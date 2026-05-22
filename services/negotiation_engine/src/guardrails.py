"""Deterministic policy guardrails — Layer 2 of the safety shield.

This module implements the L2 enforcement layer described in
``KnowledgeBase/project_scaffold/architecture/negotiation_engine/03_hard_guardrails_policy.md``.
It is a pure-function policy gateway: ``(CounterOffer, policy) -> True | raise``.

The shield is **architecturally independent** of any LLM, bandit, or rule
engine that *proposed* the counter-offer:

* L1 — Pydantic structural validation lives in :mod:`.models` and rejects
  ``discount_pct`` outside ``[0.0, 0.20]`` at construction time.
* L2 — this module — re-validates against the *session policy* (per-category
  G2, per-supplier G3, lead-time G5, available-qty G6) and computes the
  *tightest-of-many* effective cap.
* L3 — schema validation at the ``onix-bap`` perimeter rejects malformed
  Beckn wire payloads.

Any of the three layers is individually sufficient to block a violating
action; promoting them to independent layers gives defence-in-depth.
"""
from __future__ import annotations

import logging
from typing import Any

from .models import ABSOLUTE_MAX_DISCOUNT_PCT, CounterOffer

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Custom exception
# ---------------------------------------------------------------------------


class PolicyViolationError(Exception):
    """Raised when a counter-offer violates a deterministic policy guardrail.

    The exception carries the structured fields needed to emit the
    canonical ``negotiation.policy_violation_blocked`` Kafka event without
    further parsing.
    """

    def __init__(
        self,
        rule_id: str,
        attempted_value: Any,
        allowed_value: Any,
        message: str | None = None,
    ) -> None:
        self.rule_id = rule_id
        self.attempted_value = attempted_value
        self.allowed_value = allowed_value
        super().__init__(
            message
            or f"Policy violation {rule_id}: attempted={attempted_value!r}, allowed={allowed_value!r}"
        )

    def to_audit_payload(self) -> dict:
        """Serialise to the audit envelope shape (mirrors Kafka payload)."""
        return {
            "rule_id": self.rule_id,
            "attempted_value": self.attempted_value,
            "allowed_value": self.allowed_value,
            "message": str(self),
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def effective_max_discount_pct(policy: dict) -> float:
    """Compute the *tightest-of-G1/G2/G3* maximum allowed discount.

    Per ``03_hard_guardrails_policy.md`` §G1-G3 stacking, the effective cap
    for a given (category, supplier) pair is the minimum of:

    * G1 — :data:`ABSOLUTE_MAX_DISCOUNT_PCT` (0.20, non-negotiable).
    * G2 — ``policy["category_max_discount_pct"]`` if set.
    * G3 — ``policy["supplier_max_discount_pct"]`` if set.

    Returns a value in ``[0.0, ABSOLUTE_MAX_DISCOUNT_PCT]``.
    """
    candidates: list[float] = [ABSOLUTE_MAX_DISCOUNT_PCT]  # G1
    cat = policy.get("category_max_discount_pct")
    if cat is not None:
        candidates.append(float(cat))  # G2
    sup = policy.get("supplier_max_discount_pct")
    if sup is not None:
        candidates.append(float(sup))  # G3
    return min(candidates)


# ---------------------------------------------------------------------------
# The shield
# ---------------------------------------------------------------------------


def validate_counter_offer(offer: CounterOffer, policy: dict) -> bool:
    """Deterministic policy shield — the canonical L2 enforcement point.

    Evaluates the proposed ``offer`` against every applicable guardrail
    rule for the session. Returns ``True`` if all rules are satisfied;
    raises :class:`PolicyViolationError` otherwise.

    Parameters
    ----------
    offer:
        The proposed counter-offer. Construction of this object already
        passed L1 (Pydantic) validation, so ``discount_pct`` is structurally
        in ``[0.0, 0.20]`` — but we re-check anyway for callers that bypass
        the constructor (e.g. ``model_construct``) and to make the L2
        contract self-contained.
    policy:
        The session policy dict, loaded once at session start from the
        ``negotiation_strategy`` PostgreSQL row. Recognised keys:

        * ``category_max_discount_pct`` (float, optional) — G2.
        * ``supplier_max_discount_pct`` (float, optional) — G3.
        * ``supplier_lead_time_min`` (int hours, optional) — G5.
        * ``supplier_available_qty`` (int, optional) — G6.

        Any unknown keys are ignored; missing keys disable their guardrail.

    Returns
    -------
    bool
        Always ``True`` on success. The boolean return is preserved for
        callers who want to use this as a predicate; failure is signalled
        only via the exception.

    Raises
    ------
    PolicyViolationError
        On the first failing rule. The error carries ``rule_id``,
        ``attempted_value``, and ``allowed_value`` for audit serialisation.
    """
    # G1 — absolute hard cap (re-checked independently of Pydantic L1).
    if offer.discount_pct < 0.0:
        raise PolicyViolationError(
            rule_id="G1",
            attempted_value=offer.discount_pct,
            allowed_value=f"[0.0, {ABSOLUTE_MAX_DISCOUNT_PCT}]",
            message=f"G1: discount_pct={offer.discount_pct!r} must be non-negative",
        )
    if offer.discount_pct > ABSOLUTE_MAX_DISCOUNT_PCT:
        raise PolicyViolationError(
            rule_id="G1",
            attempted_value=offer.discount_pct,
            allowed_value=ABSOLUTE_MAX_DISCOUNT_PCT,
            message=(
                f"G1: discount_pct={offer.discount_pct:.4f} exceeds "
                f"absolute hard cap {ABSOLUTE_MAX_DISCOUNT_PCT}"
            ),
        )

    # G2 + G3 — tightest-of-many. ``effective_max`` is always <= 0.20.
    effective_max = effective_max_discount_pct(policy)
    if offer.discount_pct > effective_max:
        # Discriminate which of G2 / G3 was the binding constraint for the
        # audit log; if both are tighter, attribute to whichever is smaller.
        cat = policy.get("category_max_discount_pct")
        sup = policy.get("supplier_max_discount_pct")
        if sup is not None and float(sup) == effective_max:
            rule_id = "G3"
        elif cat is not None and float(cat) == effective_max:
            rule_id = "G2"
        else:  # pragma: no cover — only reachable if effective_max == G1.
            rule_id = "G2_G3"
        raise PolicyViolationError(
            rule_id=rule_id,
            attempted_value=offer.discount_pct,
            allowed_value=effective_max,
            message=(
                f"{rule_id}: discount_pct={offer.discount_pct:.4f} exceeds "
                f"effective cap {effective_max:.4f} for this (category, supplier)"
            ),
        )

    # G5 — requested delivery >= supplier lead-time minimum.
    lead_min = policy.get("supplier_lead_time_min")
    if lead_min is not None:
        lead_min_int = int(lead_min)
        if offer.target_delivery_hours < lead_min_int:
            raise PolicyViolationError(
                rule_id="G5",
                attempted_value=offer.target_delivery_hours,
                allowed_value=lead_min_int,
                message=(
                    f"G5: requested delivery {offer.target_delivery_hours}h is "
                    f"shorter than supplier lead-time minimum {lead_min_int}h"
                ),
            )

    # G6 — requested quantity <= supplier available quantity.
    avail = policy.get("supplier_available_qty")
    if avail is not None:
        avail_int = int(avail)
        if offer.target_quantity > avail_int:
            raise PolicyViolationError(
                rule_id="G6",
                attempted_value=offer.target_quantity,
                allowed_value=avail_int,
                message=(
                    f"G6: requested qty {offer.target_quantity} exceeds "
                    f"supplier available qty {avail_int}"
                ),
            )

    logger.debug(
        "validate_counter_offer: PASS discount=%.4f effective_max=%.4f",
        offer.discount_pct,
        effective_max,
    )
    return True


__all__ = [
    "PolicyViolationError",
    "effective_max_discount_pct",
    "validate_counter_offer",
]
