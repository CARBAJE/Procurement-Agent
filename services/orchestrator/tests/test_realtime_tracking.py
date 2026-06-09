"""Unit tests for the real-time tracking pieces of workflow.py.

Mocks the Kafka producer and the `_persist*` helpers so tests stay fast and
self-contained. Covers:
  • HMAC verification on the seller webhook (valid + invalid)
  • _beckn_state_to_po_status mapping
  • _publish_status_event safe no-op when producer is None
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import sys
from unittest.mock import AsyncMock, patch

import pytest
from aiohttp.test_utils import AioHTTPTestCase
from aiohttp import web

sys.path.insert(
    0,
    os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")),
)

# Stub env so workflow.py imports cleanly.
os.environ.setdefault("SELLER_WEBHOOK_HMAC_SECRET", "test-secret")
os.environ.setdefault("KAFKA_BOOTSTRAP", "")  # disables real Kafka init


import workflow  # noqa: E402


# ── State mapping ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize("beckn_state, expected", [
    ("CREATED",          "pending"),
    ("ACCEPTED",         "confirmed"),
    ("PACKED",           "confirmed"),
    ("SHIPPED",          "shipped"),
    ("OUT_FOR_DELIVERY", "shipped"),
    ("DELIVERED",        "delivered"),
    ("CANCELLED",        "cancelled"),
    ("unknown",          None),
    ("",                 None),
])
def test_beckn_state_to_po_status(beckn_state, expected):
    assert workflow._beckn_state_to_po_status(beckn_state) == expected


# ── Producer no-op when uninitialised ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_publish_status_event_safe_when_producer_none():
    workflow._kafka_producer = None
    # Should NOT raise.
    await workflow._publish_status_event({"transaction_id": "abc"})


@pytest.mark.asyncio
async def test_publish_status_event_sends_when_producer_set():
    fake = AsyncMock()
    workflow._kafka_producer = fake
    try:
        await workflow._publish_status_event(
            {"transaction_id": "abc", "state": "SHIPPED"}
        )
        fake.send_and_wait.assert_awaited_once()
        args, kwargs = fake.send_and_wait.call_args
        assert args[0] == workflow.KAFKA_TOPIC
        # value is JSON-encoded bytes
        decoded = json.loads(kwargs["value"].decode("utf-8"))
        assert decoded["state"] == "SHIPPED"
    finally:
        workflow._kafka_producer = None


# ── Seller webhook (HMAC) ─────────────────────────────────────────────────────


class SellerWebhookTest(AioHTTPTestCase):
    """Spin up an aiohttp test server with just the seller webhook route."""

    async def get_application(self) -> web.Application:
        app = web.Application()
        app.router.add_post("/webhooks/seller/status",
                            workflow.seller_status_webhook)
        return app

    def _sign(self, body: bytes) -> str:
        return base64.b64encode(
            hmac.new(workflow.SELLER_WEBHOOK_HMAC_SECRET.encode("utf-8"),
                     body, hashlib.sha256).digest()
        ).decode("ascii")

    async def test_invalid_hmac_returns_401(self):
        body = json.dumps({
            "transaction_id": "T1", "order_id": "O1", "beckn_state": "SHIPPED",
        }).encode("utf-8")
        resp = await self.client.post(
            "/webhooks/seller/status",
            data=body,
            headers={"Content-Type": "application/json",
                     "X-Signature": "this-is-not-the-right-signature"},
        )
        assert resp.status == 401

    async def test_missing_hmac_returns_401(self):
        body = json.dumps({
            "transaction_id": "T1", "order_id": "O1", "beckn_state": "SHIPPED",
        }).encode("utf-8")
        resp = await self.client.post(
            "/webhooks/seller/status",
            data=body,
            headers={"Content-Type": "application/json"},
        )
        assert resp.status == 401

    async def test_unsupported_state_returns_400(self):
        body = json.dumps({
            "transaction_id": "T1", "order_id": "O1", "beckn_state": "TELEPORTED",
        }).encode("utf-8")
        resp = await self.client.post(
            "/webhooks/seller/status",
            data=body,
            headers={"Content-Type": "application/json",
                     "X-Signature": self._sign(body)},
        )
        assert resp.status == 400
        text = await resp.json()
        assert "unsupported" in text["error"].lower()

    async def test_missing_fields_returns_400(self):
        body = json.dumps({"transaction_id": "T1"}).encode("utf-8")  # missing order_id
        resp = await self.client.post(
            "/webhooks/seller/status",
            data=body,
            headers={"Content-Type": "application/json",
                     "X-Signature": self._sign(body)},
        )
        assert resp.status == 400

    async def test_valid_hmac_persists_and_publishes(self):
        body = json.dumps({
            "transaction_id": "T1", "order_id": "O1", "beckn_state": "SHIPPED",
        }).encode("utf-8")

        # Patch _persist, _persist_audit, _publish_status_event so we don't
        # need a real DB or Kafka.
        with patch.object(workflow, "_persist", new=AsyncMock()) as p, \
             patch.object(workflow, "_persist_audit", new=AsyncMock()) as a, \
             patch.object(workflow, "_publish_status_event", new=AsyncMock()) as pub:
            resp = await self.client.post(
                "/webhooks/seller/status",
                data=body,
                headers={"Content-Type": "application/json",
                         "X-Signature": self._sign(body)},
            )
            assert resp.status == 200
            data = await resp.json()
            assert data["transaction_id"] == "T1"
            assert data["state"] == "SHIPPED"

            # persist was called with /normalize/po_status
            assert any(
                call.args[1] == "/normalize/po_status"
                for call in p.await_args_list
            )
            # audit was called once
            a.assert_awaited()
            # publish was called once with state SHIPPED
            pub.assert_awaited_once()
            published = pub.await_args.args[0]
            assert published["state"] == "SHIPPED"
            assert published["po_status"] == "shipped"
            assert published["source"] == "seller_webhook"
