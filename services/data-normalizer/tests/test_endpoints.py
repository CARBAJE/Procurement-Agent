"""Integration tests for every DataNormalizer HTTP endpoint."""
from __future__ import annotations

import uuid

import pytest
from aiohttp.test_utils import TestClient


def _intent_body(request_id: str) -> dict:
    return {
        "request_id": request_id,
        "intent_class": "procurement",
        "confidence": 0.9,
        "model_version": "test-v1",
        "beckn_intent": {
            "item":                 "A4 paper",
            "descriptions":         ["80gsm"],
            "quantity":             500,
            "unit":                 "ream",
            "location_coordinates": "12.97,77.59",
            "delivery_timeline":    48,
            "budget_constraints":   {"min": 100, "max": 200},
        },
    }


def _offering(item_id: str, bpp_uri: str = "http://bpp-1.test", price="150.00") -> dict:
    return {
        "bpp_uri":           bpp_uri,
        "provider_name":     "ProviderOne",
        "item_id":           item_id,
        "price_value":       price,
        "price_currency":    "INR",
        "fulfillment_hours": 48,
        "rating":            "4.5",
        "specifications":    ["FSC"],
        "available_quantity": 1000,
    }


# ── Happy path per endpoint ──────────────────────────────────────────────────

async def test_normalize_request_creates_row(client: TestClient, db_pool):
    resp = await client.post("/normalize/request", json={
        "raw_input_text": "500 reams A4 paper",
        "channel":        "web",
    })
    assert resp.status == 201
    body = await resp.json()
    rid = body["request_id"]
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT status, raw_input_text, channel FROM procurement_requests WHERE request_id = $1",
            uuid.UUID(rid),
        )
    assert row["status"] == "draft"
    assert row["raw_input_text"] == "500 reams A4 paper"
    assert row["channel"] == "web"


async def test_normalize_intent_creates_both_rows(client: TestClient, db_pool):
    rid = (await (await client.post("/normalize/request", json={"raw_input_text": "x"})).json())["request_id"]
    resp = await client.post("/normalize/intent", json=_intent_body(rid))
    assert resp.status == 201
    body = await resp.json()
    assert body["intent_id"] and body["beckn_intent_id"]
    async with db_pool.acquire() as conn:
        pi = await conn.fetchrow("SELECT request_id FROM parsed_intents WHERE intent_id = $1",
                                 uuid.UUID(body["intent_id"]))
        bi = await conn.fetchrow("SELECT intent_id, item FROM beckn_intents WHERE beckn_intent_id = $1",
                                 uuid.UUID(body["beckn_intent_id"]))
    assert str(pi["request_id"]) == rid
    assert str(bi["intent_id"]) == body["intent_id"]
    assert bi["item"] == "A4 paper"


async def test_normalize_discovery_creates_query_and_offerings(client: TestClient, db_pool):
    rid = (await (await client.post("/normalize/request", json={"raw_input_text": "x"})).json())["request_id"]
    bid = (await (await client.post("/normalize/intent", json=_intent_body(rid))).json())["beckn_intent_id"]

    resp = await client.post("/normalize/discovery", json={
        "beckn_intent_id": bid,
        "network_id":      "beckn-default",
        "offerings":       [_offering("item-A"), _offering("item-B", "http://bpp-2.test", "175.00")],
    })
    assert resp.status == 201
    body = await resp.json()
    assert body["query_id"]
    assert len(body["offering_ids"]) == 2

    async with db_pool.acquire() as conn:
        count = await conn.fetchval(
            "SELECT count(*) FROM seller_offerings WHERE query_id = $1",
            uuid.UUID(body["query_id"]),
        )
        bpp_count = await conn.fetchval("SELECT count(*) FROM bpp")
    assert count == 2
    assert bpp_count == 2   # two distinct bpp_uris


async def test_normalize_scoring_creates_scored_offers(client: TestClient, db_pool):
    rid = (await (await client.post("/normalize/request", json={"raw_input_text": "x"})).json())["request_id"]
    bid = (await (await client.post("/normalize/intent", json=_intent_body(rid))).json())["beckn_intent_id"]
    dr = await (await client.post("/normalize/discovery", json={
        "beckn_intent_id": bid,
        "offerings":       [_offering("item-A"), _offering("item-B", "http://bpp-2.test", "175.00")],
    })).json()

    resp = await client.post("/normalize/scoring", json={
        "query_id": dr["query_id"],
        "scores": [
            {"offering_id": dr["offering_ids"][0]["offering_id"], "rank": 1, "composite_score": 0.95, "price_value": "150"},
            {"offering_id": dr["offering_ids"][1]["offering_id"], "rank": 2, "composite_score": 0.80, "price_value": "175"},
        ],
    })
    assert resp.status == 201
    body = await resp.json()
    assert len(body["score_ids"]) == 2

    async with db_pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT total_score, rank FROM scored_offers ORDER BY rank"
        )
    assert [r["rank"] for r in rows] == [1, 2]
    assert rows[0]["total_score"] == 95.0


async def test_normalize_order_creates_full_fk_chain(client: TestClient, db_pool):
    rid = (await (await client.post("/normalize/request", json={"raw_input_text": "x"})).json())["request_id"]
    bid = (await (await client.post("/normalize/intent", json=_intent_body(rid))).json())["beckn_intent_id"]
    dr = await (await client.post("/normalize/discovery", json={
        "beckn_intent_id": bid,
        "offerings":       [_offering("item-A")],
    })).json()
    sr = await (await client.post("/normalize/scoring", json={
        "query_id": dr["query_id"],
        "scores":   [{"offering_id": dr["offering_ids"][0]["offering_id"], "rank": 1, "composite_score": 0.95, "price_value": "150"}],
    })).json()
    score_id = sr["score_ids"][0]["score_id"]

    resp = await client.post("/normalize/order", json={
        "score_id":          score_id,
        "bpp_uri":           "http://bpp-1.test",
        "item_id":           "item-A",
        "quantity":          500,
        "agreed_price":      150.0,
        "beckn_confirm_ref": "test-order-001",
        "currency":          "INR",
    })
    assert resp.status == 201
    body = await resp.json()
    po_id = body["po_id"]

    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT po.status, po.agreed_price, po.beckn_confirm_ref,
                   ad.status AS approval_status,
                   no_.acceptance_status
            FROM purchase_orders po
            JOIN approval_decisions ad ON ad.approval_id = po.approval_id
            JOIN negotiation_outcomes no_ ON no_.negotiation_id = ad.negotiation_id
            WHERE po.po_id = $1
            """,
            uuid.UUID(po_id),
        )
    assert row["status"] == "pending"
    assert row["agreed_price"] == 150.0
    assert row["beckn_confirm_ref"] == "test-order-001"
    assert row["approval_status"] == "auto_approved"
    assert row["acceptance_status"] == "skipped"


async def test_patch_status_updates_request(client: TestClient, db_pool):
    rid = (await (await client.post("/normalize/request", json={"raw_input_text": "x"})).json())["request_id"]

    resp = await client.patch("/normalize/status", json={"request_id": rid, "status": "cancelled"})
    assert resp.status == 200

    async with db_pool.acquire() as conn:
        status = await conn.fetchval(
            "SELECT status FROM procurement_requests WHERE request_id = $1",
            uuid.UUID(rid),
        )
    assert status == "cancelled"


async def test_patch_po_status_updates_by_confirm_ref(client: TestClient, db_pool):
    # Build a PO end-to-end first.
    rid = (await (await client.post("/normalize/request", json={"raw_input_text": "x"})).json())["request_id"]
    bid = (await (await client.post("/normalize/intent", json=_intent_body(rid))).json())["beckn_intent_id"]
    dr = await (await client.post("/normalize/discovery", json={
        "beckn_intent_id": bid,
        "offerings":       [_offering("item-A")],
    })).json()
    sr = await (await client.post("/normalize/scoring", json={
        "query_id": dr["query_id"],
        "scores":   [{"offering_id": dr["offering_ids"][0]["offering_id"], "rank": 1, "composite_score": 0.9, "price_value": "150"}],
    })).json()
    await client.post("/normalize/order", json={
        "score_id":          sr["score_ids"][0]["score_id"],
        "bpp_uri":           "http://bpp-1.test",
        "item_id":           "item-A",
        "quantity":          1,
        "agreed_price":      150.0,
        "beckn_confirm_ref": "ref-shipped-1",
    })

    resp = await client.patch("/normalize/po_status", json={
        "beckn_confirm_ref": "ref-shipped-1",
        "state":             "shipped",
    })
    assert resp.status == 200

    async with db_pool.acquire() as conn:
        po_status = await conn.fetchval(
            "SELECT status FROM purchase_orders WHERE beckn_confirm_ref = $1",
            "ref-shipped-1",
        )
    assert po_status == "shipped"


async def test_post_audit_appends_event(client: TestClient, db_pool):
    rid = (await (await client.post("/normalize/request", json={"raw_input_text": "x"})).json())["request_id"]
    resp = await client.post("/normalize/audit", json={
        "event_type":   "normalize",
        "agent_action": "request_created",
        "reasoning_payload": {"raw_query": "hello"},
        "request_id":   rid,
    })
    assert resp.status == 201

    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT event_type, agent_action FROM audit_trail_events WHERE request_id = $1",
            uuid.UUID(rid),
        )
    assert row["event_type"] == "normalize"
    assert row["agent_action"] == "request_created"


# ── Validation errors (400) ──────────────────────────────────────────────────

@pytest.mark.parametrize("path,body", [
    ("/normalize/request",   {}),                                      # missing raw_input_text
    ("/normalize/request",   {"raw_input_text": "   "}),               # blank after trim
    ("/normalize/intent",    {"beckn_intent": {}}),                    # missing request_id
    ("/normalize/intent",    {"request_id": str(uuid.uuid4())}),       # missing beckn_intent
    ("/normalize/discovery", {}),                                      # missing beckn_intent_id
    ("/normalize/scoring",   {}),                                      # missing query_id
    ("/normalize/order",     {"bpp_uri": "x"}),                        # missing score_id, item_id, etc.
    ("/normalize/audit",     {"agent_action": "x"}),                   # missing event_type
    ("/normalize/audit",     {"event_type": "garbage", "agent_action": "x"}),  # invalid enum
])
async def test_validation_errors_return_400(client: TestClient, path, body):
    resp = await client.post(path, json=body)
    assert resp.status == 400


async def test_patch_status_missing_fields_returns_400(client: TestClient):
    resp = await client.patch("/normalize/status", json={"request_id": str(uuid.uuid4())})
    assert resp.status == 400


async def test_patch_po_status_invalid_state_returns_400(client: TestClient):
    resp = await client.patch("/normalize/po_status", json={
        "beckn_confirm_ref": "x", "state": "invented",
    })
    assert resp.status == 400


# ── Structured DB errors (409 / 422) ─────────────────────────────────────────

async def test_fk_violation_on_intent_returns_409(client: TestClient):
    """Posting an intent for a non-existent request_id triggers a FK violation
    which the middleware maps to 409 (not the legacy 500)."""
    resp = await client.post("/normalize/intent", json=_intent_body(str(uuid.uuid4())))
    assert resp.status == 409
    body = await resp.json()
    assert body["error"] == "fk_violation"


async def test_unique_violation_on_duplicate_intent_returns_409(client: TestClient):
    rid = (await (await client.post("/normalize/request", json={"raw_input_text": "x"})).json())["request_id"]
    first = await client.post("/normalize/intent", json=_intent_body(rid))
    assert first.status == 201

    second = await client.post("/normalize/intent", json=_intent_body(rid))
    assert second.status == 409
    body = await second.json()
    assert body["error"] == "duplicate"


# ── Silent defaults (logged) — still succeed and apply the safe value ────────

async def test_invalid_channel_silently_defaulted_to_web(client: TestClient, db_pool):
    resp = await client.post("/normalize/request", json={
        "raw_input_text": "x", "channel": "carrier-pigeon",
    })
    assert resp.status == 201
    rid = (await resp.json())["request_id"]
    async with db_pool.acquire() as conn:
        ch = await conn.fetchval(
            "SELECT channel::text FROM procurement_requests WHERE request_id = $1",
            uuid.UUID(rid),
        )
    assert ch == "web"


async def test_confidence_above_one_gets_clamped(client: TestClient, db_pool):
    rid = (await (await client.post("/normalize/request", json={"raw_input_text": "x"})).json())["request_id"]
    body = _intent_body(rid)
    body["confidence"] = 1.7
    resp = await client.post("/normalize/intent", json=body)
    assert resp.status == 201
    iid = (await resp.json())["intent_id"]
    async with db_pool.acquire() as conn:
        score = await conn.fetchval(
            "SELECT confidence_score FROM parsed_intents WHERE intent_id = $1",
            uuid.UUID(iid),
        )
    assert score == 1.0
