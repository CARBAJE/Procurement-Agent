"""
Milestone: NL Intent Parser
Validates that 15+ diverse natural-language procurement requests are correctly
parsed into valid Beckn-compatible structured intents (ParseResult + BecknIntent).
"""
import pytest

from IntentParser import parse_request
from IntentParser.schemas import ParseResult

# ── 16 procurement queries — diverse products, cities, units, timelines, budgets ──

PROCUREMENT_QUERIES = [
    "I need 500 units of A4 printer paper 80gsm delivered to Bangalore within 5 days, budget under 2 rupees per sheet",
    "Quote for 200 meters of UTP Cat6 cable for Mumbai office, delivery in 3 days, max 15 INR per meter",
    "50 stainless steel 2-inch gate valves for Chennai plant, deliver in 1 week, max 1500 INR each",
    "100 ISI-certified safety helmets for Hyderabad warehouse, within 48 hours, budget max 800 INR each",
    "10 Dell Latitude 5540 laptops for Delhi office, 7-day delivery, budget under 70000 INR per unit",
    "20 electric motors 5HP 415V for Pune factory, delivery in 2 weeks, max 12000 INR each",
    "300 HEPA H14 filters 610x610mm for Kolkata cleanroom, 10 days delivery, budget max 3500 INR each",
    "5000 M8×30 hex bolts Grade 8.8 galvanized for Mumbai docks, 4-day delivery, 5 INR per piece",
    "150 meters of hydraulic hose 1/4 inch SAE100R2 for Pune plant, within 72 hours, max 120 INR per meter",
    "200 units of 25mm PVC electrical conduit 3m length for Bangalore site, 3-day delivery, max 150 INR each",
    "1000 pairs of nitrile industrial gloves size L for Hyderabad, 48 hours delivery, under 30 INR per pair",
    "30 LED flood lights 200W IP65 for Chennai warehouse, 5-day delivery, max 2500 INR each",
    "10 compressed air cylinders 50L 150 bar for Delhi depot, 1 week delivery, max 15000 INR each",
    "500 square meters of 200GSM HDPE tarpaulin for Mumbai project, 3-day delivery, max 45 INR per sqm",
    "25 ergonomic office chairs with lumbar support for Bengaluru HQ, 10 days, budget max 8000 INR each",
    "20 rolls of 80mm thermal paper for Pune POS systems, same-day delivery, max 150 INR per roll",
]

NON_PROCUREMENT_QUERIES = [
    "Good morning, can you help me?",
    "What are your working hours?",
]


# ── Assertions ────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("query", PROCUREMENT_QUERIES)
def test_procurement_query_yields_valid_beckn_intent(query: str) -> None:
    result = parse_request(query)
    print(f"\n{result.model_dump_json(indent=2)}")

    assert isinstance(result, ParseResult)
    assert result.intent, "intent must not be empty"
    assert result.confidence is not None
    assert result.beckn_intent is not None, (
        f"Expected a BecknIntent for procurement query:\n  {query}"
    )

    bi = result.beckn_intent
    assert bi.item.strip(),          "item must not be empty"
    assert bi.quantity > 0,          "quantity must be a positive integer"
    assert bi.delivery_timeline > 0, "delivery_timeline must be positive (hours)"
    assert bi.budget_constraints.max > 0, "budget max must be a positive number"
    assert isinstance(bi.descriptions, list), "descriptions must be a list"


@pytest.mark.parametrize("query", NON_PROCUREMENT_QUERIES)
def test_non_procurement_query_has_no_beckn_intent(query: str) -> None:
    result = parse_request(query)
    print(f"\n{result.model_dump_json(indent=2)}")
    assert result.beckn_intent is None, (
        f"Expected no BecknIntent for non-procurement query:\n  {query}"
    )
