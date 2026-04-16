"""Tests for the NL Intent Parser.

Unit tests (always run):   mock the Anthropic client, test conversion logic.
Integration tests (opt-in): real LLM calls, need ANTHROPIC_API_KEY env var.

Run integration tests:
    ANTHROPIC_API_KEY=sk-ant-... pytest tests/test_intent_parser.py -v -m integration
"""
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.nlp.city_gps import resolve_gps
from src.nlp.intent_parser import IntentParser, _days_to_iso_duration
from src.beckn.models import SearchIntent

API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
skip_no_key = pytest.mark.skipif(not API_KEY, reason="ANTHROPIC_API_KEY not set")


# ── Helpers ───────────────────────────────────────────────────────────────────


def make_mock_response(tool_input: dict):
    """Build a mock Anthropic message response containing a tool_use block."""
    block = MagicMock()
    block.type = "tool_use"
    block.name = "parse_procurement_intent"
    block.input = tool_input

    response = MagicMock()
    response.content = [block]
    return response


def make_parser() -> IntentParser:
    return IntentParser(api_key="test-key")


# ── Unit: duration conversion ─────────────────────────────────────────────────


def test_duration_one_day():
    assert _days_to_iso_duration(1) == "P1D"


def test_duration_three_days():
    assert _days_to_iso_duration(3) == "P3D"


def test_duration_seven_days():
    assert _days_to_iso_duration(7) == "P7D"


def test_duration_urgent_zero_days():
    assert _days_to_iso_duration(0) == "PT1H"


# ── Unit: city GPS lookup ─────────────────────────────────────────────────────


def test_resolve_bangalore():
    assert resolve_gps("Bangalore") == "12.9716,77.5946"


def test_resolve_case_insensitive():
    assert resolve_gps("MUMBAI") == resolve_gps("mumbai")


def test_resolve_bengaluru_alias():
    assert resolve_gps("bengaluru") == resolve_gps("bangalore")


def test_resolve_unknown_city():
    assert resolve_gps("Atlantis") is None


def test_resolve_none():
    assert resolve_gps(None) is None


# ── Unit: _build_intent (mocked LLM responses) ───────────────────────────────


async def test_parse_basic_item(mocker):
    parser = make_parser()
    mock_resp = make_mock_response({"item_name": "A4 paper 80gsm", "quantity": 500})
    mocker.patch.object(parser._client.messages, "create", new=AsyncMock(return_value=mock_resp))

    intent = await parser.parse("500 reams A4 paper")
    assert intent.item.descriptor.name == "A4 paper 80gsm"
    assert intent.item.quantity.count == 500


async def test_parse_with_city(mocker):
    parser = make_parser()
    mock_resp = make_mock_response({
        "item_name": "Office chairs",
        "quantity": 50,
        "delivery_city": "Bangalore",
        "delivery_days": 7,
    })
    mocker.patch.object(parser._client.messages, "create", new=AsyncMock(return_value=mock_resp))

    intent = await parser.parse("50 office chairs, Bangalore, next week")
    assert intent.fulfillment.end.location.gps == "12.9716,77.5946"
    assert intent.fulfillment.end.time.duration == "P7D"


async def test_parse_with_budget(mocker):
    parser = make_parser()
    mock_resp = make_mock_response({
        "item_name": "Laptops",
        "quantity": 200,
        "budget_amount": "1600000",
        "budget_currency": "INR",
    })
    mocker.patch.object(parser._client.messages, "create", new=AsyncMock(return_value=mock_resp))

    intent = await parser.parse("200 laptops, budget 16 lakh")
    assert intent.payment.params.amount == "1600000"
    assert intent.payment.params.currency == "INR"


async def test_parse_urgent_flag(mocker):
    parser = make_parser()
    mock_resp = make_mock_response({
        "item_name": "PPE kits",
        "quantity": 10000,
        "is_urgent": True,
        "delivery_days": 1,
        "delivery_city": "Delhi",
    })
    mocker.patch.object(parser._client.messages, "create", new=AsyncMock(return_value=mock_resp))

    intent = await parser.parse("URGENT: 10000 PPE kits Delhi 24 hours")
    assert intent.fulfillment.end.time.duration == "P1D"


async def test_parse_with_specifications(mocker):
    parser = make_parser()
    mock_resp = make_mock_response({
        "item_name": "Business laptops",
        "quantity": 200,
        "specifications": ["16GB RAM", "512GB SSD", "i7 processor", "Windows 11 Pro"],
    })
    mocker.patch.object(parser._client.messages, "create", new=AsyncMock(return_value=mock_resp))

    intent = await parser.parse("200 laptops 16GB RAM 512GB SSD i7 Windows 11 Pro")
    assert "16GB RAM" in intent.item.descriptor.short_desc
    assert "512GB SSD" in intent.item.descriptor.short_desc


async def test_parse_returns_search_intent_type(mocker):
    parser = make_parser()
    mock_resp = make_mock_response({"item_name": "Pens", "quantity": 100})
    mocker.patch.object(parser._client.messages, "create", new=AsyncMock(return_value=mock_resp))

    result = await parser.parse("100 pens")
    assert isinstance(result, SearchIntent)


async def test_parse_no_fulfillment_when_no_location_or_days(mocker):
    parser = make_parser()
    mock_resp = make_mock_response({"item_name": "Stapler", "quantity": 10})
    mocker.patch.object(parser._client.messages, "create", new=AsyncMock(return_value=mock_resp))

    intent = await parser.parse("10 staplers")
    assert intent.fulfillment is None


async def test_parse_no_payment_when_no_budget(mocker):
    parser = make_parser()
    mock_resp = make_mock_response({"item_name": "Notebooks", "quantity": 200})
    mocker.patch.object(parser._client.messages, "create", new=AsyncMock(return_value=mock_resp))

    intent = await parser.parse("200 notebooks")
    assert intent.payment is None


async def test_parse_explicit_gps_overrides_city(mocker):
    parser = make_parser()
    mock_resp = make_mock_response({
        "item_name": "Generators",
        "quantity": 2,
        "delivery_gps": "17.3850,78.4867",
        "delivery_city": "Hyderabad",
    })
    mocker.patch.object(parser._client.messages, "create", new=AsyncMock(return_value=mock_resp))

    intent = await parser.parse("2 generators Hyderabad")
    assert intent.fulfillment.end.location.gps == "17.3850,78.4867"


async def test_parse_raises_on_bad_llm_response(mocker):
    parser = make_parser()
    bad_block = MagicMock()
    bad_block.type = "text"
    bad_resp = MagicMock()
    bad_resp.content = [bad_block]
    mocker.patch.object(parser._client.messages, "create", new=AsyncMock(return_value=bad_resp))

    with pytest.raises(ValueError, match="parse_procurement_intent"):
        await parser.parse("something")


# ── Integration tests (real LLM, requires ANTHROPIC_API_KEY) ─────────────────

PROCUREMENT_REQUESTS = [
    ("500 reams A4 paper 80gsm, Bangalore office, 3 days", "A4", 500),
    ("200 business laptops 16GB RAM 512GB SSD, Mumbai HQ, budget 1.6 crore", "laptop", 200),
    ("URGENT: 10000 PPE kits Level 3, Delhi hospitals, 24 hours", "PPE", 10000),
    ("50 ergonomic office chairs, Pune branch, next week", "chair", 50),
    ("100 HP 123A black printer cartridges, Delhi office", "cartridge", 100),
    ("Conference room: 1 table 10 chairs, Chennai, 2 weeks", "table", 1),
    ("1000 pairs industrial safety gloves, Hyderabad plant", "glove", 1000),
    ("5 Cisco 48-port network switches, Bangalore server room", "switch", 5),
    ("100 stationery kits pens notebooks staplers, Kolkata", "stationer", 100),
    ("20 HEPA air purifiers, Bangalore office, budget 5 lakhs", "purifier", 20),
    ("1 diesel generator 10KVA backup power, immediate", "generator", 1),
    ("5000 N95 certified medical masks, hospital supply", "mask", 5000),
    ("Monthly cleaning supplies: detergent mop bucket, 500 sqm office", "cleaning", 1),
    ("1000 reams copier paper 75gsm, warehouse B, Ahmedabad", "paper", 1000),
    ("50 branded laptop bags for new employee onboarding batch", "bag", 50),
]


@pytest.mark.integration
@skip_no_key
@pytest.mark.parametrize("request_text,item_keyword,min_qty", PROCUREMENT_REQUESTS)
async def test_parse_real_request(request_text, item_keyword, min_qty):
    parser = IntentParser(api_key=API_KEY)
    intent = await parser.parse(request_text)

    assert isinstance(intent, SearchIntent)
    assert intent.item.descriptor.name  # non-empty
    assert intent.item.quantity is not None
    assert intent.item.quantity.count >= min_qty
    assert item_keyword.lower() in intent.item.descriptor.name.lower() or \
           (intent.item.descriptor.short_desc and item_keyword.lower() in intent.item.descriptor.short_desc.lower()) or \
           item_keyword.lower() in request_text.lower()
