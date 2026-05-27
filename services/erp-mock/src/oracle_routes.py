"""Oracle ERP Cloud REST surface mock.

- POST /oauth2/v1/token              (client_credentials)
- POST /fscmRestApi/resources/11.13.18.05/purchaseOrders
"""
from __future__ import annotations

import logging
from uuid import uuid4

from aiohttp import web

import scenarios
import store

logger = logging.getLogger(__name__)

REST_BASE = "/fscmRestApi/resources/11.13.18.05"


async def token(_: web.Request) -> web.Response:
    return web.json_response({
        "access_token": f"mock-oracle-token-{uuid4().hex[:16]}",
        "token_type": "Bearer",
        "expires_in": 3600,
    })


async def po_create(request: web.Request) -> web.Response:
    cfg = request.app["cfg"]
    sc = scenarios.resolve(cfg.scenario, request.headers.get(scenarios.SCENARIO_HEADER))

    body = await request.json()
    txn_id = (body.get("transactionId") or body.get("PurchaseOrderId") or "").strip()
    idem = request.headers.get("Idempotency-Key", "")

    if sc.po_create_failures_before_success > 0:
        seen = store.failure_count(idem or txn_id)
        if seen < sc.po_create_failures_before_success:
            store.increment_failure(idem or txn_id)
            return web.json_response({"errors": [{"detail": "mock transient"}]}, status=500)

    existing = store.get(idem) if idem else None
    if existing:
        return web.json_response(existing)

    order_number = f"PO-OR-{uuid4().int % 1_000_000:06d}"
    record = {
        "OrderNumber": order_number,
        "Status": "Open",
        "links": [{"rel": "self", "href": f"{REST_BASE}/purchaseOrders/{order_number}"}],
    }
    if idem:
        store.put(idem, record)
    logger.info("mock-oracle created PO=%s idempotency=%s scenario=%s", order_number, idem, sc.name)
    return web.json_response(record, status=201)


def register(app: web.Application) -> None:
    app.router.add_post("/oauth2/v1/token", token)
    app.router.add_post(f"{REST_BASE}/purchaseOrders", po_create)
