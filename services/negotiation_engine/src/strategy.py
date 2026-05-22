"""Negotiation strategy engine — Phase 1 rule-based, Phase 2 bandit-ready.

This module implements the *probabilistic + heuristic* layer of the
engine that lives **under** the deterministic safety shield. The
strategy decides *what to offer*; the shield in ``guardrails.py``
decides whether the offer is permitted on the wire.

Phase 1 (this implementation):
    A per-category decision table maps ``category → archetype →
    base_discount × alpha × gamma``. Pure functions, no LLM, no I/O.
    Output is pre-decision-shielded to ``[0, effective_max]``.

Phase 2 (planned, hooks marked inline):
    A Vowpal Wabbit Contextual Bandit (``vw --cb_explore_adf``) trained
    on past Qdrant outcomes provides ``discount_pct`` selection from a
    masked arm set. See ``02_decision_intelligence_rl.md`` §3.

The 20 % hard ceiling is enforced by an **action-mask** (per
``03_hard_guardrails_policy.md`` §3.3) — never by reward shaping. The
unsafe arm is structurally absent from the choice set, so neither rule
nor bandit can ever return a value above
:data:`models.ABSOLUTE_MAX_DISCOUNT_PCT`.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Literal

from .guardrails import effective_max_discount_pct
from .models import ABSOLUTE_MAX_DISCOUNT_PCT

logger = logging.getLogger(__name__)


# ── Category archetypes ───────────────────────────────────────────────────

#: The closed set of category archetypes recognised by the Phase-1 engine.
#: Each maps onto a row of the ``negotiation_strategy`` PostgreSQL table.
CategoryArchetype = Literal[
    "commodity",
    "specialized",
    "it_equipment",
    "medical",
    "unknown",
]


@dataclass(frozen=True)
class CategoryProfile:
    """Per-category baseline parameters.

    Attributes
    ----------
    name:
        Canonical archetype name.
    base_discount:
        Rule-table baseline ask (``DiscoveryRule`` floor) before any
        ``alpha × gamma`` modulation. In ``[0, 0.20]``.
    alpha_multiplier:
        Aggressiveness factor — sensitive categories use a lower value so
        the engine asks for less even when the buyer-side gap is wide.
    advisory_only:
        If ``True``, the category mandates an advisory recommendation
        only — the engine never counter-offers. Downstream the graph
        routes to ``evaluate_ambiguous_terms`` instead of
        ``dispatch_select``.
    """

    name: CategoryArchetype
    base_discount: float
    alpha_multiplier: float
    advisory_only: bool


# Phase-1 decision table. In production the canonical source is the
# ``negotiation_strategy_rules`` PostgreSQL table (next free migration
# ``20_negotiation_strategy.sql``); the values here are the bootstrap
# defaults that match ``02_decision_intelligence_rl.md`` §2.
_CATEGORY_TABLE: dict[str, CategoryProfile] = {
    "commodity":    CategoryProfile("commodity",    0.10, 1.00, False),
    "specialized":  CategoryProfile("specialized",  0.05, 0.70, False),
    "it_equipment": CategoryProfile("it_equipment", 0.00, 0.50, True),
    "medical":      CategoryProfile("medical",      0.00, 0.40, True),
    "unknown":      CategoryProfile("unknown",      0.05, 0.60, False),
}

# Common category synonyms / Beckn-side spellings normalised to archetypes.
_CATEGORY_ALIASES: dict[str, str] = {
    "office_supplies":  "commodity",
    "stationery":       "commodity",
    "cabling":          "commodity",
    "cables":           "commodity",
    "raw_materials":    "commodity",
    "laptops":          "it_equipment",
    "servers":          "it_equipment",
    "enterprise_it":    "it_equipment",
    "it":               "it_equipment",
    "networking":       "it_equipment",
    "medical_devices":  "medical",
    "pharma":           "medical",
    "pharmaceuticals":  "medical",
    "machinery":        "specialized",
    "industrial":       "specialized",
}


# ── Helpers ───────────────────────────────────────────────────────────────


def _resolve_profile(category: str) -> CategoryProfile:
    """Look up a profile, normalising case, whitespace and known synonyms."""
    if not category:
        return _CATEGORY_TABLE["unknown"]
    key = category.strip().lower().replace("-", "_").replace(" ", "_")
    key = _CATEGORY_ALIASES.get(key, key)
    return _CATEGORY_TABLE.get(key, _CATEGORY_TABLE["unknown"])


def _gap_pct(price: float, budget: float) -> float:
    """Return ``(price - budget) / budget``, clamped to ``[0, +inf)``."""
    if budget <= 0:
        return 0.0
    return max(0.0, (price - budget) / budget)


def _historical_signal(historical_context: str) -> float:
    """Extract a coarse γ-multiplier from the prose history.

    Cheap keyword scan only — no LLM. Phase 2 replaces this with the
    bandit's learned reward predictor over the 64-dim context vector.

    Returns
    -------
    float
        Multiplier in ``[0.7, 1.1]``:
          * ``< 1.0`` dampens aggression (history shows rejections / cold-start).
          * ``> 1.0`` amplifies aggression (history shows consistent acceptance).
          * ``1.0`` for neutral / no signal.
    """
    if not historical_context:
        return 1.0

    text = historical_context.lower()
    if re.search(r"\brejects?\b|\brejected\b|cold[- ]start|conservative", text):
        return 0.7
    if re.search(r"\baccepts?\b|\baccepted\b", text):
        return 1.1
    return 1.0


# ── Public API ────────────────────────────────────────────────────────────


def compute_target_discount(
    category: str,
    historical_context: str,
    price: float,
    budget: float,
    policy: dict | None = None,
) -> float:
    """Compute the target discount fraction to request from the supplier.

    Phase-1 deterministic rule engine. The return value is **guaranteed**
    to lie in ``[0.0, effective_max]`` where ``effective_max`` is the
    tightest of guardrails G1 (0.20), G2 (per-category), and G3
    (per-supplier) — i.e. *pre-decision shielding* mirrors the
    action-masking pattern from ``03_hard_guardrails_policy`` §3.3.

    Parameters
    ----------
    category:
        Procurement category slug (free-form; aliases are normalised,
        unknown values fall back to a conservative profile).
    historical_context:
        Prose summary from ``get_supplier_negotiation_history``. Optional;
        empty string is treated as "no signal".
    price:
        Supplier's listed unit price.
    budget:
        Buyer's target / budgeted unit price. Drives the ``gap_pct`` term.
    policy:
        Session policy dict (optional). Recognised keys for shielding:
        ``category_max_discount_pct`` (G2), ``supplier_max_discount_pct``
        (G3). Unknown keys are ignored.

    Returns
    -------
    float
        Discount fraction in ``[0.0, min(effective_max, 0.20)]``.
    """
    profile = _resolve_profile(category)

    # Advisory categories deliberately never counter-offer. Returning 0.0
    # here is a strong signal to downstream nodes (``compute_counter_offer``
    # and the router) that the engine should route to
    # ``evaluate_ambiguous_terms`` instead of ``dispatch_select``.
    if profile.advisory_only:
        logger.debug(
            "strategy: advisory_only category %r → returning 0%% discount",
            profile.name,
        )
        return 0.0

    # Tightest-of-(G1, G2, G3) ceiling. Always ≤ ABSOLUTE_MAX_DISCOUNT_PCT.
    effective_max = effective_max_discount_pct(policy or {})

    # ──────────────────────────────────────────────────────────────────
    # Phase-1 formula:
    #     raw_target = max(base_discount, gap_pct × α_category) × γ_supplier
    # (β_round dampener belongs in ``evaluate_response`` — not here.)
    # ──────────────────────────────────────────────────────────────────
    #
    # Phase-2 hook — replace the block below with a bandit call:
    #
    #     context_vec = build_context_vector(profile, historical_context,
    #                                        price, budget, policy)
    #     mask = shielded_arms(ARM_DISCOUNT_BUCKETS, effective_max)
    #     arm_idx, propensity = vw_model.predict(context_vec, mask=mask)
    #     log_propensity(transaction_id, round_no, arm_idx, propensity)
    #     return ARM_DISCOUNT_BUCKETS[arm_idx]
    #
    # where ``vw_model`` is loaded once at startup, ``ARM_DISCOUNT_BUCKETS``
    # is ``[0.0, 0.025, 0.05, 0.075, 0.10, 0.125, 0.15, 0.175, 0.20]``, and
    # ``shielded_arms`` filters the bucket list to those ≤ effective_max
    # before the softmax (see ``02_decision_intelligence_rl.md`` §3.3).
    # ──────────────────────────────────────────────────────────────────
    gamma_supplier = _historical_signal(historical_context)
    gap = _gap_pct(price, budget)
    raw_target = max(profile.base_discount, gap * profile.alpha_multiplier) * gamma_supplier

    # Pre-decision shielding — clamp to the effective ceiling.
    shielded = max(0.0, min(raw_target, effective_max))

    # Belt-and-braces: even if ``effective_max`` were somehow > 0.20 (it
    # cannot, by construction of ``effective_max_discount_pct``), the
    # absolute G1 ceiling still applies. Defence-in-depth.
    final = min(shielded, ABSOLUTE_MAX_DISCOUNT_PCT)
    logger.debug(
        "strategy: category=%s gap=%.4f γ=%.2f raw=%.4f shielded=%.4f effective_max=%.4f",
        profile.name, gap, gamma_supplier, raw_target, final, effective_max,
    )
    return final


def is_advisory_only(category: str) -> bool:
    """Return ``True`` if the category mandates advisory-only mode.

    Convenience predicate used by ``nodes.py`` to decide whether the
    LangGraph router should branch to ``evaluate_ambiguous_terms``
    instead of ``compute_counter_offer``.
    """
    return _resolve_profile(category).advisory_only


def get_category_profile(category: str) -> CategoryProfile:
    """Return the canonical :class:`CategoryProfile` for a (possibly aliased) category."""
    return _resolve_profile(category)


__all__ = [
    "ABSOLUTE_MAX_DISCOUNT_PCT",
    "CategoryArchetype",
    "CategoryProfile",
    "compute_target_discount",
    "get_category_profile",
    "is_advisory_only",
]
