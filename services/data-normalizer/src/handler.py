"""Data Normalizer — thin aiohttp wrapper (port 8006).

Routes:
    GET  /health
    POST /normalize/request
    POST /normalize/intent
    POST /normalize/discovery
    POST /normalize/scoring
    POST /normalize/order
    PATCH /normalize/status
"""
from __future__ import annotations

import json
import logging
import os

from aiohttp import web

from DataNormalizer import DataNormalizer
from DataNormalizer.db import close_pool

logger = logging.getLogger(__name__)

_normalizer = DataNormalizer()


# ── health ────────────────────────────────────────────────────────────────────

async def health(request: web.Request) -> web.Response:
    return web.json_response({"status": "ok", "service": "data-normalizer"})


# ── /normalize/request ────────────────────────────────────────────────────────

async def normalize_request(request: web.Request) -> web.Response:
    """POST /normalize/request
    Body: {raw_input_text, channel?, requester_id?}
    Returns: {request_id}
    """
    try:
        body = await request.json()
    except json.JSONDecodeError:
        raise web.HTTPBadRequest(reason="Invalid JSON")

    raw = body.get("raw_input_text", "").strip()
    if not raw:
        raise web.HTTPBadRequest(reason="raw_input_text is required")

    result = await _normalizer.normalize_request(
        raw_input_text=raw,
        channel=body.get("channel", "web"),
        requester_id=body.get("requester_id"),
    )
    return web.json_response(result, status=201)


# ── /normalize/intent ─────────────────────────────────────────────────────────

async def normalize_intent(request: web.Request) -> web.Response:
    """POST /normalize/intent
    Body: {request_id, intent_class, confidence, model_version, beckn_intent}
    Returns: {intent_id, beckn_intent_id}
    """
    try:
        body = await request.json()
    except json.JSONDecodeError:
        raise web.HTTPBadRequest(reason="Invalid JSON")

    for field in ("request_id", "beckn_intent"):
        if not body.get(field):
            raise web.HTTPBadRequest(reason=f"{field} is required")

    result = await _normalizer.normalize_intent(
        request_id=body["request_id"],
        intent_class=body.get("intent_class", "procurement"),
        confidence=float(body.get("confidence", 1.0)),
        model_version=body.get("model_version", "1.0"),
        beckn_intent=body["beckn_intent"],
    )
    return web.json_response(result, status=201)


# ── /normalize/discovery ──────────────────────────────────────────────────────

async def normalize_discovery(request: web.Request) -> web.Response:
    """POST /normalize/discovery
    Body: {beckn_intent_id, network_id?, offerings: [...]}
    Returns: {query_id, offering_ids: [...]}
    """
    try:
        body = await request.json()
    except json.JSONDecodeError:
        raise web.HTTPBadRequest(reason="Invalid JSON")

    if not body.get("beckn_intent_id"):
        raise web.HTTPBadRequest(reason="beckn_intent_id is required")

    result = await _normalizer.normalize_discovery(
        beckn_intent_id=body["beckn_intent_id"],
        network_id=body.get("network_id", "beckn-default"),
        offerings=body.get("offerings", []),
    )
    return web.json_response(result, status=201)


# ── /normalize/scoring ────────────────────────────────────────────────────────

async def normalize_scoring(request: web.Request) -> web.Response:
    """POST /normalize/scoring
    Body: {query_id, scores: [{offering_id, rank, composite_score, ...}]}
    Returns: {score_ids: [{offering_id, score_id}]}
    """
    try:
        body = await request.json()
    except json.JSONDecodeError:
        raise web.HTTPBadRequest(reason="Invalid JSON")

    if not body.get("query_id"):
        raise web.HTTPBadRequest(reason="query_id is required")

    result = await _normalizer.normalize_scoring(
        query_id=body["query_id"],
        scores=body.get("scores", []),
    )
    return web.json_response(result, status=201)


# ── /normalize/order ──────────────────────────────────────────────────────────

async def normalize_order(request: web.Request) -> web.Response:
    """POST /normalize/order
    Body: {score_id, bpp_uri, item_id, quantity, agreed_price,
           beckn_confirm_ref, delivery_terms?, currency?, unit?, network_id?}
    Returns: {po_id}
    """
    try:
        body = await request.json()
    except json.JSONDecodeError:
        raise web.HTTPBadRequest(reason="Invalid JSON")

    for field in ("score_id", "bpp_uri", "item_id", "agreed_price", "beckn_confirm_ref"):
        if not body.get(field):
            raise web.HTTPBadRequest(reason=f"{field} is required")

    result = await _normalizer.normalize_order(
        score_id=body["score_id"],
        bpp_uri=body["bpp_uri"],
        item_id=body["item_id"],
        quantity=int(body.get("quantity", 1)),
        agreed_price=float(body["agreed_price"]),
        beckn_confirm_ref=body["beckn_confirm_ref"],
        delivery_terms=body.get("delivery_terms", "Standard delivery"),
        currency=body.get("currency", "INR"),
        unit=body.get("unit", "units"),
        network_id=body.get("network_id", "beckn-default"),
        requester_id=body.get("requester_id"),
    )
    return web.json_response(result, status=201)


# ── PATCH /normalize/status ───────────────────────────────────────────────────

async def normalize_status(request: web.Request) -> web.Response:
    """PATCH /normalize/status
    Body: {request_id, status}
    Returns: {request_id, status}
    """
    try:
        body = await request.json()
    except json.JSONDecodeError:
        raise web.HTTPBadRequest(reason="Invalid JSON")

    for field in ("request_id", "status"):
        if not body.get(field):
            raise web.HTTPBadRequest(reason=f"{field} is required")

    result = await _normalizer.update_status(
        request_id=body["request_id"],
        status=body["status"],
    )
    return web.json_response(result)


# ── App factory ───────────────────────────────────────────────────────────────

async def _on_shutdown(app: web.Application) -> None:
    await close_pool()


def create_app() -> web.Application:
    app = web.Application()
    app.router.add_get("/health",               health)
    app.router.add_post("/normalize/request",   normalize_request)
    app.router.add_post("/normalize/intent",    normalize_intent)
    app.router.add_post("/normalize/discovery", normalize_discovery)
    app.router.add_post("/normalize/scoring",   normalize_scoring)
    app.router.add_post("/normalize/order",     normalize_order)
    app.router.add_route("PATCH", "/normalize/status", normalize_status)
    app.on_shutdown.append(_on_shutdown)
    return app


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    port = int(os.getenv("PORT", "8006"))
    web.run_app(create_app(), host="0.0.0.0", port=port)
