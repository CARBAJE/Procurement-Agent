"""Tests for the Beckn v2 /confirm flow (Phase 2).

/confirm commits the order with the payment terms negotiated in /init. The
BPP responds with on_confirm carrying the order_id used by all subsequent
/status queries.
"""
import asyncio

import pytest
from aioresponses import aioresponses

from src.beckn.client import BecknClient
from src.beckn.models import ConfirmResponse, OrderState, PaymentTerms

ACK = {"message": {"ack": {"status": "ACK"}}}
CONFIRM_URL = "http://mock-onix.test/bap/caller/confirm"


@pytest.fixture
def cod_terms():
    return PaymentTerms(
        type="ON_FULFILLMENT",
        collected_by="BPP",
        currency="INR",
        status="NOT-PAID",
    )


# ── Adapter: payload builder ──────────────────────────────────────────────────


def test_build_confirm_wire_payload_action(adapter, cod_terms):
    payload = adapter.build_confirm_wire_payload(
        contract_id="contract-1",
        payment=cod_terms,
        transaction_id="txn-1",
        bpp_id="bpp-1",
        bpp_uri="http://bpp.test",
    )
    assert payload["context"]["action"] == "confirm"
    assert payload["context"]["bppId"] == "bpp-1"
    assert payload["context"]["transactionId"] == "txn-1"


def test_build_confirm_wire_payload_carries_payment(adapter, cod_terms):
    payload = adapter.build_confirm_wire_payload(
        contract_id="contract-1",
        payment=cod_terms,
        transaction_id="txn-1",
        bpp_id="bpp-1",
        bpp_uri="http://bpp.test",
    )
    payment = payload["message"]["contract"]["payment"]
    assert payment["type"] == "ON_FULFILLMENT"
    assert payment["collectedBy"] == "BPP"
    assert payment["status"] == "NOT-PAID"
    assert payment["currency"] == "INR"


def test_build_confirm_marks_contract_as_confirmed(adapter, cod_terms):
    payload = adapter.build_confirm_wire_payload(
        contract_id="contract-1",
        payment=cod_terms,
        transaction_id="txn-1",
        bpp_id="bpp-1",
        bpp_uri="http://bpp.test",
    )
    contract = payload["message"]["contract"]
    assert contract["id"] == "contract-1"
    assert contract["status"]["code"] == "CONFIRMED"


def test_confirm_url_points_to_onix(adapter):
    assert adapter.caller_action_url("confirm") == "http://mock-onix.test/bap/caller/confirm"


# ── Client: confirm() round trip ──────────────────────────────────────────────


async def test_confirm_returns_order_id_from_on_confirm(adapter, collector, cod_terms):
    on_confirm_payload = {
        "context": {
            "domain": "nic2004:52110", "action": "on_confirm", "country": "IND",
            "city": "std:080", "core_version": "2.0.0",
            "bap_id": "test-bap", "bap_uri": "http://localhost:8000/beckn",
            "transaction_id": "txn-confirm-1", "message_id": "msg-confirm-1",
            "timestamp": "2024-01-01T00:00:00.000Z",
        },
        "message": {
            "order": {
                "id": "order-abc-123",
                "contractId": "contract-1",
                "status": {"code": "ACCEPTED"},
                "state": "ACCEPTED",
                "fulfillmentEta": "2026-04-26T10:00:00Z",
            }
        },
    }

    with aioresponses() as mock:
        mock.post(CONFIRM_URL, payload=ACK)
        async with BecknClient(adapter) as client:
            async def _task():
                await asyncio.sleep(0.05)
                await collector.handle_callback("on_confirm", on_confirm_payload)

            task = asyncio.create_task(_task())
            resp = await client.confirm(
                contract_id="contract-1",
                payment=cod_terms,
                transaction_id="txn-confirm-1",
                bpp_id="bpp-1",
                bpp_uri="http://bpp.test",
                collector=collector,
                timeout=1.0,
            )
            await task

    assert isinstance(resp, ConfirmResponse)
    assert resp.order_id == "order-abc-123"
    assert resp.state == OrderState.ACCEPTED
    assert resp.fulfillment_eta == "2026-04-26T10:00:00Z"


async def test_confirm_raises_if_on_confirm_missing(adapter, collector, cod_terms):
    """/confirm with no callback is a protocol failure — must raise."""
    with aioresponses() as mock:
        mock.post(CONFIRM_URL, payload=ACK)
        async with BecknClient(adapter) as client:
            with pytest.raises(RuntimeError, match="timed out waiting for on_confirm"):
                await client.confirm(
                    contract_id="contract-1",
                    payment=cod_terms,
                    transaction_id="txn-nocallback",
                    bpp_id="bpp-1",
                    bpp_uri="http://bpp.test",
                    collector=collector,
                    timeout=0.1,
                )


async def test_confirm_raises_on_onix_error(adapter, collector, cod_terms):
    with aioresponses() as mock:
        mock.post(CONFIRM_URL, status=503)
        async with BecknClient(adapter) as client:
            with pytest.raises(Exception):
                await client.confirm(
                    contract_id="contract-1",
                    payment=cod_terms,
                    transaction_id="txn-err",
                    bpp_id="bpp-1",
                    bpp_uri="http://bpp.test",
                    collector=collector,
                    timeout=0.5,
                )
