"""BAP callback server for Beckn v2 async transaction callbacks.

In Beckn v2, discovery is synchronous — no /on_search endpoint needed.
This server handles async callbacks from the ONIX adapter for transactional
flows: on_select, on_init, on_confirm, on_status.

Also exposes a local BPP discover endpoint (POST /bpp/discover) so that
onix-bap can route discover requests here instead of the external Discover
Service. This avoids the need for a public URL / ngrok for local development.

Callbacks arrive at:  POST /bap/receiver/{action}
  e.g. /bap/receiver/on_select, /bap/receiver/on_confirm

Run:
    python -m src.server
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import uuid

# Allow `shared/` (one level up from Bap-1/) to be importable — same as run.py
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))

import aiohttp
from aiohttp import web

from src.beckn.adapter import BecknProtocolAdapter
from src.beckn.callbacks import CallbackCollector
from src.beckn.client import BecknClient
from src.beckn.models import BecknIntent
from src.config import BecknConfig

logger = logging.getLogger(__name__)

config = BecknConfig()
collector = CallbackCollector(default_timeout=config.callback_timeout)

SUPPORTED_CALLBACKS = {"on_discover", "on_select", "on_init", "on_confirm", "on_status"}

# ── Local catalog — returned for every discover request ───────────────────────
# Mirrors the data in publish_catalog.py so the two stay in sync.

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


async def health(request: web.Request) -> web.Response:
    return web.json_response({
        "status": "ok",
        "bap_id": config.bap_id,
        "version": config.core_version,
    })


async def bap_receiver(request: web.Request) -> web.Response:
    """Handle async callbacks from ONIX adapter or directly from the network.

    Routes: POST /bap/receiver/{action}
            POST /{action}            (real Beckn network posts directly)
    """
    action = request.match_info["action"]
    if action not in SUPPORTED_CALLBACKS:
        raise web.HTTPNotFound(reason=f"Unknown callback action: {action}")

    try:
        payload = await request.json()
    except json.JSONDecodeError:
        raise web.HTTPBadRequest(reason="Invalid JSON")

    ctx = payload.get("context", {})
    txn_id = ctx.get("transactionId") or ctx.get("transaction_id", "unknown")
    bpp_id = ctx.get("bppId") or ctx.get("bpp_id", "unknown")
    logger.debug("%s received | txn=%s bpp=%s", action, txn_id, bpp_id)
    logger.debug("%s payload: %s", action, json.dumps(payload))

    ack = await collector.handle_callback(action, payload)
    return web.json_response(ack)


async def bpp_discover(request: web.Request) -> web.Response:
    """Local BPP catalog handler — receives discover from onix-bap and sends
    on_discover directly back to our own callback server.

    onix-bap routes discover here (via generic-routing-BAPCaller.yaml) instead
    of the external Discover Service, so the full flow stays local:

        run.py → onix-bap → POST /bpp/discover (here)
                             → async POST /bap/receiver/on_discover (here, via asyncio task)
                             → CallbackCollector → run.py wakes up
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
    """Build on_discover payload from local catalog and POST to our own callback route."""
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

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                "http://localhost:8000/bap/receiver/on_discover",
                json=on_discover_payload,
                headers={"Content-Type": "application/json"},
            ) as resp:
                logger.debug("on_discover sent locally | HTTP=%d", resp.status)
    except Exception as exc:
        logger.error("Failed to send local on_discover: %s", exc)


def _local_catalog_as_offerings() -> list[dict]:
    """Convert _LOCAL_CATALOG raw dicts to DiscoverOffering-compatible format."""
    result = []
    for item in _LOCAL_CATALOG:
        result.append({
            "bpp_id":        "bpp.local",
            "bpp_uri":       "http://localhost:8000/bpp",
            "provider_id":   item["provider"]["id"],
            "provider_name": item["provider"]["descriptor"]["name"],
            "item_id":       item["id"],
            "item_name":     item["descriptor"]["name"],
            "price_value":   item["price"]["value"],
            "price_currency": item["price"].get("currency", "INR"),
            "rating":        str(item["rating"]["ratingValue"]) if item.get("rating") else None,
            "specifications": [],
            "fulfillment_hours": None,
        })
    return result


async def discover(request: web.Request) -> web.Response:
    """Frontend-facing discover endpoint.

    Accepts an already-parsed BecknIntent JSON body (sent by the Next.js
    frontend after the user confirms the IntentParser preview).

    Tries real discover via ONIX adapter first. Falls back to the local
    catalog if ONIX is unavailable, so the frontend works without Docker.

    POST /discover
    Body:     BecknIntent fields (item, quantity, location_coordinates, …)
    Response: { transaction_id, offerings: [...], status: "live"|"mock" }
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
            result = await asyncio.wait_for(
                client.discover_async(intent, collector, timeout=10.0),
                timeout=12.0,
            )
        offerings = [o.model_dump() for o in result.offerings]
        return web.json_response({
            "transaction_id": result.transaction_id,
            "offerings":      offerings,
            "status":         "live",
        })
    except Exception as exc:
        logger.warning("ONIX discover failed (%s) — returning local catalog", exc)
        return web.json_response({
            "transaction_id": str(uuid.uuid4()),
            "offerings":      _local_catalog_as_offerings(),
            "status":         "mock",
        })


def create_app() -> web.Application:
    app = web.Application()
    app.router.add_get("/health", health)
    app.router.add_post("/discover", discover)                    # frontend integration
    app.router.add_post("/bap/receiver/{action}", bap_receiver)
    app.router.add_post("/bpp/discover", bpp_discover)
    app.router.add_post("/{action}", bap_receiver)  # real Beckn network posts without prefix
    return app


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    app = create_app()
    web.run_app(app, host="0.0.0.0", port=8000)
