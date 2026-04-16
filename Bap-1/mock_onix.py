"""
Mock beckn-onix Adapter — simulates the Go ONIX adapter for local development.

Runs on port 8081. Provides:
  POST /discover       → synchronous catalog response (v2 discovery)
  POST /bap/caller/select  → ACK + optional on_select callback to BAP

Run in a separate terminal:
    python mock_onix.py

Then run the BAP:
    python run.py
"""
from __future__ import annotations

import asyncio
import logging

import aiohttp
from aiohttp import web

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
)
log = logging.getLogger(__name__)

# ── Catalog (what BPPs have registered via /publish) ─────────────────────────

CATALOG = [
    {
        "bpp_id": "officeworld-bpp",
        "bpp_uri": "http://localhost:8082/officeworld",
        "provider_id": "prov-officeworld",
        "provider_name": "OfficeWorld Supplies",
        "item_id": "item-a4-80gsm",
        "item_name": "A4 Paper 80gsm (500 sheets)",
        "price_value": "195.00",
        "price_currency": "INR",
        "rating": "4.8",
        "available_quantity": 10000,
        "fulfillment_hours": 48,
    },
    {
        "bpp_id": "paperdirect-bpp",
        "bpp_uri": "http://localhost:8082/paperdirect",
        "provider_id": "prov-paperdirect",
        "provider_name": "PaperDirect India",
        "item_id": "item-a4-ream",
        "item_name": "A4 Paper 80gsm Ream",
        "price_value": "189.00",
        "price_currency": "INR",
        "rating": "4.5",
        "available_quantity": 5000,
        "fulfillment_hours": 72,
    },
    {
        "bpp_id": "stathub-bpp",
        "bpp_uri": "http://localhost:8082/stathub",
        "provider_id": "prov-stathub",
        "provider_name": "Stationery Hub",
        "item_id": "item-a4-premium",
        "item_name": "A4 Paper Premium 80gsm",
        "price_value": "201.00",
        "price_currency": "INR",
        "rating": "4.9",
        "available_quantity": 2000,
        "fulfillment_hours": 24,
    },
]

BAP_BASE_URL = "http://localhost:8000/bap/receiver"


# ── Route handlers ────────────────────────────────────────────────────────────


async def health(request: web.Request) -> web.Response:
    return web.json_response({"status": "ok", "role": "mock-onix-adapter", "version": "2.0.0"})


async def bap_caller_discover(request: web.Request) -> web.Response:
    """Receive /bap/caller/discover from Python agent.

    Mirrors the real ONIX adapter:
      - ACK immediately
      - Send on_discover callback asynchronously with catalog
    """
    payload = await request.json()
    context = payload.get("context", {})
    intent = payload.get("message", {})
    txn_id = context.get("transaction_id", "unknown")
    item = intent.get("item", "unknown")

    log.info("/bap/caller/discover | txn=%s | item=%s", txn_id, item)

    asyncio.create_task(send_on_discover_callback(context))

    return web.json_response({"message": {"ack": {"status": "ACK"}}})


async def send_on_discover_callback(context: dict) -> None:
    """Async: simulate Discovery Service returning catalog via on_discover callback."""
    await asyncio.sleep(0.5)
    payload = {
        "context": {
            **context,
            "action": "on_discover",
            "bpp_id": "mock-catalog-service",
            "bpp_uri": "http://localhost:8081",
        },
        "message": {
            "catalog": {
                "providers": [
                    {
                        "id": entry["provider_id"],
                        "descriptor": {"name": entry["provider_name"]},
                        "rating": entry["rating"],
                        "items": [
                            {
                                "id": entry["item_id"],
                                "descriptor": {"name": entry["item_name"]},
                                "price": {
                                    "value": entry["price_value"],
                                    "currency": entry["price_currency"],
                                },
                                "quantity": {"available": {"count": entry["available_quantity"]}},
                            }
                        ],
                    }
                    for entry in CATALOG
                ]
            }
        },
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(f"{BAP_BASE_URL}/on_discover", json=payload) as resp:
                ack = await resp.json()
                log.info("on_discover sent -> BAP | ACK=%s", ack)
    except Exception as e:
        log.error("Failed to send on_discover callback: %s", e)


async def send_on_select_callback(context: dict, order: dict) -> None:
    """Async: simulate BPP processing select and calling back /on_select."""
    await asyncio.sleep(0.5)
    payload = {
        "context": {**context, "action": "on_select"},
        "message": {
            "order": {
                **order,
                "state": "ACCEPTED",
                "quote": {
                    "price": {"currency": "INR", "value": order.get("items", [{}])[0].get("price", "189.00")},
                },
            }
        },
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(f"{BAP_BASE_URL}/on_select", json=payload) as resp:
                ack = await resp.json()
                log.info("on_select sent -> BAP | ACK=%s", ack)
    except Exception as e:
        log.error("Failed to send on_select callback: %s", e)


async def bap_caller_select(request: web.Request) -> web.Response:
    """Receive /select from Python agent, ACK immediately, trigger async callback."""
    payload = await request.json()
    context = payload.get("context", {})
    order = payload.get("message", {}).get("order", {})
    txn_id = context.get("transaction_id", "unknown")
    provider_id = order.get("provider", {}).get("id", "unknown")

    log.info("/select received | txn=%s | provider=%s", txn_id, provider_id)

    # Fire on_select callback asynchronously
    asyncio.create_task(send_on_select_callback(context, order))

    return web.json_response({"message": {"ack": {"status": "ACK"}}})


async def bap_caller_generic(request: web.Request) -> web.Response:
    """Handle init/confirm/status calls — just ACK for now."""
    action = request.match_info["action"]
    payload = await request.json()
    txn_id = payload.get("context", {}).get("transaction_id", "unknown")
    log.info("/bap/caller/%s received | txn=%s", action, txn_id)
    return web.json_response({"message": {"ack": {"status": "ACK"}}})


# ── App ───────────────────────────────────────────────────────────────────────


def create_app() -> web.Application:
    app = web.Application()
    app.router.add_get("/health", health)
    app.router.add_post("/bap/caller/discover", bap_caller_discover)
    app.router.add_post("/bap/caller/select", bap_caller_select)
    app.router.add_post("/bap/caller/{action}", bap_caller_generic)
    return app


if __name__ == "__main__":
    log.info("Mock ONIX adapter starting on http://localhost:8081 (Beckn v2)")
    log.info("Catalog: %d offerings registered", len(CATALOG))
    app = create_app()
    web.run_app(app, host="0.0.0.0", port=8081)
