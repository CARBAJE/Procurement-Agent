"""HTTP shape tests for the Comparison UI endpoints.

These exercise the aiohttp routing + JSON contract of:
    POST /compare
    POST /commit
    GET  /status/{txn_id}/{order_id}

The real ONIX adapter is not reachable inside the test environment, so every
handler falls back to its mock path (`status: "mock"`). That's exactly what
we want for shape verification — the agent-level correctness is covered by
test_compare_commit.py and test_agent.py.

Each test uses a fresh AiohttpClient via aiohttp_client fixture.
"""
from __future__ import annotations

import pytest
from aiohttp.test_utils import TestClient, TestServer

from src import server as server_module
from src.server import create_app


@pytest.fixture
async def client():
    """Fresh aiohttp TestClient wrapped around a fresh app instance.

    We also clear the module-level session store between tests so state from a
    previous test doesn't leak into the next.
    """
    server_module.session_store._backend._store.clear()
    app = create_app()
    async with TestClient(TestServer(app)) as client:
        yield client


def _sample_intent_body():
    return {
        "item": "A4 paper 80gsm",
        "descriptions": ["A4", "80gsm"],
        "quantity": 500,
        "location_coordinates": "12.9716,77.5946",
        "delivery_timeline": 72,
        "unit": "unit",
    }


# ── /compare ─────────────────────────────────────────────────────────────────


async def test_compare_returns_200_with_mock_catalog(client: TestClient):
    resp = await client.post("/compare", json=_sample_intent_body())
    assert resp.status == 200
    body = await resp.json()
    assert body["status"] == "mock"
    assert len(body["offerings"]) == 6


async def test_compare_response_has_full_ui_shape(client: TestClient):
    resp = await client.post("/compare", json=_sample_intent_body())
    body = await resp.json()
    assert {
        "transaction_id", "offerings", "recommended_item_id",
        "scoring", "reasoning_steps", "messages", "status",
    } <= body.keys()
    assert body["recommended_item_id"] == "item-a4-budgetpaper"   # cheapest at ₹165


async def test_compare_scoring_has_price_criterion(client: TestClient):
    resp = await client.post("/compare", json=_sample_intent_body())
    body = await resp.json()
    scoring = body["scoring"]
    assert scoring["recommended_item_id"] == body["recommended_item_id"]
    assert len(scoring["criteria"]) == 1
    assert scoring["criteria"][0]["key"] == "price"
    assert len(scoring["ranking"]) == 6


async def test_compare_rejects_malformed_json(client: TestClient):
    resp = await client.post(
        "/compare",
        data="not-json",
        headers={"Content-Type": "application/json"},
    )
    assert resp.status == 400


async def test_compare_rejects_invalid_intent(client: TestClient):
    resp = await client.post("/compare", json={"item": "A4", "quantity": "not-a-number"})
    assert resp.status == 422


# ── /commit ──────────────────────────────────────────────────────────────────


async def test_commit_404s_unknown_transaction(client: TestClient):
    resp = await client.post("/commit", json={
        "transaction_id": "does-not-exist",
        "chosen_item_id": "anything",
    })
    assert resp.status == 404


async def test_compare_then_commit_roundtrip(client: TestClient):
    """End-to-end: /compare stores session, /commit retrieves and commits."""
    r1 = await client.post("/compare", json=_sample_intent_body())
    body1 = await r1.json()
    txn_id = body1["transaction_id"]
    # User picks the 2nd cheapest — not the agent's recommendation.
    chosen = body1["offerings"][1]["item_id"]

    r2 = await client.post("/commit", json={
        "transaction_id": txn_id,
        "chosen_item_id": chosen,
    })
    assert r2.status == 200
    body2 = await r2.json()
    assert {
        "transaction_id", "order_id", "order_state",
        "payment_terms", "bpp_id", "bpp_uri",
        "reasoning_steps", "messages", "status",
    } <= body2.keys()
    assert body2["transaction_id"] == txn_id
    assert body2["order_id"].startswith("mock-order-")


async def test_commit_rejects_item_not_in_session(client: TestClient):
    r1 = await client.post("/compare", json=_sample_intent_body())
    txn_id = (await r1.json())["transaction_id"]
    r2 = await client.post("/commit", json={
        "transaction_id": txn_id,
        "chosen_item_id": "item-not-in-catalog",
    })
    assert r2.status == 422


# ── /status ──────────────────────────────────────────────────────────────────


async def test_status_400s_without_bpp_and_no_session(client: TestClient):
    resp = await client.get("/status/unknown-txn/order-1")
    assert resp.status == 400


async def test_status_recovers_bpp_from_prior_session(client: TestClient):
    """After /compare (+ /commit), /status can omit bpp params — the server
    recovers them from the stored state."""
    r1 = await client.post("/compare", json=_sample_intent_body())
    body1 = await r1.json()
    txn_id = body1["transaction_id"]
    chosen = body1["recommended_item_id"]
    await client.post("/commit", json={
        "transaction_id": txn_id,
        "chosen_item_id": chosen,
    })

    resp = await client.get(f"/status/{txn_id}/any-order-id")
    assert resp.status == 200
    body = await resp.json()
    assert {"state", "transaction_id", "order_id", "observed_at", "status"} <= body.keys()
