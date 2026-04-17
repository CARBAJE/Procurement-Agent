"""Tests for the NL Intent Parser bridge (IntentParser → Bap-1).

Unit tests (always run):
    Mock IntentParser.core.parse_request — test bridge conversion logic only.
    No Ollama required.

Integration tests (opt-in):
    Real Ollama calls. Skipped in CI. Run with:
        pytest tests/test_intent_parser.py -v -m integration

Run unit tests only:
    pytest tests/test_intent_parser.py -v -k "not integration"
"""
from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from src.beckn.models import BecknIntent, BudgetConstraints
from src.nlp.intent_parser_facade import parse_nl_to_intent


# ── Fixtures / helpers ────────────────────────────────────────────────────────


def _make_parse_result(
    intent: str = "SearchProduct",
    beckn_intent=None,
    confidence: float = 0.95,
):
    """Build a ParseResult for use as parse_request() mock return value."""
    from IntentParser.schemas import ParseResult

    return ParseResult(intent=intent, confidence=confidence, beckn_intent=beckn_intent)


def _make_parsed_beckn_intent(
    item: str = "A4 paper",
    descriptions: list[str] | None = None,
    quantity: int = 100,
    location_coordinates: str = "12.9716,77.5946",
    delivery_timeline: int = 72,
    budget_max: float = 200.0,
):
    """Build a BecknIntent for use as parse_request() mock return value."""
    return BecknIntent(
        item=item,
        descriptions=descriptions or [],
        quantity=quantity,
        location_coordinates=location_coordinates,
        delivery_timeline=delivery_timeline,
        budget_constraints=BudgetConstraints(max=budget_max),
    )


# ── Unit tests — bridge conversion (no LLM) ──────────────────────────────────


def test_bridge_returns_none_for_non_procurement():
    result = _make_parse_result(intent="GeneralInquiry", beckn_intent=None)
    with patch("src.nlp.intent_parser_facade.parse_request", return_value=result):
        assert parse_nl_to_intent("Good morning") is None


def test_bridge_converts_to_bap_beckn_intent():
    parsed_bi = _make_parsed_beckn_intent(item="A4 paper", quantity=100)
    result = _make_parse_result(beckn_intent=parsed_bi)
    with patch("src.nlp.intent_parser_facade.parse_request", return_value=result):
        intent = parse_nl_to_intent("100 units A4 paper")
    assert isinstance(intent, BecknIntent)
    assert intent.item == "A4 paper"
    assert intent.quantity == 100


def test_bridge_preserves_delivery_timeline_in_hours():
    """Timeline must be int hours (72 = 3 days), NOT an ISO 8601 string."""
    parsed_bi = _make_parsed_beckn_intent(delivery_timeline=72)
    result = _make_parse_result(beckn_intent=parsed_bi)
    with patch("src.nlp.intent_parser_facade.parse_request", return_value=result):
        intent = parse_nl_to_intent("A4 paper, 3 days")
    assert intent.delivery_timeline == 72
    assert isinstance(intent.delivery_timeline, int)


def test_bridge_preserves_budget_constraints():
    parsed_bi = _make_parsed_beckn_intent(budget_max=500.0)
    result = _make_parse_result(beckn_intent=parsed_bi)
    with patch("src.nlp.intent_parser_facade.parse_request", return_value=result):
        intent = parse_nl_to_intent("A4 paper, budget 500")
    assert isinstance(intent.budget_constraints, BudgetConstraints)
    assert intent.budget_constraints.max == 500.0
    assert intent.budget_constraints.min == 0.0


def test_bridge_preserves_location_coordinates():
    """location_coordinates must be a 'lat,lon' decimal string."""
    parsed_bi = _make_parsed_beckn_intent(location_coordinates="12.9716,77.5946")
    result = _make_parse_result(beckn_intent=parsed_bi)
    with patch("src.nlp.intent_parser_facade.parse_request", return_value=result):
        intent = parse_nl_to_intent("A4 paper Bangalore")
    assert intent.location_coordinates == "12.9716,77.5946"


def test_bridge_preserves_descriptions_list():
    parsed_bi = _make_parsed_beckn_intent(descriptions=["80gsm", "A4", "white"])
    result = _make_parse_result(beckn_intent=parsed_bi)
    with patch("src.nlp.intent_parser_facade.parse_request", return_value=result):
        intent = parse_nl_to_intent("500 A4 80gsm white paper")
    assert isinstance(intent.descriptions, list)
    assert "80gsm" in intent.descriptions
    assert "A4" in intent.descriptions


def test_bridge_result_accepted_by_adapter():
    """BecknIntent from the bridge must pass through build_discover_request."""
    from src.beckn.adapter import BecknProtocolAdapter
    from src.config import BecknConfig

    parsed_bi = _make_parsed_beckn_intent(
        item="A4 paper 80gsm",
        descriptions=["A4", "80gsm"],
        quantity=500,
        location_coordinates="12.9716,77.5946",
        delivery_timeline=72,
        budget_max=200.0,
    )
    result = _make_parse_result(beckn_intent=parsed_bi)
    with patch("src.nlp.intent_parser_facade.parse_request", return_value=result):
        intent = parse_nl_to_intent("500 A4 paper 80gsm Bangalore 3 days under 200 INR")

    config = BecknConfig(
        bap_id="test-bap",
        bap_uri="http://localhost:8000",
        onix_url="http://localhost:8081",
    )
    request = BecknProtocolAdapter(config).build_discover_request(intent)
    assert request.message == intent
    assert request.context.action == "discover"


# ── Integration tests (requires Ollama, skipped in CI) ───────────────────────

_skip_in_ci = pytest.mark.skipif(
    os.getenv("CI") == "true",
    reason="Ollama not available in CI",
)

_INTEGRATION_CASES = [
    (
        "500 units A4 paper 80gsm delivered to Bangalore within 3 days, budget under 200 INR per ream",
        500,
        72,
        200.0,
    ),
    (
        "10 Dell laptops for Delhi office, 7-day delivery, budget under 70000 INR per unit",
        10,
        168,
        70000.0,
    ),
    (
        "1000 pairs nitrile gloves size L for Hyderabad, 48 hours, max 30 INR per pair",
        1000,
        48,
        30.0,
    ),
]


@pytest.mark.integration
@_skip_in_ci
@pytest.mark.parametrize("query,min_qty,max_timeline_h,max_budget", _INTEGRATION_CASES)
def test_integration_parse_nl_to_intent(query, min_qty, max_timeline_h, max_budget):
    """End-to-end: NL query → BecknIntent via real Ollama."""
    intent = parse_nl_to_intent(query)

    assert intent is not None, f"Expected procurement intent for: {query!r}"
    assert isinstance(intent, BecknIntent)
    assert intent.quantity >= min_qty
    assert 0 < intent.delivery_timeline <= max_timeline_h * 2  # allow 2× tolerance
    assert intent.budget_constraints is not None
    assert intent.budget_constraints.max > 0
    assert intent.location_coordinates is not None
