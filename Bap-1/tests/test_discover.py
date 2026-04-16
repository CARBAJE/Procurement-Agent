"""Tests for the Beckn v2 /discover flow (synchronous discovery).

v2 change: discovery is synchronous.
  - Python calls POST /discover on the ONIX adapter
  - ONIX queries the Catalog Service and returns offerings directly
  - No async callbacks needed for discovery
"""
import re

import pytest
from aioresponses import aioresponses

from src.beckn.client import BecknClient
from src.beckn.models import (
    BecknIntent,
    BudgetConstraints,
    DiscoverOffering,
    DiscoverResponse,
)

DISCOVER_URL = "http://mock-onix.test/bap/caller/discover"

ACK_OFFERINGS = {
    "context": {
        "domain": "nic2004:52110",
        "action": "discover",
        "country": "IND",
        "city": "std:080",
        "core_version": "2.0.0",
        "bap_id": "test-bap",
        "bap_uri": "http://localhost:8000/beckn",
        "transaction_id": "resp-txn-001",
        "message_id": "resp-msg-001",
        "timestamp": "2024-01-01T00:00:00.000Z",
    },
    "transaction_id": "resp-txn-001",
    "offerings": [
        {
            "bpp_id": "seller-1",
            "bpp_uri": "http://seller1.test",
            "provider_id": "prov-1",
            "provider_name": "OfficeWorld",
            "item_id": "item-a4",
            "item_name": "A4 Paper 80gsm",
            "price_value": "195.00",
            "price_currency": "INR",
            "rating": "4.8",
        },
        {
            "bpp_id": "seller-2",
            "bpp_uri": "http://seller2.test",
            "provider_id": "prov-2",
            "provider_name": "PaperDirect",
            "item_id": "item-a4-ream",
            "item_name": "A4 Paper Ream",
            "price_value": "189.00",
            "price_currency": "INR",
            "rating": "4.5",
        },
        {
            "bpp_id": "seller-3",
            "bpp_uri": "http://seller3.test",
            "provider_id": "prov-3",
            "provider_name": "StationeryHub",
            "item_id": "item-a4-premium",
            "item_name": "A4 Paper Premium",
            "price_value": "201.00",
            "price_currency": "INR",
            "rating": "4.9",
        },
    ],
}


@pytest.fixture
def paper_intent():
    return BecknIntent(
        item="A4 paper 80gsm",
        descriptions=["A4", "80gsm"],
        quantity=500,
        location_coordinates="12.9716,77.5946",
        delivery_timeline=72,  # 3 days in hours
        budget_constraints=BudgetConstraints(max=200.0),
    )


# ── BecknIntent validators ────────────────────────────────────────────────────


def test_intent_quantity_must_be_positive():
    with pytest.raises(Exception):
        BecknIntent(item="paper", quantity=0)


def test_intent_negative_quantity_rejected():
    with pytest.raises(Exception):
        BecknIntent(item="paper", quantity=-10)


def test_intent_timeline_must_be_positive():
    with pytest.raises(Exception):
        BecknIntent(item="paper", quantity=100, delivery_timeline=0)


def test_intent_timeline_hours_not_iso():
    intent = BecknIntent(item="paper", quantity=100, delivery_timeline=72)
    assert isinstance(intent.delivery_timeline, int)
    assert intent.delivery_timeline == 72  # hours, not "P3D"


def test_intent_budget_range():
    intent = BecknIntent(
        item="paper",
        quantity=100,
        budget_constraints=BudgetConstraints(max=200.0),
    )
    assert intent.budget_constraints.max == 200.0
    assert intent.budget_constraints.min == 0.0  # open lower bound


def test_intent_descriptions_atomic_list():
    intent = BecknIntent(
        item="A4 paper",
        quantity=500,
        descriptions=["A4", "80gsm"],
    )
    assert len(intent.descriptions) == 2
    assert "A4" in intent.descriptions


# ── Adapter unit tests ────────────────────────────────────────────────────────


def test_build_discover_request_action(adapter, paper_intent):
    req = adapter.build_discover_request(paper_intent)
    assert req.context.action == "discover"


def test_build_discover_request_version(adapter, paper_intent):
    req = adapter.build_discover_request(paper_intent)
    assert req.context.core_version == "2.0.0"


def test_build_discover_request_bap_identity(adapter, paper_intent):
    req = adapter.build_discover_request(paper_intent)
    assert req.context.bap_id == "test-bap"


def test_build_discover_request_preserves_intent(adapter, paper_intent):
    req = adapter.build_discover_request(paper_intent)
    assert req.message.item == "A4 paper 80gsm"
    assert req.message.quantity == 500
    assert req.message.delivery_timeline == 72


def test_discover_url_points_to_onix(adapter):
    assert adapter.discover_url == "http://mock-onix.test/bap/caller/discover"


def test_discover_url_not_gateway(adapter):
    assert "gateway" not in adapter.discover_url
    assert "onix" in adapter.discover_url or "8081" in adapter.discover_url or "mock-onix" in adapter.discover_url


# ── Client integration tests ──────────────────────────────────────────────────


async def test_discover_returns_offerings(adapter, paper_intent):
    with aioresponses() as mock:
        mock.post(DISCOVER_URL, payload=ACK_OFFERINGS)
        async with BecknClient(adapter) as client:
            response = await client.discover(paper_intent)

    assert isinstance(response, DiscoverResponse)
    assert len(response.offerings) == 3


async def test_discover_returns_3_plus_sellers(adapter, paper_intent):
    with aioresponses() as mock:
        mock.post(DISCOVER_URL, payload=ACK_OFFERINGS)
        async with BecknClient(adapter) as client:
            response = await client.discover(paper_intent)

    assert len(response.offerings) >= 3


async def test_discover_offerings_have_prices(adapter, paper_intent):
    with aioresponses() as mock:
        mock.post(DISCOVER_URL, payload=ACK_OFFERINGS)
        async with BecknClient(adapter) as client:
            response = await client.discover(paper_intent)

    for offering in response.offerings:
        assert isinstance(offering, DiscoverOffering)
        assert offering.price_value
        assert offering.bpp_id


async def test_discover_with_explicit_transaction_id(adapter, paper_intent):
    with aioresponses() as mock:
        mock.post(DISCOVER_URL, payload=ACK_OFFERINGS)
        async with BecknClient(adapter) as client:
            response = await client.discover(paper_intent, transaction_id="my-txn")

    assert response.transaction_id == "resp-txn-001"


async def test_discover_raises_on_onix_error(adapter, paper_intent):
    with aioresponses() as mock:
        mock.post(DISCOVER_URL, status=503)
        async with BecknClient(adapter) as client:
            with pytest.raises(Exception):
                await client.discover(paper_intent)
