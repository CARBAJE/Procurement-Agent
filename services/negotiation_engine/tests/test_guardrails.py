"""Unit tests for the deterministic policy shield (Layer 2).

These tests pin the L1 (Pydantic) + L2 (``validate_counter_offer``) safety
contract described in
``KnowledgeBase/project_scaffold/architecture/negotiation_engine/03_hard_guardrails_policy.md``.

The headline assertions:

* A **valid 15% discount** passes L1 construction and L2 validation.
* An **invalid 25% discount** is blocked — either by L1 (Pydantic raises
  ``ValidationError`` at construction) or, if the caller bypasses L1 via
  ``model_construct``, by L2 raising :class:`PolicyViolationError`.

Additional cases cover boundary conditions, the tightest-of-many G1/G2/G3
stacking, and the lead-time (G5) / available-qty (G6) rules.
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.guardrails import (
    PolicyViolationError,
    effective_max_discount_pct,
    validate_counter_offer,
)
from src.models import ABSOLUTE_MAX_DISCOUNT_PCT, CounterOffer


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_offer(**overrides) -> CounterOffer:
    """Build a CounterOffer with sensible test defaults.

    Goes through the full validator chain (L1). Use
    :func:`_make_unsafe_offer` when the test specifically wants to drive
    L2 with values that L1 would otherwise reject.
    """
    defaults: dict = {
        "target_price": 900.0,
        "target_delivery_hours": 72,
        "target_quantity": 10,
        "discount_pct": 0.10,
        "rationale": "test-fixture",
    }
    defaults.update(overrides)
    return CounterOffer(**defaults)


def _make_unsafe_offer(**overrides) -> CounterOffer:
    """Construct a CounterOffer that bypasses L1 (Pydantic) validators.

    Used to exercise L2 in isolation — required to test that
    ``validate_counter_offer`` itself catches an out-of-bound discount, not
    just that Pydantic does. ``model_construct`` is the official Pydantic v2
    escape hatch for trusted callers.
    """
    defaults: dict = {
        "target_price": 800.0,
        "target_delivery_hours": 72,
        "target_quantity": 10,
        "discount_pct": 0.10,
        "rationale": "unsafe-fixture",
    }
    defaults.update(overrides)
    return CounterOffer.model_construct(**defaults)


# ---------------------------------------------------------------------------
# Headline tests — required by the implementation brief.
# ---------------------------------------------------------------------------


def test_valid_15pct_discount_passes_l2():
    """A 15% discount with an empty policy passes the shield."""
    offer = _make_offer(discount_pct=0.15)
    assert validate_counter_offer(offer, policy={}) is True


def test_invalid_25pct_discount_blocked_at_l1():
    """L1 — Pydantic structurally rejects discount_pct > 0.20 at construction."""
    with pytest.raises(ValidationError) as excinfo:
        _make_offer(discount_pct=0.25)
    assert "discount_pct" in str(excinfo.value)


def test_invalid_25pct_discount_blocked_at_l2():
    """L2 — even when L1 is bypassed, the shield still raises PolicyViolationError."""
    unsafe = _make_unsafe_offer(discount_pct=0.25)
    with pytest.raises(PolicyViolationError) as excinfo:
        validate_counter_offer(unsafe, policy={})
    err = excinfo.value
    assert err.rule_id == "G1"
    assert err.attempted_value == 0.25
    assert err.allowed_value == ABSOLUTE_MAX_DISCOUNT_PCT


# ---------------------------------------------------------------------------
# Boundary conditions on G1
# ---------------------------------------------------------------------------


def test_boundary_20pct_passes():
    """The cap is inclusive: exactly 20% must be allowed."""
    offer = _make_offer(discount_pct=ABSOLUTE_MAX_DISCOUNT_PCT)
    assert validate_counter_offer(offer, policy={}) is True


def test_zero_pct_passes():
    """A 0% counter-offer (effectively 'accept the listed price') must pass."""
    offer = _make_offer(discount_pct=0.0)
    assert validate_counter_offer(offer, policy={}) is True


def test_negative_discount_rejected_at_l1():
    """Pydantic ge=0 must reject a negative discount."""
    with pytest.raises(ValidationError):
        _make_offer(discount_pct=-0.01)


def test_negative_discount_rejected_at_l2_when_bypassing_l1():
    """L2 also re-checks the lower bound for callers using model_construct."""
    unsafe = _make_unsafe_offer(discount_pct=-0.05)
    with pytest.raises(PolicyViolationError) as excinfo:
        validate_counter_offer(unsafe, policy={})
    assert excinfo.value.rule_id == "G1"


# ---------------------------------------------------------------------------
# G2 / G3 — tightest-of-many stacking
# ---------------------------------------------------------------------------


def test_category_override_tighter_than_g1_blocks_15pct():
    """G2 — a category cap of 10% must block a 15% counter-offer."""
    offer = _make_offer(discount_pct=0.15)
    with pytest.raises(PolicyViolationError) as excinfo:
        validate_counter_offer(offer, policy={"category_max_discount_pct": 0.10})
    assert excinfo.value.rule_id == "G2"
    assert excinfo.value.allowed_value == 0.10


def test_supplier_override_tightest_wins():
    """G3 — supplier cap is tightest; effective_max should reflect it."""
    policy = {
        "category_max_discount_pct": 0.15,
        "supplier_max_discount_pct": 0.05,
    }
    assert effective_max_discount_pct(policy) == 0.05

    offer = _make_offer(discount_pct=0.10)
    with pytest.raises(PolicyViolationError) as excinfo:
        validate_counter_offer(offer, policy=policy)
    assert excinfo.value.rule_id == "G3"
    assert excinfo.value.allowed_value == 0.05


def test_effective_max_defaults_to_g1_when_no_overrides():
    """With no per-category or per-supplier overrides, the cap is G1's 0.20."""
    assert effective_max_discount_pct({}) == ABSOLUTE_MAX_DISCOUNT_PCT


def test_effective_max_clamped_by_g1_even_if_override_too_high():
    """An override > 0.20 cannot widen the cap — G1 is always in the min."""
    policy = {"category_max_discount_pct": 0.30}
    assert effective_max_discount_pct(policy) == ABSOLUTE_MAX_DISCOUNT_PCT


# ---------------------------------------------------------------------------
# G5 — supplier lead-time minimum
# ---------------------------------------------------------------------------


def test_g5_lead_time_violation_raises():
    """Requesting delivery shorter than the supplier's minimum lead time must block."""
    offer = _make_offer(target_delivery_hours=24, discount_pct=0.05)
    with pytest.raises(PolicyViolationError) as excinfo:
        validate_counter_offer(offer, policy={"supplier_lead_time_min": 48})
    assert excinfo.value.rule_id == "G5"
    assert excinfo.value.attempted_value == 24
    assert excinfo.value.allowed_value == 48


def test_g5_boundary_equal_lead_time_passes():
    """Equal-to-minimum is allowed (>=, not >)."""
    offer = _make_offer(target_delivery_hours=48, discount_pct=0.05)
    assert validate_counter_offer(offer, policy={"supplier_lead_time_min": 48}) is True


# ---------------------------------------------------------------------------
# G6 — supplier available quantity
# ---------------------------------------------------------------------------


def test_g6_quantity_exceeds_available_raises():
    offer = _make_offer(target_quantity=100, discount_pct=0.05)
    with pytest.raises(PolicyViolationError) as excinfo:
        validate_counter_offer(offer, policy={"supplier_available_qty": 50})
    assert excinfo.value.rule_id == "G6"


def test_g6_boundary_equal_quantity_passes():
    offer = _make_offer(target_quantity=50, discount_pct=0.05)
    assert validate_counter_offer(offer, policy={"supplier_available_qty": 50}) is True


# ---------------------------------------------------------------------------
# Audit-payload shape — used to emit Kafka policy_violation_blocked events.
# ---------------------------------------------------------------------------


def test_violation_audit_payload_shape():
    """PolicyViolationError exposes a structured payload for audit emission."""
    unsafe = _make_unsafe_offer(discount_pct=0.25)
    with pytest.raises(PolicyViolationError) as excinfo:
        validate_counter_offer(unsafe, policy={})

    payload = excinfo.value.to_audit_payload()
    assert payload["rule_id"] == "G1"
    assert payload["attempted_value"] == 0.25
    assert payload["allowed_value"] == ABSOLUTE_MAX_DISCOUNT_PCT
    assert "message" in payload
