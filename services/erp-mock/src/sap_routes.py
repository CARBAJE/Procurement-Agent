"""SAP S/4HANA OData v4 surface mock.

Implements the slice the adapter needs:
- POST /sap/oauth2/token (client_credentials)
- GET  /sap/opu/odata/sap/API_PURCHASEORDER_PROCESS_SRV/A_PurchaseOrder
       with header X-CSRF-Token: Fetch  →  returns X-CSRF-Token in response
- POST /sap/opu/odata/sap/API_PURCHASEORDER_PROCESS_SRV/A_PurchaseOrder
       creates a synthetic PurchaseOrder number; honors Idempotency-Key.

PO create itself lands in M3.2 — for M3.1 we expose the routes so the adapter
can be probed end-to-end.
"""
from __future__ import annotations

import logging
from uuid import uuid4

from aiohttp import web

import scenarios
import store

logger = logging.getLogger(__name__)

ODATA_BASE = "/sap/opu/odata/sap/API_PURCHASEORDER_PROCESS_SRV"


async def token(_: web.Request) -> web.Response:
    return web.json_response({
        "access_token": f"mock-sap-token-{uuid4().hex[:16]}",
        "token_type": "Bearer",
        "expires_in": 3600,
    })


async def po_collection(request: web.Request) -> web.Response:
    """GET A_PurchaseOrder — returns the CSRF token when requested."""
    if request.headers.get("X-CSRF-Token", "").lower() == "fetch":
        csrf = uuid4().hex
        return web.json_response(
            {"d": {"results": []}},
            headers={"X-CSRF-Token": csrf},
        )
    return web.json_response({"d": {"results": []}})


async def po_create(request: web.Request) -> web.Response:
    """POST A_PurchaseOrder — creates a synthetic PO. M3.2-aware: honors the
    `po_create_fails` scenario by returning 500 the first N attempts."""
    cfg = request.app["cfg"]
    sc = scenarios.resolve(cfg.scenario, request.headers.get(scenarios.SCENARIO_HEADER))

    body = await request.json()
    txn_id = (body.get("transactionId") or body.get("PurchaseOrderId") or "").strip()
    idem = request.headers.get("Idempotency-Key", "")

    if sc.po_create_failures_before_success > 0:
        seen = store.failure_count(idem or txn_id)
        if seen < sc.po_create_failures_before_success:
            store.increment_failure(idem or txn_id)
            return web.json_response({"error": {"code": "TEMPORARY", "message": "mock transient"}}, status=500)

    existing = store.get(idem) if idem else None
    if existing:
        return web.json_response({"d": existing})

    po_number = f"4500{uuid4().int % 10_000_000:07d}"
    record = {"PurchaseOrder": po_number, "PurchaseOrderType": "NB",
              "__metadata": {"type": "API_PURCHASEORDER_PROCESS_SRV.A_PurchaseOrderType"}}
    if idem:
        store.put(idem, record)
    logger.info("mock-sap created PO=%s idempotency=%s scenario=%s", po_number, idem, sc.name)
    return web.json_response({"d": record}, status=201)


def register(app: web.Application) -> None:
    app.router.add_post("/sap/oauth2/token", token)
    app.router.add_get(f"{ODATA_BASE}/A_PurchaseOrder", po_collection)
    app.router.add_post(f"{ODATA_BASE}/A_PurchaseOrder", po_create)
