"""BAP callback server for Beckn v2 async transaction callbacks.

In Beckn v2, discovery is synchronous — no /on_search endpoint needed.
This server handles async callbacks from the ONIX adapter for transactional
flows: on_select, on_init, on_confirm, on_status.

Also exposes a local BPP discover endpoint (POST /bpp/discover) so that
onix-bap can route discover requests here instead of the external Discover
Service. This avoids the need for a public URL / ngrok for local development.

Frontend-facing HTTP API (Phase 2 — Comparison UI):

    POST /parse                               NL → BecknIntent (Ollama)
    POST /compare                             discover + rank only, no commit
    POST /commit                              select + init + confirm for a txn
    GET  /status/{txn_id}/{order_id}          poll order state

    POST /bap/receiver/{action}               async callbacks from ONIX
    POST /bpp/discover                        local catalog handler
    POST /{action}                            real Beckn network callbacks

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
from datetime import datetime, timezone
from typing import Optional

# Allow `shared/` (one level up from Bap-1/) to be importable — same as run.py
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))

import aiohttp
from aiohttp import web

from src.agent import ProcurementAgent, TransactionSessionStore
from src.beckn.adapter import BecknProtocolAdapter
from src.beckn.callbacks import CallbackCollector
from src.beckn.models import BecknIntent, DiscoverOffering
from src.beckn.providers import build_providers
from src.config import BecknConfig

logger = logging.getLogger(__name__)

config = BecknConfig()
collector = CallbackCollector(default_timeout=config.callback_timeout)

# TODO(persistence): swap InMemoryBackend for PostgresBackend here.
# See: Bap-1/docs/ARCHITECTURE.md §7.2 #6.
session_store = TransactionSessionStore()

SUPPORTED_CALLBACKS = {"on_discover", "on_select", "on_init", "on_confirm", "on_status"}

_PROCUREMENT_INTENTS = {"SearchProduct", "RequestQuote", "PurchaseOrder"}

# ── Local catalog — returned for every discover request ───────────────────────
# Six offerings with deliberate diversity so the Comparison UI has something
# meaningful to render (price, rating, ETA, stock, specifications all vary).
# Mirrors the data in starter-kit/.../publish_catalog.py in the Docker path.

_LOCAL_CATALOG = [
    {
        "id": "item-a4-paperdirect",
        "descriptor": {
            "name": "A4 Paper 80gsm Ream",
            "shortDesc": "Standard A4 80gsm ream, 500 sheets",
        },
        "provider": {"id": "PROV-PAPERDIRECT-01", "descriptor": {"name": "PaperDirect India"}},
        "price": {"value": "168.00", "currency": "INR"},
        "rating": {"ratingValue": 4.2},
        "quantity": {"available": {"count": 5000}},
        "fulfillmentHours": 48,
        "specifications": ["Brightness 92", "Recycled 30%", "ISO 9001"],
    },
    {
        "id": "item-a4-officeworld",
        "descriptor": {
            "name": "A4 Paper 80gsm (500 sheets)",
            "shortDesc": "Trusted brand A4 paper, office grade",
        },
        "provider": {"id": "PROV-OFFICEWORLD-01", "descriptor": {"name": "OfficeWorld Supplies"}},
        "price": {"value": "195.00", "currency": "INR"},
        "rating": {"ratingValue": 4.8},
        "quantity": {"available": {"count": 1000}},
        "fulfillmentHours": 24,
        "specifications": ["Brightness 96", "Recycled 50%", "FSC Certified"],
    },
    {
        "id": "item-a4-stathub-premium",
        "descriptor": {
            "name": "A4 Paper Premium 80gsm",
            "shortDesc": "Premium A4 paper, high brightness",
        },
        "provider": {"id": "PROV-STATHUB-01", "descriptor": {"name": "Stationery Hub"}},
        "price": {"value": "218.00", "currency": "INR"},
        "rating": {"ratingValue": 4.9},
        "quantity": {"available": {"count": 500}},
        "fulfillmentHours": 72,
        "specifications": ["Brightness 98", "FSC Certified", "Acid-free"],
    },
    {
        "id": "item-a4-greenleaf",
        "descriptor": {
            "name": "A4 Paper Eco 80gsm",
            "shortDesc": "100% recycled A4 paper",
        },
        "provider": {"id": "PROV-GREENLEAF-01", "descriptor": {"name": "GreenLeaf Papers"}},
        "price": {"value": "182.00", "currency": "INR"},
        "rating": {"ratingValue": 4.4},
        "quantity": {"available": {"count": 2000}},
        "fulfillmentHours": 96,
        "specifications": ["Brightness 88", "Recycled 100%", "FSC Certified"],
    },
    {
        "id": "item-a4-quickprint",
        "descriptor": {
            "name": "A4 Paper 80gsm Express",
            "shortDesc": "Same-day dispatch A4 paper",
        },
        "provider": {"id": "PROV-QUICKPRINT-01", "descriptor": {"name": "QuickPrint Depot"}},
        "price": {"value": "205.00", "currency": "INR"},
        "rating": {"ratingValue": 4.0},
        "quantity": {"available": {"count": 200}},
        "fulfillmentHours": 24,
        "specifications": ["Brightness 94", "ISO 9001"],
    },
    {
        "id": "item-a4-budgetpaper",
        "descriptor": {
            "name": "A4 Paper Basic 80gsm",
            "shortDesc": "Budget-friendly A4 paper",
        },
        "provider": {"id": "PROV-BUDGETPAPER-01", "descriptor": {"name": "Budget Paper Co"}},
        "price": {"value": "165.00", "currency": "INR"},
        "rating": {"ratingValue": 3.9},
        "quantity": {"available": {"count": 3000}},
        "fulfillmentHours": 120,
        "specifications": ["Brightness 85", "Recycled 20%"],
    },
]


# ── Utilities ─────────────────────────────────────────────────────────────────


def _build_agent(discover_timeout: float = 10.0, callback_timeout: float = 10.0) -> ProcurementAgent:
    adapter = BecknProtocolAdapter(config)
    return ProcurementAgent(
        adapter,
        collector,
        providers=build_providers(config),
        discover_timeout=discover_timeout,
        callback_timeout=callback_timeout,
    )


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
            "available_quantity": item.get("quantity", {}).get("available", {}).get("count"),
            "rating":        str(item["rating"]["ratingValue"]) if item.get("rating") else None,
            "specifications": item.get("specifications", []),
            "fulfillment_hours": item.get("fulfillmentHours"),
        })
    return result


def _local_catalog_offerings_for_state() -> list[DiscoverOffering]:
    """Same data as `_local_catalog_as_offerings` but as DiscoverOffering instances
    so it can live in a ProcurementState (for the mock-fallback compare path)."""
    return [DiscoverOffering(**o) for o in _local_catalog_as_offerings()]


def _build_scoring(offerings: list[DiscoverOffering], recommended_item_id: Optional[str]) -> dict:
    """Produce the multi-criterion-ready scoring payload.

    Today populates a single `price` criterion (Phase 1 heuristic). When the
    Comparison Engine ships, replace this helper with an injected
    ScoringStrategy.score(offerings) that returns richer criteria (tco,
    reputation, eta, compliance) in the same shape.

    TODO(comparison-engine): swap out for the strategy-based implementation.
    See: Bap-1/docs/ARCHITECTURE.md §7.2 #7.
    """
    if not offerings:
        return {"recommended_item_id": None, "criteria": [], "ranking": []}

    prices = [float(o.price_value) for o in offerings]
    p_min, p_max = min(prices), max(prices)
    spread = (p_max - p_min) or 1.0

    price_scores = []
    for o in offerings:
        raw = float(o.price_value)
        # Lower is better → normalize to [0, 1] with 1 = cheapest.
        normalized = 1.0 - (raw - p_min) / spread
        explanation = (
            "Cheapest option" if raw == p_min else
            f"₹{raw - p_min:.2f} above cheapest"
        )
        price_scores.append({
            "item_id": o.item_id,
            "raw": o.price_value,
            "normalized": round(normalized, 4),
            "explanation": explanation,
        })

    ranking = sorted(
        [
            {
                "item_id": s["item_id"],
                "composite_score": s["normalized"],
                "rank": 0,
            }
            for s in price_scores
        ],
        key=lambda r: -r["composite_score"],
    )
    for idx, row in enumerate(ranking, start=1):
        row["rank"] = idx

    return {
        "recommended_item_id": recommended_item_id,
        "criteria": [
            {
                "key": "price",
                "label": "Price",
                "weight": 1.0,
                "direction": "min",
                "scores": price_scores,
            }
        ],
        "ranking": ranking,
    }


def _serialize_step(step: dict) -> dict:
    """Reasoning steps are already plain dicts — pass through unchanged."""
    return step


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


# ── Callback receiver routes ──────────────────────────────────────────────────


async def health(request: web.Request) -> web.Response:
    return web.json_response({
        "status": "ok",
        "bap_id": config.bap_id,
        "version": config.core_version,
    })


async def bap_receiver(request: web.Request) -> web.Response:
    """Handle async callbacks from ONIX adapter or directly from the network."""
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

    ack = await collector.handle_callback(action, payload)
    return web.json_response(ack)


async def bpp_discover(request: web.Request) -> web.Response:
    """Local BPP catalog handler — receives discover from onix-bap and sends
    on_discover directly back to our own callback server."""
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
    """Build on_discover payload from local catalog and POST to our callback route."""
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


# ── Frontend-facing API ───────────────────────────────────────────────────────


async def parse(request: web.Request) -> web.Response:
    """POST /parse — NL → BecknIntent via IntentParser (Ollama)."""
    try:
        body = await request.json()
    except json.JSONDecodeError:
        raise web.HTTPBadRequest(reason="Invalid JSON")

    query = body.get("query", "").strip()
    if not query:
        raise web.HTTPBadRequest(reason="query is required")

    try:
        from IntentParser import parse_request
        result = parse_request(query)

        intent_type = "procurement" if result.intent in _PROCUREMENT_INTENTS else "unknown"
        beckn_dict = None
        if result.beckn_intent:
            beckn_dict = {**result.beckn_intent.model_dump(), "unit": "unit"}

        return web.json_response({
            "intent":       intent_type,
            "confidence":   result.confidence,
            "beckn_intent": beckn_dict,
            "routed_to":    result.routed_to or "qwen3:1.7b",
        })
    except Exception as exc:
        logger.error("Intent parsing failed: %s", exc)
        # Exception messages from instructor/openai can be multiline and
        # aiohttp forbids newlines in the HTTP reason phrase. Return JSON
        # instead so the frontend proxy can fall back to the stub intent.
        return web.json_response(
            {"error": "Intent parsing failed", "detail": str(exc).splitlines()[0][:200]},
            status=500,
        )


async def compare(request: web.Request) -> web.Response:
    """POST /compare — run discover + rank, store state, return offerings + scoring.

    Body:     BecknIntent fields (item, quantity, location_coordinates, …)
    Response: {
        transaction_id,
        offerings[],
        recommended_item_id,
        scoring: {criteria, ranking},
        reasoning_steps[],
        messages[],
        status: "live" | "mock"
    }
    """
    try:
        body = await request.json()
    except json.JSONDecodeError:
        raise web.HTTPBadRequest(reason="Invalid JSON")

    try:
        intent = BecknIntent(**body)
    except Exception as exc:
        return web.json_response(
            {"error": "Invalid BecknIntent", "detail": str(exc)},
            status=422,
        )

    agent = _build_agent()

    try:
        state = await agent.arun_compare(intent)
    except Exception as exc:
        logger.warning("arun_compare crashed (%s) — returning mock", exc)
        return _mock_compare_response(intent)

    if state.get("error") or not state.get("offerings"):
        logger.warning("Compare had no offerings (%s) — returning mock", state.get("error"))
        return _mock_compare_response(intent, upstream_state=state)

    offerings_models: list[DiscoverOffering] = state["offerings"]
    selected = state.get("selected")
    recommended_item_id = selected.item_id if selected else None

    txn_id = state.get("transaction_id") or str(uuid.uuid4())
    # Ensure the txn id is set so commit can recover state.
    state["transaction_id"] = txn_id
    session_store.put(txn_id, state)

    return web.json_response({
        "transaction_id": txn_id,
        "offerings": [o.model_dump() for o in offerings_models],
        "recommended_item_id": recommended_item_id,
        "scoring": _build_scoring(offerings_models, recommended_item_id),
        "reasoning_steps": [_serialize_step(s) for s in state.get("reasoning_steps", [])],
        "messages": state.get("messages", []),
        "status": "live",
    })


def _mock_compare_response(intent: BecknIntent, upstream_state: Optional[dict] = None) -> web.Response:
    """Fallback compare response using the local catalog (Docker stack offline)."""
    txn_id = str(uuid.uuid4())
    offerings_dicts = _local_catalog_as_offerings()
    offerings_models = [DiscoverOffering(**o) for o in offerings_dicts]
    recommended = min(offerings_models, key=lambda o: float(o.price_value))

    # Synthesize a reasoning trace that resembles the live path so the UI
    # has something meaningful to show even when ONIX is offline.
    upstream_steps = (upstream_state or {}).get("reasoning_steps", [])
    upstream_messages = (upstream_state or {}).get("messages", [])
    synthetic_steps = upstream_steps + [
        {
            "node": "rank_and_select",
            "role": "reason",
            "summary": f"Recommended {recommended.provider_name} — cheapest of {len(offerings_models)} (mock)",
            "details": {
                "strategy": "price_only",
                "recommended_item_id": recommended.item_id,
                "recommended_provider": recommended.provider_name,
                "offering_count": len(offerings_models),
            },
            "timestamp": _now_iso(),
        },
    ]
    synthetic_messages = upstream_messages + [
        f"[rank_and_select] selected {recommended.provider_name!r} "
        f"₹{recommended.price_value} (cheapest of {len(offerings_models)})"
    ]

    # Pre-populate a session state so /commit still works against the mock path.
    mock_state = {
        "request": intent.item,
        "intent": intent,
        "transaction_id": txn_id,
        "offerings": offerings_models,
        "selected": recommended,
        "messages": synthetic_messages,
        "reasoning_steps": synthetic_steps,
    }
    session_store.put(txn_id, mock_state)  # type: ignore[arg-type]

    return web.json_response({
        "transaction_id": txn_id,
        "offerings": offerings_dicts,
        "recommended_item_id": recommended.item_id,
        "scoring": _build_scoring(offerings_models, recommended.item_id),
        "reasoning_steps": synthetic_steps,
        "messages": synthetic_messages,
        "status": "mock",
    })


async def commit(request: web.Request) -> web.Response:
    """POST /commit — run select + init + confirm for a previously compared txn.

    Body:     { transaction_id, chosen_item_id }
    Response: {
        transaction_id, order_id, order_state,
        payment_terms, fulfillment_eta,
        bpp_id, bpp_uri, contract_id,
        reasoning_steps[], messages[],
        status
    }
    """
    try:
        body = await request.json()
    except json.JSONDecodeError:
        raise web.HTTPBadRequest(reason="Invalid JSON")

    txn_id = body.get("transaction_id")
    chosen_item_id = body.get("chosen_item_id")
    if not txn_id or not chosen_item_id:
        raise web.HTTPBadRequest(reason="transaction_id and chosen_item_id are required")

    state = session_store.get(txn_id)
    if state is None:
        raise web.HTTPNotFound(reason=f"Unknown transaction_id: {txn_id}")

    offerings: list[DiscoverOffering] = state.get("offerings", [])
    chosen = next((o for o in offerings if o.item_id == chosen_item_id), None)
    if chosen is None:
        raise web.HTTPUnprocessableEntity(
            reason=f"chosen_item_id {chosen_item_id!r} is not in the compared offerings"
        )

    # TODO(approval-workflow): if ApprovalProvider.required(state) is True,
    # return 202 Accepted with {approval_pending: true} instead of committing.
    # See: Bap-1/docs/ARCHITECTURE.md §7.3 #10.

    # Override the recommendation with the user's pick.
    state["selected"] = chosen
    # Carry-over for commit graph: LangGraph merges additively but the entry
    # state needs prior messages present so they're kept for the full trace.
    state.setdefault("messages", [])
    state.setdefault("reasoning_steps", [])

    agent = _build_agent()

    try:
        final_state = await agent.arun_commit(state)
    except Exception as exc:
        logger.warning("arun_commit crashed (%s) — returning mock", exc)
        return _mock_commit_response(txn_id, chosen, state)

    session_store.put(txn_id, final_state)

    if final_state.get("error"):
        logger.warning("Commit ended with error: %s", final_state["error"])
        return _mock_commit_response(txn_id, chosen, final_state)

    order_id = final_state.get("order_id")
    order_state = final_state.get("order_state")
    payment_terms = final_state.get("payment_terms")
    confirm_resp = final_state.get("confirm_response")

    return web.json_response({
        "transaction_id": txn_id,
        "order_id": order_id,
        "order_state": order_state.value if order_state else None,
        "payment_terms": payment_terms.model_dump() if payment_terms else None,
        "fulfillment_eta": confirm_resp.fulfillment_eta if confirm_resp else None,
        "bpp_id": chosen.bpp_id,
        "bpp_uri": chosen.bpp_uri,
        "contract_id": final_state.get("contract_id"),
        "reasoning_steps": final_state.get("reasoning_steps", []),
        "messages": final_state.get("messages", []),
        "status": "live",
    })


def _mock_commit_response(
    txn_id: str,
    chosen: DiscoverOffering,
    state: dict,
) -> web.Response:
    """Synthesize a plausible commit result when the Docker stack is offline."""
    order_id = f"mock-order-{uuid.uuid4().hex[:8]}"
    mock_state = {
        **state,
        "order_id": order_id,
        "messages": state.get("messages", []),
        "reasoning_steps": state.get("reasoning_steps", []),
    }
    session_store.put(txn_id, mock_state)  # type: ignore[arg-type]
    return web.json_response({
        "transaction_id": txn_id,
        "order_id": order_id,
        "order_state": "CREATED",
        "payment_terms": {
            "type": "ON_FULFILLMENT",
            "collected_by": "BPP",
            "currency": chosen.price_currency,
            "status": "NOT-PAID",
        },
        "fulfillment_eta": None,
        "bpp_id": chosen.bpp_id,
        "bpp_uri": chosen.bpp_uri,
        "contract_id": state.get("contract_id"),
        "reasoning_steps": state.get("reasoning_steps", []),
        "messages": state.get("messages", []),
        "status": "mock",
    })


async def status(request: web.Request) -> web.Response:
    """GET /status/{txn_id}/{order_id}?bpp_id=...&bpp_uri=...

    Single-shot /status poll. bpp_id and bpp_uri can be omitted — the server
    will recover them from the session if present.

    TODO(realtime-ws): a teammate will add /ws/status/{order_id} that pushes
    the same shape over WebSocket instead of requiring polling.
    See: Bap-1/docs/ARCHITECTURE.md §7.4 #11.
    """
    txn_id = request.match_info["txn_id"]
    order_id = request.match_info["order_id"]
    bpp_id = request.query.get("bpp_id")
    bpp_uri = request.query.get("bpp_uri")

    stored = session_store.get(txn_id)
    selected = stored.get("selected") if stored is not None else None
    intent = stored.get("intent") if stored is not None else None
    if (not bpp_id or not bpp_uri) and selected is not None:
        bpp_id = bpp_id or selected.bpp_id
        bpp_uri = bpp_uri or selected.bpp_uri

    if not bpp_id or not bpp_uri:
        raise web.HTTPBadRequest(
            reason="bpp_id and bpp_uri required (not provided and not recoverable from session)"
        )

    # Beckn v2.1 /status inherits Contract's required commitments, so we
    # replay the item list from the session every poll.
    from src.beckn.models import SelectedItem
    items: list[SelectedItem] = []
    if selected is not None:
        items = [SelectedItem(
            id=selected.item_id,
            quantity=intent.quantity if intent else 1,
            name=selected.item_name,
            price_value=selected.price_value,
            price_currency=selected.price_currency,
        )]

    agent = _build_agent(callback_timeout=5.0)
    try:
        resp = await agent.get_status(
            transaction_id=txn_id,
            order_id=order_id,
            bpp_id=bpp_id,
            bpp_uri=bpp_uri,
            items=items,
        )
        return web.json_response({
            "transaction_id": txn_id,
            "order_id": resp.order_id,
            "state": resp.state.value,
            "fulfillment_eta": resp.fulfillment_eta,
            "tracking_url": resp.tracking_url,
            "observed_at": _now_iso(),
            "status": "live",
        })
    except Exception as exc:
        logger.debug("status failed (%s) — returning mock", exc)
        # Mock progression: if we have a stored order_state, echo it, else CREATED.
        last_state = (stored or {}).get("order_state")
        state_value = last_state.value if last_state else "CREATED"
        return web.json_response({
            "transaction_id": txn_id,
            "order_id": order_id,
            "state": state_value,
            "fulfillment_eta": None,
            "tracking_url": None,
            "observed_at": _now_iso(),
            "status": "mock",
        })


# ── App wiring ────────────────────────────────────────────────────────────────


async def _on_startup(app: web.Application) -> None:
    await session_store.start_sweeper()


async def _on_cleanup(app: web.Application) -> None:
    await session_store.stop_sweeper()


def create_app() -> web.Application:
    app = web.Application()
    app.router.add_get("/health",                                   health)
    app.router.add_post("/parse",                                   parse)
    app.router.add_post("/compare",                                 compare)
    app.router.add_post("/commit",                                  commit)
    app.router.add_get("/status/{txn_id}/{order_id}",               status)
    app.router.add_post("/bap/receiver/{action}",                   bap_receiver)
    app.router.add_post("/bpp/discover",                            bpp_discover)
    app.router.add_post("/{action}",                                bap_receiver)
    app.on_startup.append(_on_startup)
    app.on_cleanup.append(_on_cleanup)
    return app


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    app = create_app()
    web.run_app(app, host="0.0.0.0", port=8000)
