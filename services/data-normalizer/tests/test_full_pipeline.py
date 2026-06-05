"""End-to-end integration test: walk the full pipeline through the HTTP API,
then assert that every FK row exists in the DB.
"""
from __future__ import annotations

import uuid

import pytest


async def test_full_pipeline_request_to_confirmed_order(client, db_pool):
    # 1. Create the request.
    r1 = await (await client.post("/normalize/request", json={
        "raw_input_text": "500 reams A4 paper Bangalore 3 days",
        "channel":        "web",
    })).json()
    request_id = r1["request_id"]

    # 2. Persist parsed + beckn intents.
    r2 = await (await client.post("/normalize/intent", json={
        "request_id":    request_id,
        "intent_class":  "procurement",
        "confidence":    0.95,
        "model_version": "test-v1",
        "beckn_intent":  {
            "item":                 "A4 paper",
            "descriptions":         ["80gsm", "white"],
            "quantity":             500,
            "unit":                 "ream",
            "location_coordinates": "12.97,77.59",
            "delivery_timeline":    72,
            "budget_constraints":   {"min": 100, "max": 200},
        },
    })).json()
    beckn_intent_id = r2["beckn_intent_id"]

    # 3. Persist discovery — 3 offerings.
    r3 = await (await client.post("/normalize/discovery", json={
        "beckn_intent_id": beckn_intent_id,
        "network_id":      "beckn-default",
        "offerings": [
            {"bpp_uri": "http://bpp-1.test", "provider_name": "P1", "item_id": "i-1", "price_value": "150"},
            {"bpp_uri": "http://bpp-2.test", "provider_name": "P2", "item_id": "i-2", "price_value": "175"},
            {"bpp_uri": "http://bpp-3.test", "provider_name": "P3", "item_id": "i-3", "price_value": "160"},
        ],
    })).json()
    query_id = r3["query_id"]
    offering_ids_map = {o["item_id"]: o["offering_id"] for o in r3["offering_ids"]}

    # 4. Score them.
    r4 = await (await client.post("/normalize/scoring", json={
        "query_id": query_id,
        "scores": [
            {"offering_id": offering_ids_map["i-1"], "rank": 1, "composite_score": 0.95, "price_value": "150"},
            {"offering_id": offering_ids_map["i-3"], "rank": 2, "composite_score": 0.85, "price_value": "160"},
            {"offering_id": offering_ids_map["i-2"], "rank": 3, "composite_score": 0.70, "price_value": "175"},
        ],
    })).json()
    score_ids_map = {s["offering_id"]: s["score_id"] for s in r4["score_ids"]}

    # 5. /status="negotiating" (mirrors what the orchestrator does).
    await client.patch("/normalize/status", json={"request_id": request_id, "status": "negotiating"})

    # 6. Place the order on the winning offer.
    r6 = await (await client.post("/normalize/order", json={
        "score_id":          score_ids_map[offering_ids_map["i-1"]],
        "bpp_uri":           "http://bpp-1.test",
        "item_id":           "i-1",
        "quantity":          500,
        "agreed_price":      150.0,
        "beckn_confirm_ref": "e2e-order-001",
        "currency":          "INR",
    })).json()
    po_id = r6["po_id"]

    # 7. Flip the request status to confirmed.
    await client.patch("/normalize/status", json={"request_id": request_id, "status": "confirmed"})

    # 8. Audit the major hitos.
    await client.post("/normalize/audit", json={
        "event_type": "normalize", "agent_action": "request_created",
        "request_id": request_id,
    })
    await client.post("/normalize/audit", json={
        "event_type": "score", "agent_action": "scored 3 offerings",
        "request_id": request_id, "reasoning_payload": {"top": "i-1"},
    })
    await client.post("/normalize/audit", json={
        "event_type": "confirm", "agent_action": "order_confirmed",
        "request_id": request_id, "po_id": po_id,
    })

    # 9. Simulate the BPP reporting shipped → delivered.
    await client.patch("/normalize/po_status", json={"beckn_confirm_ref": "e2e-order-001", "state": "shipped"})
    await client.patch("/normalize/po_status", json={"beckn_confirm_ref": "e2e-order-001", "state": "delivered"})

    # ── Assertions: full FK chain reachable, statuses correct, audit log present
    async with db_pool.acquire() as conn:
        chain = await conn.fetchrow(
            """
            SELECT pr.status      AS pr_status,
                   dq.query_id,
                   po.status      AS po_status,
                   po.beckn_confirm_ref
            FROM procurement_requests pr
            JOIN parsed_intents pi      ON pi.request_id = pr.request_id
            JOIN beckn_intents bi       ON bi.intent_id = pi.intent_id
            JOIN discovery_queries dq   ON dq.beckn_intent_id = bi.beckn_intent_id
            JOIN seller_offerings so    ON so.query_id = dq.query_id
            JOIN scored_offers sc       ON sc.offering_id = so.offering_id
            JOIN negotiation_outcomes no_ ON no_.score_id = sc.score_id
            JOIN approval_decisions ad  ON ad.negotiation_id = no_.negotiation_id
            JOIN purchase_orders po     ON po.approval_id = ad.approval_id
            WHERE pr.request_id = $1
            LIMIT 1
            """,
            uuid.UUID(request_id),
        )
        offering_count = await conn.fetchval(
            "SELECT COUNT(*) FROM seller_offerings WHERE query_id = $1",
            chain["query_id"],
        )
        scored_count = await conn.fetchval(
            """
            SELECT COUNT(*) FROM scored_offers sc
            JOIN seller_offerings so ON so.offering_id = sc.offering_id
            WHERE so.query_id = $1
            """,
            chain["query_id"],
        )
        audit_count = await conn.fetchval(
            "SELECT count(*) FROM audit_trail_events WHERE request_id = $1",
            uuid.UUID(request_id),
        )

    assert chain is not None,                        "FK chain is broken"
    assert chain["pr_status"] == "confirmed"
    assert offering_count == 3
    assert scored_count == 3
    assert chain["po_status"] == "delivered"
    assert chain["beckn_confirm_ref"] == "e2e-order-001"
    assert audit_count == 3
