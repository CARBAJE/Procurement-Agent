"""Tests for the Beckn v2 /select flow.

v2 change: /select goes through the ONIX adapter, not directly to the BPP.
  - Python calls POST /bap/caller/select on ONIX adapter (localhost:8081)
  - ONIX adapter signs and routes to POST /bpp/receiver/select on the BPP
  - Async callback arrives at /bap/receiver/on_select
"""
import pytest
from aioresponses import aioresponses

from src.beckn.client import BecknClient
from src.beckn.models import (
    BecknIntent,
    BudgetConstraints,
    DiscoverOffering,
    SelectOrder,
    SelectProvider,
    SelectedItem,
)

ACK = {"message": {"ack": {"status": "ACK"}}}
SELECT_URL = "http://mock-onix.test/bap/caller/select"
DISCOVER_URL = "http://mock-onix.test/bap/caller/discover"

DISCOVER_RESPONSE = {
    "context": {
        "domain": "nic2004:52110", "action": "discover", "country": "IND",
        "city": "std:080", "core_version": "2.0.0",
        "bap_id": "test-bap", "bap_uri": "http://localhost:8000/beckn",
        "transaction_id": "txn-e2e-001", "message_id": "msg-001",
        "timestamp": "2024-01-01T00:00:00.000Z",
    },
    "transaction_id": "txn-e2e-001",
    "offerings": [
        {
            "bpp_id": "paperdirect-bpp",
            "bpp_uri": "http://paperdirect.test",
            "provider_id": "prov-pd",
            "provider_name": "PaperDirect India",
            "item_id": "item-a4-ream",
            "item_name": "A4 Paper 80gsm",
            "price_value": "189.00",
            "price_currency": "INR",
            "rating": "4.5",
        }
    ],
}


@pytest.fixture
def sample_order():
    return SelectOrder(
        provider=SelectProvider(id="prov-pd"),
        items=[SelectedItem(id="item-a4-ream", quantity=500)],
        fulfillment_hours=72,
    )


# ── Adapter unit tests ────────────────────────────────────────────────────────


def test_build_select_request_action(adapter, sample_order):
    req = adapter.build_select_request(sample_order, "txn-1", "bpp-1", "http://bpp.test")
    assert req.context.action == "select"


def test_build_select_request_carries_bpp_context(adapter, sample_order):
    req = adapter.build_select_request(sample_order, "txn-2", "bpp-007", "http://bpp007.test")
    assert req.context.bpp_id == "bpp-007"
    assert req.context.bpp_uri == "http://bpp007.test"


def test_build_select_request_preserves_transaction_id(adapter, sample_order):
    req = adapter.build_select_request(sample_order, "my-txn", "bpp-1", "http://bpp.test")
    assert req.context.transaction_id == "my-txn"


def test_select_url_points_to_onix_adapter(adapter):
    assert adapter.select_url == "http://mock-onix.test/bap/caller/select"


def test_select_url_not_direct_to_bpp(adapter):
    """select must go through ONIX adapter, never directly to BPP."""
    assert "bpp" not in adapter.select_url.replace("bap", "")
    assert "caller" in adapter.select_url


def test_caller_action_url(adapter):
    assert adapter.caller_action_url("init") == "http://mock-onix.test/bap/caller/init"
    assert adapter.caller_action_url("confirm") == "http://mock-onix.test/bap/caller/confirm"
    assert adapter.caller_action_url("status") == "http://mock-onix.test/bap/caller/status"


# ── Client integration tests ──────────────────────────────────────────────────


async def test_select_posts_to_onix_adapter(adapter, sample_order):
    with aioresponses() as mock:
        mock.post(SELECT_URL, payload=ACK)
        async with BecknClient(adapter) as client:
            ack = await client.select(sample_order, "txn-http", "bpp-1", "http://bpp.test")

    assert ack == ACK


async def test_select_raises_on_onix_error(adapter, sample_order):
    with aioresponses() as mock:
        mock.post(SELECT_URL, status=503)
        async with BecknClient(adapter) as client:
            with pytest.raises(Exception):
                await client.select(sample_order, "txn-err", "bpp-1", "http://bpp.test")


# ── End-to-end: discover → select ─────────────────────────────────────────────


async def test_discover_to_select_flow(adapter, collector):
    """Full v2 flow: synchronous discover → pick best offering → select."""
    intent = BecknIntent(
        item="A4 paper 80gsm",
        descriptions=["A4", "80gsm"],
        quantity=500,
        location_coordinates="12.9716,77.5946",
        delivery_timeline=72,
        budget_constraints=BudgetConstraints(max=200.0),
    )

    with aioresponses() as mock:
        mock.post(DISCOVER_URL, payload=DISCOVER_RESPONSE)
        mock.post(SELECT_URL, payload=ACK)

        async with BecknClient(adapter) as client:
            # 1. Synchronous discover — no waiting, no callbacks
            discover_resp = await client.discover(intent)
            assert len(discover_resp.offerings) >= 1

            # 2. Pick best offering (lowest price)
            best = min(discover_resp.offerings, key=lambda o: float(o.price_value))
            assert best.provider_name == "PaperDirect India"

            # 3. Register for on_select callback, then send /select
            txn_id = discover_resp.transaction_id
            collector.register(txn_id, "on_select")

            order = SelectOrder(
                provider=SelectProvider(id=best.provider_id),
                items=[SelectedItem(id=best.item_id, quantity=500)],
            )
            select_ack = await client.select(
                order,
                transaction_id=txn_id,
                bpp_id=best.bpp_id,
                bpp_uri=best.bpp_uri,
            )
            assert select_ack == ACK

        collector.cleanup(txn_id, "on_select")
