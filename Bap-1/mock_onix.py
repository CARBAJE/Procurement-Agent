"""
Mock beckn-onix Adapter — simulates the Go ONIX adapter for local development.

Runs on port 8081. Provides:
  POST /bap/caller/discover  → ACK + async on_discover callback
  POST /bap/caller/select    → ACK + async on_select   callback
  POST /bap/caller/init      → ACK + async on_init     callback (Phase 2)
  POST /bap/caller/confirm   → ACK + async on_confirm  callback (Phase 2)
  POST /bap/caller/status    → ACK + async on_status   callback (Phase 2)

The Phase 2 callbacks progress the mock order through a realistic lifecycle:
  - on_init    returns payment terms (COD) and the final quote
  - on_confirm assigns an order_id and sets state=ACCEPTED
  - on_status  advances the state on each poll
               ACCEPTED → PACKED → SHIPPED → OUT_FOR_DELIVERY → DELIVERED

Run in a separate terminal:
    python mock_onix.py

Then run the BAP:
    python run.py
"""
from __future__ import annotations

import asyncio
import itertools
import logging
from uuid import uuid4

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

# ── Status state machine for /status polling ─────────────────────────────────
# order_id → cycling iterator over the delivery lifecycle. Each /status call
# advances one step; once DELIVERED we stay there.
_STATE_CYCLE = [
    "ACCEPTED",
    "PACKED",
    "SHIPPED",
    "OUT_FOR_DELIVERY",
    "DELIVERED",
]
_order_state: dict[str, int] = {}   # order_id → current index in cycle


def _next_state(order_id: str) -> str:
    idx = _order_state.get(order_id, 0)
    _order_state[order_id] = min(idx + 1, len(_STATE_CYCLE) - 1)
    return _STATE_CYCLE[idx if idx < len(_STATE_CYCLE) else -1]


# ── Helpers ───────────────────────────────────────────────────────────────────


async def _post_callback(action: str, payload: dict) -> None:
    """POST a callback to the BAP receiver with a short simulated delay."""
    await asyncio.sleep(0.5)
    url = f"{BAP_BASE_URL}/{action}"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload) as resp:
                ack = await resp.json()
                log.info("%s sent -> BAP | ACK=%s", action, ack)
    except Exception as e:
        log.error("Failed to send %s callback: %s", action, e)


# ── Route handlers ────────────────────────────────────────────────────────────


async def health(request: web.Request) -> web.Response:
    return web.json_response({"status": "ok", "role": "mock-onix-adapter", "version": "2.0.0"})


async def bap_caller_discover(request: web.Request) -> web.Response:
    """Receive /bap/caller/discover from Python agent."""
    payload = await request.json()
    context = payload.get("context", {})
    txn_id = context.get("transactionId") or context.get("transaction_id", "unknown")
    log.info("/bap/caller/discover | txn=%s", txn_id)

    asyncio.create_task(send_on_discover_callback(context))
    return web.json_response({"message": {"ack": {"status": "ACK"}}})


async def send_on_discover_callback(context: dict) -> None:
    payload = {
        "context": {
            **context,
            "action": "on_discover",
            "bppId": "mock-catalog-service",
            "bppUri": "http://localhost:8081",
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
    await _post_callback("on_discover", payload)


async def bap_caller_select(request: web.Request) -> web.Response:
    """Receive /select — ACK + async on_select with seller quote."""
    payload = await request.json()
    context = payload.get("context", {})
    txn_id = context.get("transactionId") or context.get("transaction_id", "unknown")
    log.info("/bap/caller/select | txn=%s", txn_id)

    asyncio.create_task(send_on_select_callback(context, payload.get("message", {})))
    return web.json_response({"message": {"ack": {"status": "ACK"}}})


async def send_on_select_callback(context: dict, message: dict) -> None:
    contract = message.get("contract") or {}
    payload = {
        "context": {**context, "action": "on_select"},
        "message": {
            "contract": {
                **contract,
                "status": {"code": "ACCEPTED"},
                "quote": {
                    "price": {
                        "currency": "INR",
                        "value": _first_consideration_value(contract) or "189.00",
                    },
                },
            }
        },
    }
    await _post_callback("on_select", payload)


def _first_consideration_value(contract: dict) -> str | None:
    considerations = contract.get("consideration") or []
    if considerations:
        return considerations[0].get("price", {}).get("value")
    return None


async def bap_caller_init(request: web.Request) -> web.Response:
    """Receive /init — ACK + async on_init with payment terms (COD)."""
    payload = await request.json()
    context = payload.get("context", {})
    message = payload.get("message", {})
    txn_id = context.get("transactionId") or context.get("transaction_id", "unknown")
    log.info("/bap/caller/init | txn=%s", txn_id)

    asyncio.create_task(send_on_init_callback(context, message))
    return web.json_response({"message": {"ack": {"status": "ACK"}}})


async def send_on_init_callback(context: dict, message: dict) -> None:
    """BPP drafts payment terms — for this mock, confirm COD as proposed."""
    contract = message.get("contract") or {}
    quote_value = _first_consideration_value(contract) or "189.00"

    payload = {
        "context": {**context, "action": "on_init"},
        "message": {
            "contract": {
                **contract,
                "status": {"code": "INITIALIZED"},
                "payment": {
                    "type": "ON_FULFILLMENT",
                    "collectedBy": "BPP",
                    "status": "NOT-PAID",
                    "currency": "INR",
                },
                "quote": {
                    "price": {"currency": "INR", "value": quote_value},
                },
            }
        },
    }
    await _post_callback("on_init", payload)


async def bap_caller_confirm(request: web.Request) -> web.Response:
    """Receive /confirm — ACK + async on_confirm with order_id."""
    payload = await request.json()
    context = payload.get("context", {})
    message = payload.get("message", {})
    txn_id = context.get("transactionId") or context.get("transaction_id", "unknown")
    log.info("/bap/caller/confirm | txn=%s", txn_id)

    asyncio.create_task(send_on_confirm_callback(context, message))
    return web.json_response({"message": {"ack": {"status": "ACK"}}})


async def send_on_confirm_callback(context: dict, message: dict) -> None:
    contract = message.get("contract") or {}
    order_id = f"order-{uuid4().hex[:12]}"
    # Seed the status cycle so the first /status poll returns PACKED.
    _order_state[order_id] = 1   # next state on first poll = PACKED

    payload = {
        "context": {**context, "action": "on_confirm"},
        "message": {
            "order": {
                "id": order_id,
                "contractId": contract.get("id"),
                "status": {"code": "ACCEPTED"},
                "state": "ACCEPTED",
                "fulfillmentEta": "2026-04-26T10:00:00.000Z",
            }
        },
    }
    await _post_callback("on_confirm", payload)


async def bap_caller_status(request: web.Request) -> web.Response:
    """Receive /status — ACK + async on_status advancing the lifecycle."""
    payload = await request.json()
    context = payload.get("context", {})
    message = payload.get("message", {})
    txn_id = context.get("transactionId") or context.get("transaction_id", "unknown")
    order_id = message.get("orderId") or message.get("order_id", "unknown")
    log.info("/bap/caller/status | txn=%s order=%s", txn_id, order_id)

    asyncio.create_task(send_on_status_callback(context, order_id))
    return web.json_response({"message": {"ack": {"status": "ACK"}}})


async def send_on_status_callback(context: dict, order_id: str) -> None:
    state = _next_state(order_id)
    payload = {
        "context": {**context, "action": "on_status"},
        "message": {
            "order": {
                "id": order_id,
                "state": state,
                "status": {"code": state},
                "fulfillment": {
                    "eta": "2026-04-26T10:00:00.000Z",
                    "trackingUrl": f"http://localhost:8081/track/{order_id}",
                },
            }
        },
    }
    await _post_callback("on_status", payload)


async def bap_caller_generic(request: web.Request) -> web.Response:
    """Fallback for any other /bap/caller/{action} — just ACK."""
    action = request.match_info["action"]
    payload = await request.json()
    txn_id = payload.get("context", {}).get("transactionId", "unknown")
    log.info("/bap/caller/%s received (fallback ACK) | txn=%s", action, txn_id)
    return web.json_response({"message": {"ack": {"status": "ACK"}}})


# ── App ───────────────────────────────────────────────────────────────────────


def create_app() -> web.Application:
    app = web.Application()
    app.router.add_get("/health", health)
    app.router.add_post("/bap/caller/discover", bap_caller_discover)
    app.router.add_post("/bap/caller/select",   bap_caller_select)
    app.router.add_post("/bap/caller/init",     bap_caller_init)
    app.router.add_post("/bap/caller/confirm",  bap_caller_confirm)
    app.router.add_post("/bap/caller/status",   bap_caller_status)
    app.router.add_post("/bap/caller/{action}", bap_caller_generic)
    return app


if __name__ == "__main__":
    log.info("Mock ONIX adapter starting on http://localhost:8081 (Beckn v2)")
    log.info("Catalog: %d offerings registered", len(CATALOG))
    app = create_app()
    web.run_app(app, host="0.0.0.0", port=8081)
