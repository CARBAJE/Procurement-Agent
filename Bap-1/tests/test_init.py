"""Tests for the Beckn v2 /init flow (Phase 2).

/init extends the /select contract with billing + fulfillment. The BPP
drafts payment terms and returns them via the on_init callback; /confirm
must use those terms verbatim.
"""
import asyncio

import pytest
from aioresponses import aioresponses

from src.beckn.client import BecknClient
from src.beckn.models import (
    Address,
    BillingInfo,
    FulfillmentInfo,
    InitResponse,
    PaymentTerms,
    SelectedItem,
)

ACK = {"message": {"ack": {"status": "ACK"}}}
INIT_URL = "http://mock-onix.test/bap/caller/init"


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def sample_billing():
    return BillingInfo(
        name="Test Buyer",
        email="test@example.com",
        phone="+91-0000000000",
        address=Address(
            door="Door 1",
            street="Street Test",
            city="Bangalore",
            state="Karnataka",
            country="IND",
            area_code="560100",
        ),
        tax_id="TESTTAXID",
    )


@pytest.fixture
def sample_fulfillment():
    return FulfillmentInfo(
        type="Delivery",
        end_location="12.9716,77.5946",
        end_address=Address(
            city="Bangalore",
            country="IND",
            area_code="560100",
        ),
        contact_name="Test Buyer",
        contact_phone="+91-0000000000",
        delivery_timeline=72,
    )


@pytest.fixture
def sample_items():
    return [SelectedItem(id="item-a4-ream", quantity=500, name="A4 Paper Ream",
                         price_value="189.00", price_currency="INR")]


# ── Adapter: payload builder ──────────────────────────────────────────────────


def test_build_init_wire_payload_action(
    adapter, sample_items, sample_billing, sample_fulfillment,
):
    payload = adapter.build_init_wire_payload(
        contract_id="contract-1",
        items=sample_items,
        billing=sample_billing,
        fulfillment=sample_fulfillment,
        transaction_id="txn-1",
        bpp_id="bpp-1",
        bpp_uri="http://bpp.test",
    )
    assert payload["context"]["action"] == "init"
    assert payload["context"]["version"] == "2.0.0"
    assert payload["context"]["transactionId"] == "txn-1"
    assert payload["context"]["bppId"] == "bpp-1"


def test_build_init_wire_payload_carries_billing_in_participants(
    adapter, sample_items, sample_billing, sample_fulfillment,
):
    """v2.1: buyer billing info lives inside contract.participants[role=buyer]."""
    payload = adapter.build_init_wire_payload(
        contract_id="contract-1",
        items=sample_items,
        billing=sample_billing,
        fulfillment=sample_fulfillment,
        transaction_id="txn-1",
        bpp_id="bpp-1",
        bpp_uri="http://bpp.test",
    )
    participants = payload["message"]["contract"]["participants"]
    assert len(participants) == 1
    buyer = participants[0]
    assert buyer["descriptor"]["code"] == "buyer"
    assert buyer["descriptor"]["name"] == "Test Buyer"
    assert buyer["contact"]["name"] == "Test Buyer"
    assert buyer["contact"]["email"] == "test@example.com"
    assert buyer["contact"]["phone"] == "+91-0000000000"
    assert buyer["address"]["city"] == "Bangalore"
    assert buyer["address"]["areaCode"] == "560100"
    assert buyer["taxId"] == "TESTTAXID"
    # v2.1 Contract schema has additionalProperties: false — no inline billing.
    assert "billing" not in payload["message"]["contract"]


def test_build_init_wire_payload_emits_minimal_performance(
    adapter, sample_items, sample_billing, sample_fulfillment,
):
    """v2.1: a minimal Performance entry referencing the commitment — no
    performanceAttributes (would trigger JSON-LD extended validation that
    requires a resolvable @context URI we don't have)."""
    payload = adapter.build_init_wire_payload(
        contract_id="contract-1",
        items=sample_items,
        billing=sample_billing,
        fulfillment=sample_fulfillment,
        transaction_id="txn-1",
        bpp_id="bpp-1",
        bpp_uri="http://bpp.test",
    )
    performance = payload["message"]["contract"]["performance"]
    assert len(performance) == 1
    perf = performance[0]
    # Only envelope fields — no @context-bearing attributes bag.
    assert set(perf.keys()) == {"id", "status", "commitmentIds"}
    assert perf["status"]["code"] == "PENDING"
    assert perf["commitmentIds"] == ["commitment-001"]
    # v2.1 Contract schema rejects inline fulfillment.
    assert "fulfillment" not in payload["message"]["contract"]


def test_build_init_wire_payload_has_commitments_and_consideration(
    adapter, sample_items, sample_billing, sample_fulfillment,
):
    payload = adapter.build_init_wire_payload(
        contract_id="contract-1",
        items=sample_items,
        billing=sample_billing,
        fulfillment=sample_fulfillment,
        transaction_id="txn-1",
        bpp_id="bpp-1",
        bpp_uri="http://bpp.test",
    )
    contract = payload["message"]["contract"]
    assert contract["id"] == "contract-1"
    assert len(contract["commitments"]) == 1
    assert contract["commitments"][0]["resources"][0]["quantity"]["unitQuantity"] == 500
    # 500 × 189 = 94500
    assert contract["consideration"][0]["price"]["value"] == "94500.0"


def test_init_url_points_to_onix(adapter):
    assert adapter.caller_action_url("init") == "http://mock-onix.test/bap/caller/init"


# ── Client: init() round trip ─────────────────────────────────────────────────


async def test_init_posts_and_awaits_on_init(
    adapter, collector, sample_items, sample_billing, sample_fulfillment,
):
    """Full round-trip: POST /init, simulate on_init, get InitResponse."""
    on_init_payload = {
        "context": {
            "domain": "nic2004:52110", "action": "on_init", "country": "IND",
            "city": "std:080", "core_version": "2.0.0",
            "bap_id": "test-bap", "bap_uri": "http://localhost:8000/beckn",
            "transaction_id": "txn-init-1", "message_id": "msg-init-1",
            "timestamp": "2024-01-01T00:00:00.000Z",
        },
        "message": {
            "contract": {
                "id": "contract-1",
                "payment": {
                    "type": "ON_FULFILLMENT",
                    "collectedBy": "BPP",
                    "status": "NOT-PAID",
                    "currency": "INR",
                },
                "quote": {"price": {"currency": "INR", "value": "94500.0"}},
            }
        },
    }

    with aioresponses() as mock:
        mock.post(INIT_URL, payload=ACK)
        async with BecknClient(adapter) as client:
            # Post the on_init callback immediately after /init is sent.
            async def _task():
                # Give the client time to register the queue.
                await asyncio.sleep(0.05)
                await collector.handle_callback("on_init", on_init_payload)

            task = asyncio.create_task(_task())
            resp = await client.init(
                contract_id="contract-1",
                items=sample_items,
                billing=sample_billing,
                fulfillment=sample_fulfillment,
                transaction_id="txn-init-1",
                bpp_id="bpp-1",
                bpp_uri="http://bpp.test",
                collector=collector,
                timeout=1.0,
            )
            await task

    assert isinstance(resp, InitResponse)
    assert resp.contract_id == "contract-1"
    assert resp.payment_terms is not None
    assert resp.payment_terms.type == "ON_FULFILLMENT"
    assert resp.payment_terms.collected_by == "BPP"
    assert resp.quote_total == "94500.0"


async def test_init_returns_empty_terms_on_timeout(
    adapter, collector, sample_items, sample_billing, sample_fulfillment,
):
    """If on_init never arrives, InitResponse has no payment_terms (not an error)."""
    with aioresponses() as mock:
        mock.post(INIT_URL, payload=ACK)
        async with BecknClient(adapter) as client:
            resp = await client.init(
                contract_id="contract-1",
                items=sample_items,
                billing=sample_billing,
                fulfillment=sample_fulfillment,
                transaction_id="txn-timeout",
                bpp_id="bpp-1",
                bpp_uri="http://bpp.test",
                collector=collector,
                timeout=0.1,
            )

    assert resp.contract_id == "contract-1"
    assert resp.payment_terms is None


async def test_init_raises_on_onix_error(
    adapter, collector, sample_items, sample_billing, sample_fulfillment,
):
    with aioresponses() as mock:
        mock.post(INIT_URL, status=503)
        async with BecknClient(adapter) as client:
            with pytest.raises(Exception):
                await client.init(
                    contract_id="contract-1",
                    items=sample_items,
                    billing=sample_billing,
                    fulfillment=sample_fulfillment,
                    transaction_id="txn-err",
                    bpp_id="bpp-1",
                    bpp_uri="http://bpp.test",
                    collector=collector,
                    timeout=0.5,
                )
