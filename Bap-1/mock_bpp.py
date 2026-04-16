"""
Mock BPP (Seller) Server — simulates a real Beckn seller responding to searches.

Runs on port 8001. Receives /search from the gateway, calls back /on_search
on the BAP, and handles /select.

Run in a separate terminal:
    python mock_bpp.py

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

# ── Mock catalog (what this BPP sells) ───────────────────────────────────────

SELLERS = [
    {
        "bpp_id": "officeworld-bpp",
        "bpp_name": "OfficeWorld Supplies",
        "provider_id": "prov-officeworld-001",
        "item_id": "item-a4-80gsm",
        "item_name": "A4 Paper 80gsm (500 sheets)",
        "price": "195.00",
        "rating": "4.8",
    },
    {
        "bpp_id": "paperdirect-bpp",
        "bpp_name": "PaperDirect India",
        "provider_id": "prov-paperdirect-001",
        "item_id": "item-a4-ream",
        "item_name": "A4 Paper 80gsm Ream",
        "price": "189.00",
        "rating": "4.5",
    },
    {
        "bpp_id": "stathub-bpp",
        "bpp_name": "Stationery Hub",
        "provider_id": "prov-stathub-001",
        "item_id": "item-a4-premium",
        "item_name": "A4 Paper Premium 80gsm",
        "price": "201.00",
        "rating": "4.9",
    },
]

BAP_CALLBACK_URL = "http://localhost:8000/on_search"


# ── Helpers ───────────────────────────────────────────────────────────────────


def build_on_search_payload(context: dict, seller: dict) -> dict:
    """Build a Beckn-compliant on_search payload for a given seller."""
    return {
        "context": {
            **context,
            "action": "on_search",
            "bpp_id": seller["bpp_id"],
            "bpp_uri": f"http://localhost:8001/{seller['bpp_id']}",
        },
        "message": {
            "catalog": {
                "bpp/descriptor": {"name": seller["bpp_name"]},
                "bpp/providers": [
                    {
                        "id": seller["provider_id"],
                        "descriptor": {"name": seller["bpp_name"]},
                        "rating": seller["rating"],
                        "items": [
                            {
                                "id": seller["item_id"],
                                "descriptor": {"name": seller["item_name"]},
                                "price": {
                                    "currency": "INR",
                                    "value": seller["price"],
                                },
                                "quantity": {"count": 500},
                            }
                        ],
                    }
                ],
            }
        },
    }


async def send_on_search_callback(context: dict, seller: dict) -> None:
    """POST /on_search to the BAP after a simulated processing delay."""
    await asyncio.sleep(0.5)  # simulate BPP processing time
    payload = build_on_search_payload(context, seller)
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(BAP_CALLBACK_URL, json=payload) as resp:
                ack = await resp.json()
                log.info(
                    "on_search sent -> BAP | seller=%s | ACK=%s",
                    seller["bpp_id"],
                    ack,
                )
    except Exception as e:
        log.error("Failed to send on_search callback: %s", e)


# ── Route handlers ────────────────────────────────────────────────────────────


async def health(request: web.Request) -> web.Response:
    return web.json_response({"status": "ok", "role": "mock-bpp"})


async def handle_search(request: web.Request) -> web.Response:
    """Receive /search from the BAP gateway and trigger on_search callbacks."""
    payload = await request.json()
    context = payload.get("context", {})
    txn_id = context.get("transaction_id", "unknown")
    item = payload.get("message", {}).get("intent", {}).get("item", {})
    item_name = item.get("descriptor", {}).get("name", "unknown")

    log.info("Received /search | txn=%s | item=%s", txn_id, item_name)

    # Fire callbacks for each mock seller asynchronously
    for seller in SELLERS:
        asyncio.create_task(send_on_search_callback(context, seller))

    return web.json_response({"message": {"ack": {"status": "ACK"}}})


async def handle_select(request: web.Request) -> web.Response:
    """Receive /select from the BAP."""
    payload = await request.json()
    context = payload.get("context", {})
    order = payload.get("message", {}).get("order", {})
    txn_id = context.get("transaction_id", "unknown")
    provider_id = order.get("provider", {}).get("id", "unknown")

    log.info("Received /select | txn=%s | provider=%s", txn_id, provider_id)

    return web.json_response({"message": {"ack": {"status": "ACK"}}})


# ── App ───────────────────────────────────────────────────────────────────────


def create_app() -> web.Application:
    app = web.Application()
    app.router.add_get("/health", health)
    app.router.add_post("/search", handle_search)      # gateway endpoint
    app.router.add_post("/{bpp_id}/select", handle_select)
    return app


if __name__ == "__main__":
    log.info("Mock BPP server starting on http://localhost:8001")
    log.info("Sellers: %s", [s["bpp_name"] for s in SELLERS])
    app = create_app()
    web.run_app(app, host="0.0.0.0", port=8001)
