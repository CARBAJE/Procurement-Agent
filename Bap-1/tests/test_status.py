"""Tests for the Beckn v2 /status flow (Phase 2).

/status queries the current fulfillment state of a confirmed order. Typically
polled from the UI at a 30-second SLA (KnowledgeBase real_time_tracking.md).
"""
import asyncio

import pytest
from aioresponses import aioresponses

from src.beckn.client import BecknClient
from src.beckn.models import OrderState, SelectedItem, StatusResponse

ACK = {"message": {"ack": {"status": "ACK"}}}
STATUS_URL = "http://mock-onix.test/bap/caller/status"


@pytest.fixture
def sample_items():
    return [SelectedItem(id="item-a4", quantity=500, name="A4 Paper",
                         price_value="189.00", price_currency="INR")]


# ── Adapter: payload builder ──────────────────────────────────────────────────


def test_build_status_wire_payload_action(adapter, sample_items):
    payload = adapter.build_status_wire_payload(
        order_id="order-123",
        items=sample_items,
        transaction_id="txn-1",
        bpp_id="bpp-1",
        bpp_uri="http://bpp.test",
    )
    assert payload["context"]["action"] == "status"
    assert payload["context"]["transactionId"] == "txn-1"
    # v2.1 wraps the order id inside contract.id (not a bare orderId field).
    assert payload["message"]["contract"]["id"] == "order-123"
    # /status inherits Contract.required=[commitments], so commitments must
    # be replayed on every poll.
    assert len(payload["message"]["contract"]["commitments"]) == 1


def test_status_url_points_to_onix(adapter):
    assert adapter.caller_action_url("status") == "http://mock-onix.test/bap/caller/status"


# ── Client: status() round trip ───────────────────────────────────────────────


def _on_status_payload(order_id: str, state: str, eta: str | None = None) -> dict:
    fulfillment = {"trackingUrl": f"http://track/{order_id}"}
    if eta:
        fulfillment["eta"] = eta
    return {
        "context": {
            "domain": "nic2004:52110", "action": "on_status", "country": "IND",
            "city": "std:080", "core_version": "2.0.0",
            "bap_id": "test-bap", "bap_uri": "http://localhost:8000/beckn",
            "transaction_id": "txn-status-1", "message_id": "msg-status-1",
            "timestamp": "2024-01-01T00:00:00.000Z",
        },
        "message": {
            "order": {
                "id": order_id,
                "state": state,
                "status": {"code": state},
                "fulfillment": fulfillment,
            }
        },
    }


@pytest.mark.parametrize(
    "raw_state,expected",
    [
        ("ACCEPTED", OrderState.ACCEPTED),
        ("PACKED", OrderState.PACKED),
        ("SHIPPED", OrderState.SHIPPED),
        ("OUT_FOR_DELIVERY", OrderState.OUT_FOR_DELIVERY),
        ("DELIVERED", OrderState.DELIVERED),
        ("CANCELLED", OrderState.CANCELLED),
    ],
)
async def test_status_parses_every_lifecycle_state(
    adapter, collector, sample_items, raw_state, expected,
):
    payload = _on_status_payload("order-abc", raw_state, eta="2026-04-26T10:00:00Z")

    with aioresponses() as mock:
        mock.post(STATUS_URL, payload=ACK)
        async with BecknClient(adapter) as client:
            async def _task():
                await asyncio.sleep(0.05)
                await collector.handle_callback("on_status", payload)

            task = asyncio.create_task(_task())
            resp = await client.status(
                order_id="order-abc",
                items=sample_items,
                transaction_id="txn-status-1",
                bpp_id="bpp-1",
                bpp_uri="http://bpp.test",
                collector=collector,
                timeout=1.0,
            )
            await task

    assert isinstance(resp, StatusResponse)
    assert resp.order_id == "order-abc"
    assert resp.state == expected
    assert resp.fulfillment_eta == "2026-04-26T10:00:00Z"
    assert resp.tracking_url == "http://track/order-abc"


async def test_status_unknown_state_defaults_to_created(adapter, collector, sample_items):
    """Unknown state strings should degrade safely, not crash the polling loop."""
    payload = _on_status_payload("order-abc", "WEIRD_VALUE")

    with aioresponses() as mock:
        mock.post(STATUS_URL, payload=ACK)
        async with BecknClient(adapter) as client:
            async def _task():
                await asyncio.sleep(0.05)
                await collector.handle_callback("on_status", payload)

            task = asyncio.create_task(_task())
            resp = await client.status(
                order_id="order-abc",
                items=sample_items,
                transaction_id="txn-status-1",
                bpp_id="bpp-1",
                bpp_uri="http://bpp.test",
                collector=collector,
                timeout=1.0,
            )
            await task

    assert resp.state == OrderState.CREATED


async def test_status_no_callback_returns_created(adapter, collector, sample_items):
    """A silent BPP should not raise — polling loops must keep going."""
    with aioresponses() as mock:
        mock.post(STATUS_URL, payload=ACK)
        async with BecknClient(adapter) as client:
            resp = await client.status(
                order_id="order-abc",
                items=sample_items,
                transaction_id="txn-silent",
                bpp_id="bpp-1",
                bpp_uri="http://bpp.test",
                collector=collector,
                timeout=0.1,
            )

    assert resp.state == OrderState.CREATED
    assert resp.order_id == "order-abc"


async def test_status_raises_on_onix_error(adapter, collector, sample_items):
    with aioresponses() as mock:
        mock.post(STATUS_URL, status=503)
        async with BecknClient(adapter) as client:
            with pytest.raises(Exception):
                await client.status(
                    order_id="order-abc",
                    items=sample_items,
                    transaction_id="txn-err",
                    bpp_id="bpp-1",
                    bpp_uri="http://bpp.test",
                    collector=collector,
                    timeout=0.5,
                )
