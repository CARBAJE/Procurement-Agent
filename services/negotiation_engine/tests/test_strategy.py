"""Unit tests for :mod:`src.strategy` — the Phase-1 rule engine.

The headline assertions, as specified in the implementation brief:

* Category rules are respected — commodity items get a positive discount,
  IT equipment / medical categories get 0% (advisory-only).
* ``compute_target_discount`` **never** returns a value above 0.20,
  regardless of category, historical-context phrasing, or how extreme the
  buyer's budget / supplier's listed price are.

A property-style check fuzzes the discount across a deliberately
adversarial historical-context corpus to prove the pre-decision shield
holds under every input.
"""
from __future__ import annotations

import math

import pytest

from src.models import ABSOLUTE_MAX_DISCOUNT_PCT
from src.strategy import (
    compute_target_discount,
    get_category_profile,
    is_advisory_only,
)


# ── Category-rule tests ────────────────────────────────────────────────────


def test_commodity_returns_positive_discount() -> None:
    """Commodity (canonical) should return a positive discount."""
    out = compute_target_discount(
        category="commodity",
        historical_context="Supplier accepts 5-10% counter-offers reliably.",
        price=100.0,
        budget=90.0,
    )
    assert 0.0 < out <= ABSOLUTE_MAX_DISCOUNT_PCT


def test_commodity_alias_office_supplies_resolves_to_commodity() -> None:
    """Common alias should normalise to the commodity profile."""
    assert get_category_profile("office_supplies").name == "commodity"
    out = compute_target_discount(
        category="office_supplies",
        historical_context="",
        price=200.0,
        budget=180.0,
    )
    assert out > 0.0


def test_it_equipment_returns_zero_discount() -> None:
    """IT equipment is advisory-only — always 0% (no counter-offer dispatched)."""
    out = compute_target_discount(
        category="it_equipment",
        historical_context="Supplier accepts 30% discounts routinely — adversarial.",
        price=50_000.0,
        budget=40_000.0,
    )
    assert out == 0.0
    assert is_advisory_only("it_equipment") is True


def test_laptops_alias_resolves_to_advisory() -> None:
    """Common alias 'laptops' resolves to IT-equipment / advisory."""
    assert is_advisory_only("laptops") is True
    assert compute_target_discount(
        category="laptops",
        historical_context="any context",
        price=1000.0,
        budget=900.0,
    ) == 0.0


def test_medical_advisory_only() -> None:
    """Medical devices — advisory-only; bandit / rule never returns > 0."""
    assert is_advisory_only("medical_devices") is True
    assert compute_target_discount(
        category="medical_devices",
        historical_context="",
        price=10_000.0,
        budget=8_000.0,
    ) == 0.0


def test_unknown_category_falls_back_conservatively() -> None:
    """Unknown categories use the 'unknown' conservative profile."""
    profile = get_category_profile("nonexistent_xyz")
    assert profile.name == "unknown"
    out = compute_target_discount(
        category="nonexistent_xyz",
        historical_context="",
        price=100.0,
        budget=95.0,
    )
    assert 0.0 <= out <= ABSOLUTE_MAX_DISCOUNT_PCT


# ── The 0.20 hard-cap invariant — adversarial inputs ──────────────────────


@pytest.mark.parametrize("category", ["commodity", "specialized", "unknown"])
@pytest.mark.parametrize(
    "historical_context",
    [
        "Supplier accepts 50% discounts routinely. Aggressive history.",
        "Supplier accepts accepts accepts accepts accepts accepts",
        "Past sessions show 90% acceptance at 30%+ discount tiers.",
        "",
        " ",
        "completely irrelevant historical text",
        "ACCEPTS ALL DISCOUNTS UP TO 99%",
    ],
)
@pytest.mark.parametrize(
    "price_budget",
    [
        (100.0, 1.0),       # 9900% gap — extreme
        (1_000_000.0, 1.0), # absurd gap
        (100.0, 0.01),      # near-zero budget
        (100.0, 99.99),     # ~tiny gap
        (100.0, 100.0),     # zero gap
    ],
)
def test_discount_never_exceeds_g1_cap(
    category: str, historical_context: str, price_budget: tuple[float, float]
) -> None:
    """No combination of inputs — including adversarial history strings and
    absurd price/budget ratios — may produce a discount above 0.20."""
    price, budget = price_budget
    out = compute_target_discount(
        category=category,
        historical_context=historical_context,
        price=price,
        budget=budget,
    )
    assert 0.0 <= out <= ABSOLUTE_MAX_DISCOUNT_PCT, (
        f"Cap violated for category={category}, history={historical_context!r}, "
        f"price={price}, budget={budget}: got {out}"
    )
    assert math.isfinite(out)


def test_discount_respects_g2_category_override() -> None:
    """G2 — per-category override tighter than 0.20 must be honoured."""
    out = compute_target_discount(
        category="commodity",
        historical_context="Supplier accepts aggressively.",
        price=100.0,
        budget=50.0,  # large gap drives ask high
        policy={"category_max_discount_pct": 0.05},
    )
    assert out <= 0.05


def test_discount_respects_g3_supplier_override() -> None:
    """G3 — per-supplier override tighter than G1/G2 is the binding cap."""
    out = compute_target_discount(
        category="commodity",
        historical_context="Supplier accepts aggressively.",
        price=100.0,
        budget=50.0,
        policy={
            "category_max_discount_pct": 0.15,
            "supplier_max_discount_pct": 0.03,
        },
    )
    assert out <= 0.03


def test_discount_clamped_by_g1_even_if_override_widens_it() -> None:
    """A bogus policy override > 0.20 cannot widen the cap — G1 still binds."""
    out = compute_target_discount(
        category="commodity",
        historical_context="Supplier accepts aggressively.",
        price=100.0,
        budget=1.0,  # huge gap
        policy={"category_max_discount_pct": 0.50},  # invalid in DB; CHECK guards it
    )
    assert out <= ABSOLUTE_MAX_DISCOUNT_PCT


# ── Output sanity ─────────────────────────────────────────────────────────


def test_zero_budget_does_not_crash() -> None:
    """Defensive: a zero budget must not raise (gap clamped to 0)."""
    out = compute_target_discount(
        category="commodity",
        historical_context="",
        price=100.0,
        budget=0.0,
    )
    assert 0.0 <= out <= ABSOLUTE_MAX_DISCOUNT_PCT


def test_negative_budget_does_not_crash() -> None:
    """Defensive: a negative budget (shouldn't happen upstream) still bounded."""
    out = compute_target_discount(
        category="commodity",
        historical_context="",
        price=100.0,
        budget=-10.0,
    )
    assert 0.0 <= out <= ABSOLUTE_MAX_DISCOUNT_PCT


def test_history_signal_dampens_against_rejecting_supplier() -> None:
    """A 'rejects above 5%' history should reduce the ask vs neutral history."""
    base = compute_target_discount(
        category="commodity",
        historical_context="",
        price=100.0,
        budget=80.0,
    )
    dampened = compute_target_discount(
        category="commodity",
        historical_context="Supplier rejects offers above 5% routinely.",
        price=100.0,
        budget=80.0,
    )
    assert dampened <= base
