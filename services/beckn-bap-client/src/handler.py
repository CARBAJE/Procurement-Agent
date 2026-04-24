"""Lambda 2 — Beckn BAP Client microservice.

Single aiohttp server on port 8002 with three route groups:

Orchestrator-facing:
  POST /discover   BecknIntent JSON → { transaction_id, offerings[] }
  POST /select     selection body  → { ack: "ACK" | "NACK" }
  POST /init       init body       → { payment_terms, contract_id, ack }
  POST /confirm    confirm body    → { order_id, order_state, ack }
  POST /status     status body     → { state, fulfillment_eta, tracking_url }

ONIX callback receiver:
  POST /bap/receiver/{action}   on_discover, on_select, on_init, on_confirm, on_status
  POST /{action}                real Beckn network direct callbacks
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import uuid

# Ensure /app is in path so 'shared' package is importable
sys.path.insert(0, "/app")

import aiohttp
from aiohttp import web

from .beckn.adapter import BecknProtocolAdapter
from .beckn.callbacks import CallbackCollector
from .beckn.client import BecknClient
from .beckn.models import BecknIntent, SelectOrder, SelectProvider, SelectedItem
from .config import BecknConfig

logger = logging.getLogger(__name__)

# Module-level singletons shared between routes
config = BecknConfig()
collector = CallbackCollector(default_timeout=config.callback_timeout)

SUPPORTED_CALLBACKS = {"on_discover", "on_select", "on_init", "on_confirm", "on_status"}

# ── Local catalog — returned for every /bpp/discover request ──────────────────
# Mirrors the data in Bap-1/src/server.py so the two stay in sync.

_LOCAL_CATALOG = [
    {
        "id": "item-a4-80gsm",
        "descriptor": {"name": "A4 Paper 80gsm (500 sheets)", "shortDesc": "A4 paper 80gsm ream 500 sheets"},
        "provider": {"id": "PROV-OFFICEWORLD-01", "descriptor": {"name": "OfficeWorld Supplies"}},
        "price": {"value": "195.00", "currency": "INR"},
        "rating": {"ratingValue": 4.8},
    },
    {
        "id": "item-a4-ream",
        "descriptor": {"name": "A4 Paper 80gsm Ream", "shortDesc": "A4 80gsm ream 500 sheets"},
        "provider": {"id": "PROV-PAPERDIRECT-01", "descriptor": {"name": "PaperDirect India"}},
        "price": {"value": "189.00", "currency": "INR"},
        "rating": {"ratingValue": 4.5},
    },
    {
        "id": "item-a4-premium",
        "descriptor": {"name": "A4 Paper Premium 80gsm", "shortDesc": "Premium A4 paper 80gsm high brightness"},
        "provider": {"id": "PROV-STATHUB-01", "descriptor": {"name": "Stationery Hub"}},
        "price": {"value": "201.00", "currency": "INR"},
        "rating": {"ratingValue": 4.9},
    },
]


# ── Health ────────────────────────────────────────────────────────────────────


async def health(request: web.Request) -> web.Response:
    return web.json_response({
        "status": "ok",
        "service": "beckn-bap-client",
        "bap_id": config.bap_id,
    })


# ── Orchestrator-facing routes ────────────────────────────────────────────────


async def discover(request: web.Request) -> web.Response:
    """POST /discover — run Beckn discovery and return offerings.

    Body: BecknIntent JSON fields (item, quantity, location_coordinates, …)
    Response: { "transaction_id": str, "offerings": [DiscoverOffering…] }
    """
    try:
        body = await request.json()
    except json.JSONDecodeError:
        raise web.HTTPBadRequest(reason="Invalid JSON")

    try:
        intent = BecknIntent(**body)
    except Exception as exc:
        raise web.HTTPUnprocessableEntity(reason=f"Invalid BecknIntent: {exc}")

    adapter = BecknProtocolAdapter(config)

    try:
        async with BecknClient(adapter) as client:
            resp = await client.discover_async(
                intent,
                collector,
                timeout=config.callback_timeout,
            )

        offerings = [o.model_dump() for o in resp.offerings]
        return web.json_response({
            "transaction_id": resp.transaction_id,
            "offerings": offerings,
        })

    except Exception as exc:
        logger.error("Discovery failed: %s", exc)
        raise web.HTTPInternalServerError(reason=f"Discovery failed: {exc}")


async def select(request: web.Request) -> web.Response:
    """POST /select — send /select to ONIX for the chosen offering.

    Body:
      { "transaction_id", "bpp_id", "bpp_uri", "item_id", "item_name",
        "provider_id", "price_value", "price_currency", "quantity" }
    Response: { "ack": "ACK" | "NACK" }
    """
    try:
        body = await request.json()
    except json.JSONDecodeError:
        raise web.HTTPBadRequest(reason="Invalid JSON")

    transaction_id = body.get("transaction_id")
    bpp_id = body.get("bpp_id")
    bpp_uri = body.get("bpp_uri")

    if not all([transaction_id, bpp_id, bpp_uri]):
        raise web.HTTPBadRequest(reason="transaction_id, bpp_id, bpp_uri are required")

    order = SelectOrder(
        provider=SelectProvider(id=body.get("provider_id", "")),
        items=[
            SelectedItem(
                id=body.get("item_id", ""),
                quantity=int(body.get("quantity", 1)),
                name=body.get("item_name"),
                price_value=body.get("price_value"),
                price_currency=body.get("price_currency", "INR"),
            )
        ],
    )

    adapter = BecknProtocolAdapter(config)

    try:
        async with BecknClient(adapter) as client:
            ack = await client.select(order, transaction_id, bpp_id, bpp_uri)

        ack_status = ack.get("message", {}).get("ack", {}).get("status", "UNKNOWN")
        return web.json_response({"ack": ack_status})

    except Exception as exc:
        logger.error("/select failed: %s", exc)
        raise web.HTTPInternalServerError(reason=f"/select failed: {exc}")


# ── ONIX callback receiver ────────────────────────────────────────────────────


async def bap_receiver(request: web.Request) -> web.Response:
    """POST /bap/receiver/{action} — receive async callbacks from ONIX adapter."""
    action = request.match_info["action"]
    if action not in SUPPORTED_CALLBACKS:
        raise web.HTTPNotFound(reason=f"Unknown callback action: {action}")

    try:
        payload = await request.json()
    except json.JSONDecodeError:
        raise web.HTTPBadRequest(reason="Invalid JSON")

    ctx = payload.get("context", {})
    txn_id = ctx.get("transactionId") or ctx.get("transaction_id", "unknown")
    logger.debug("%s received | txn=%s", action, txn_id)

    ack = await collector.handle_callback(action, payload)
    return web.json_response(ack)


# ── Local BPP catalog endpoint (for ONIX discover routing) ───────────────────


async def bpp_discover(request: web.Request) -> web.Response:
    """POST /bpp/discover — local BPP catalog handler for ONIX discover routing.

    onix-bap routes discover here (via generic-routing-BAPCaller.yaml) instead
    of an external Discover Service. Immediately ACKs and fires an async
    on_discover callback back to our own /bap/receiver/on_discover route.

        orchestrator → beckn-bap-client /discover
          → BecknClient.discover_async() → onix-bap
            → POST /bpp/discover (here)
              → async POST /bap/receiver/on_discover (here, via asyncio task)
                → CallbackCollector → discover_async() wakes up
    """
    try:
        payload = await request.json()
    except json.JSONDecodeError:
        raise web.HTTPBadRequest(reason="Invalid JSON")

    ctx = payload.get("context", {})
    txn_id = ctx.get("transactionId") or ctx.get("transaction_id", "unknown")
    logger.debug("bpp/discover received | txn=%s", txn_id)

    asyncio.create_task(_send_local_on_discover(ctx))

    return web.json_response({"message": {"ack": {"status": "ACK"}}})


async def _send_local_on_discover(context: dict) -> None:
    """Build on_discover payload from the local catalog and POST to our own callback route.

    Posts to localhost:8002 (self) so the CallbackCollector receives the response
    and wakes up whatever discover_async() is waiting on this transaction_id.
    """
    await asyncio.sleep(0.1)

    on_discover_payload = {
        "context": {
            **context,
            "action": "on_discover",
            "bppId": "bpp.example.com",
            "bppUri": "http://onix-bpp:8082/bpp/receiver",
        },
        "message": {
            "catalogs": [
                {
                    "bppId": "bpp.example.com",
                    "bppUri": "http://onix-bpp:8082/bpp/receiver",
                    "resources": _LOCAL_CATALOG,
                }
            ]
        },
    }

    port = int(os.getenv("PORT", "8002"))
    callback_url = f"http://localhost:{port}/bap/receiver/on_discover"

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                callback_url,
                json=on_discover_payload,
                headers={"Content-Type": "application/json"},
            ) as resp:
                logger.debug("on_discover sent locally | HTTP=%d", resp.status)
    except Exception as exc:
        logger.error("Failed to send local on_discover: %s", exc)


# ── Transactional routes: init / confirm / status ─────────────────────────────


async def beckn_init(request: web.Request) -> web.Response:
    """POST /init — send Beckn /init and await on_init callback.

    Body: {transaction_id, contract_id, bpp_id, bpp_uri,
           items: [{id, quantity, name, price_value, price_currency}]}
    Response: {payment_terms, contract_id, ack}
    """
    try:
        body = await request.json()
    except json.JSONDecodeError:
        raise web.HTTPBadRequest(reason="Invalid JSON")

    transaction_id = body.get("transaction_id")
    contract_id = body.get("contract_id")
    bpp_id = body.get("bpp_id")
    bpp_uri = body.get("bpp_uri")

    if not all([transaction_id, contract_id, bpp_id, bpp_uri]):
        raise web.HTTPBadRequest(reason="transaction_id, contract_id, bpp_id, bpp_uri are required")

    try:
        items = [SelectedItem(**i) for i in body.get("items", [])]
    except Exception as exc:
        raise web.HTTPUnprocessableEntity(reason=f"Invalid items: {exc}")

    try:
        adapter = BecknProtocolAdapter(config)
        async with BecknClient(adapter) as client:
            result = await client.init(
                contract_id=contract_id,
                items=items,
                transaction_id=transaction_id,
                bpp_id=bpp_id,
                bpp_uri=bpp_uri,
                collector=collector,
                timeout=config.callback_timeout,
            )
        return web.json_response({
            "payment_terms": result["payment_terms"],
            "contract_id": contract_id,
            "ack": "ACK",
        })
    except Exception as exc:
        logger.error("/init failed: %s", exc)
        raise web.HTTPInternalServerError(reason=f"/init failed: {exc}")


async def beckn_confirm(request: web.Request) -> web.Response:
    """POST /confirm — send Beckn /confirm and await on_confirm callback.

    Body: {transaction_id, contract_id, bpp_id, bpp_uri, items, payment_terms?}
    Response: {order_id, order_state, ack}

    On callback timeout returns 200 with ack:"NACK" and order_id:null so the
    orchestrator can build a mock response rather than receiving a 5xx.
    """
    try:
        body = await request.json()
    except json.JSONDecodeError:
        raise web.HTTPBadRequest(reason="Invalid JSON")

    transaction_id = body.get("transaction_id")
    contract_id = body.get("contract_id")
    bpp_id = body.get("bpp_id")
    bpp_uri = body.get("bpp_uri")

    if not all([transaction_id, contract_id, bpp_id, bpp_uri]):
        raise web.HTTPBadRequest(reason="transaction_id, contract_id, bpp_id, bpp_uri are required")

    payment_terms = body.get("payment_terms") or {
        "type": "ON_FULFILLMENT",
        "collected_by": "BPP",
        "currency": "INR",
        "status": "NOT-PAID",
    }

    try:
        items = [SelectedItem(**i) for i in body.get("items", [])]
    except Exception as exc:
        raise web.HTTPUnprocessableEntity(reason=f"Invalid items: {exc}")

    try:
        adapter = BecknProtocolAdapter(config)
        async with BecknClient(adapter) as client:
            result = await client.confirm(
                contract_id=contract_id,
                items=items,
                payment=payment_terms,
                transaction_id=transaction_id,
                bpp_id=bpp_id,
                bpp_uri=bpp_uri,
                collector=collector,
                timeout=config.callback_timeout,
            )
        return web.json_response({
            "order_id": result["order_id"],
            "order_state": result["order_state"],
            "ack": "ACK",
        })
    except RuntimeError:
        # Callback timed out — return NACK so orchestrator falls back to mock
        return web.json_response({
            "order_id": None,
            "order_state": "CREATED",
            "ack": "NACK",
        })
    except Exception as exc:
        logger.error("/confirm failed: %s", exc)
        raise web.HTTPInternalServerError(reason=f"/confirm failed: {exc}")


async def beckn_status(request: web.Request) -> web.Response:
    """POST /status — send Beckn /status and await on_status callback.

    Body: {transaction_id, order_id, bpp_id, bpp_uri, items}
    Response: {state, fulfillment_eta, tracking_url}

    Never returns 5xx — status polling must be resilient to failures.
    """
    try:
        body = await request.json()
    except json.JSONDecodeError:
        raise web.HTTPBadRequest(reason="Invalid JSON")

    transaction_id = body.get("transaction_id")
    order_id = body.get("order_id")
    bpp_id = body.get("bpp_id")
    bpp_uri = body.get("bpp_uri")

    if not all([transaction_id, order_id, bpp_id, bpp_uri]):
        raise web.HTTPBadRequest(reason="transaction_id, order_id, bpp_id, bpp_uri are required")

    try:
        items = [SelectedItem(**i) for i in body.get("items", [])]
    except Exception:
        items = []

    try:
        adapter = BecknProtocolAdapter(config)
        async with BecknClient(adapter) as client:
            result = await client.status(
                order_id=order_id,
                items=items,
                transaction_id=transaction_id,
                bpp_id=bpp_id,
                bpp_uri=bpp_uri,
                collector=collector,
                timeout=config.callback_timeout,
            )
        return web.json_response(result)
    except Exception as exc:
        logger.error("/status failed: %s", exc)
        return web.json_response({
            "state": "CREATED",
            "fulfillment_eta": None,
            "tracking_url": None,
        })


# ── App factory ───────────────────────────────────────────────────────────────


def create_app() -> web.Application:
    app = web.Application()
    app.router.add_get("/health",                health)
    app.router.add_post("/discover",             discover)
    app.router.add_post("/select",               select)
    # Transactional routes must be registered before the /{action} wildcard
    app.router.add_post("/init",                 beckn_init)
    app.router.add_post("/confirm",              beckn_confirm)
    app.router.add_post("/status",               beckn_status)
    app.router.add_post("/bap/receiver/{action}", bap_receiver)
    app.router.add_post("/bpp/discover",         bpp_discover)   # ONIX discover routing target
    app.router.add_post("/{action}",             bap_receiver)   # real Beckn network callbacks
    return app


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    port = int(os.getenv("PORT", "8002"))
    web.run_app(create_app(), host="0.0.0.0", port=port)
