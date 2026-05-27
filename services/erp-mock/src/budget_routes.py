"""Mock budget endpoint hit by services/erp-adapter MockERPAdapter."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from aiohttp import web

import scenarios

logger = logging.getLogger(__name__)


async def budget_check(request: web.Request) -> web.Response:
    cfg = request.app["cfg"]
    sc = scenarios.resolve(cfg.scenario, request.headers.get(scenarios.SCENARIO_HEADER))

    try:
        body = await request.json()
    except Exception:
        return web.json_response({"allowed": False, "reasons": ["BAD_JSON"]}, status=400)

    txn_id = body.get("transaction_id", "")
    requested = body.get("requested_amount", 0)

    if not sc.budget_allowed:
        return web.json_response({
            "allowed": False,
            "available_balance": "0.00",
            "hold_id": None,
            "expires_at": None,
            "reasons": ["INSUFFICIENT_FUNDS"],
        })

    hold_id = f"hold-{uuid4().hex[:12]}"
    expires_at = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
    logger.info("mock budget OK txn=%s amount=%s scenario=%s", txn_id, requested, sc.name)
    return web.json_response({
        "allowed": True,
        "available_balance": f"{sc.available_balance:.2f}",
        "hold_id": hold_id,
        "expires_at": expires_at,
        "reasons": [],
    })


def register(app: web.Application) -> None:
    # Vendor-neutral / mock path
    app.router.add_post("/mock/budget/check", budget_check)
    # Vendor-shaped paths — same semantics, distinct URLs so SAP/Oracle
    # adapters can use vendor-shaped configuration without colliding.
    app.router.add_post("/sap/budget/check", budget_check)
    app.router.add_post("/oracle/budget/check", budget_check)
