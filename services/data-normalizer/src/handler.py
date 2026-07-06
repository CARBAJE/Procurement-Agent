"""Data Normalizer — thin aiohttp wrapper (port 8006).

Routes:
    GET  /health
    POST /normalize/request
    POST /normalize/intent
    POST /normalize/discovery
    POST /normalize/scoring
    POST /normalize/order
    PATCH /normalize/status
    POST /normalize/memory/write
    POST /normalize/memory/search
"""
from __future__ import annotations

import json
import logging
import os
import uuid as _uuid

from aiohttp import web

from DataNormalizer import DataNormalizer
from DataNormalizer.db import close_pool, get_pool
from DataNormalizer.repositories import approval_repo, user_repo

# Absolute import (no leading dot): handler.py is launched as a script in
# Docker (`python src/handler.py`), so `src` is not a package there. Tests
# import as `from src.handler import create_app` after adding the service
# root to sys.path — `src.error_middleware` resolves as a namespace package
# in that context.
try:
    from src.error_middleware import db_error_middleware
except ModuleNotFoundError:
    # Docker entrypoint adds `src/` to sys.path automatically.
    from error_middleware import db_error_middleware  # type: ignore

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
        actor=body.get("actor"),
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
        fulfillment_eta=body.get("fulfillment_eta"),
    )
    return web.json_response(result, status=201)


# ── GET /order/{request_id} ─────────────────────────────────────────────────────

async def get_order(request: web.Request) -> web.Response:
    """GET /order/{request_id}
    Returns the full order detail DTO {request, intent, order} reconstructed
    from the DB. 404 when request_id is unknown; 200 with order=null when the
    request exists but no purchase_order was persisted.
    """
    request_id = request.match_info["request_id"]
    try:
        _uuid.UUID(request_id)
    except (ValueError, AttributeError, TypeError):
        raise web.HTTPNotFound(reason="request_id is not a valid UUID")
    detail = await _normalizer.get_order_detail(request_id)
    if detail is None:
        raise web.HTTPNotFound(reason="No order found for that request_id")
    return web.json_response(detail)


# ── /normalize/audit ──────────────────────────────────────────────────────────

async def normalize_audit(request: web.Request) -> web.Response:
    """POST /normalize/audit
    Body: {event_type, agent_action, reasoning_payload?, request_id?, po_id?,
           actor_id?, kafka_offset?}
    Returns: {event_id}

    event_type must be one of: discover, normalize, score, negotiate, approve,
    confirm, override, erp_sync, notification.
    """
    try:
        body = await request.json()
    except json.JSONDecodeError:
        raise web.HTTPBadRequest(reason="Invalid JSON")

    for field in ("event_type", "agent_action"):
        if not body.get(field):
            raise web.HTTPBadRequest(reason=f"{field} is required")

    try:
        result = await _normalizer.normalize_audit(
            event_type=body["event_type"],
            agent_action=body["agent_action"],
            reasoning_payload=body.get("reasoning_payload") or {},
            request_id=body.get("request_id"),
            po_id=body.get("po_id"),
            actor_id=body.get("actor_id"),
            kafka_offset=int(body.get("kafka_offset", 0)),
        )
    except ValueError as exc:
        raise web.HTTPBadRequest(reason=str(exc))
    return web.json_response(result, status=201)


# ── GET /normalize/audit ─────────────────────────────────────────────────────

async def get_audit_event(request: web.Request) -> web.Response:
    """GET /normalize/audit/{event_id}
    Returns a single audit event or 404 when event_id is unknown.
    """
    event_id = request.match_info["event_id"]
    try:
        _uuid.UUID(event_id)
    except (ValueError, AttributeError):
        raise web.HTTPBadRequest(reason="event_id is not a valid UUID")
    event = await _normalizer.get_audit_event(event_id)
    if event is None:
        raise web.HTTPNotFound(reason="Audit event not found")
    return web.json_response(event)


async def list_audit_events(request: web.Request) -> web.Response:
    """GET /normalize/audit?request_id=X&limit=N  or  ?po_id=X&limit=N
    Returns {"count": int, "events": [...]} ordered by event_timestamp ASC.
    At least one of request_id or po_id is required; limit defaults to 100 (max 500).
    """
    params = request.rel_url.query
    try:
        limit = min(int(params.get("limit", 100)), 500)
    except ValueError:
        raise web.HTTPBadRequest(reason="limit must be an integer")

    if "request_id" in params:
        try:
            _uuid.UUID(params["request_id"])
        except ValueError:
            raise web.HTTPBadRequest(reason="request_id is not a valid UUID")
        events = await _normalizer.get_audit_events_by_request(params["request_id"], limit)
    elif "po_id" in params:
        try:
            _uuid.UUID(params["po_id"])
        except ValueError:
            raise web.HTTPBadRequest(reason="po_id is not a valid UUID")
        events = await _normalizer.get_audit_events_by_po(params["po_id"], limit)
    else:
        raise web.HTTPBadRequest(reason="request_id or po_id query parameter is required")

    return web.json_response({"count": len(events), "events": events})


# ── PATCH /normalize/po_status ────────────────────────────────────────────────

async def normalize_po_status(request: web.Request) -> web.Response:
    """PATCH /normalize/po_status
    Body: {beckn_confirm_ref, state}
    Returns: {po_id, status}  — po_id is None if no row matched.

    state must be one of: pending, confirmed, shipped, delivered, cancelled.
    """
    try:
        body = await request.json()
    except json.JSONDecodeError:
        raise web.HTTPBadRequest(reason="Invalid JSON")

    for field in ("beckn_confirm_ref", "state"):
        if not body.get(field):
            raise web.HTTPBadRequest(reason=f"{field} is required")

    try:
        result = await _normalizer.normalize_po_status(
            beckn_confirm_ref=body["beckn_confirm_ref"],
            state=body["state"],
        )
    except ValueError as exc:
        raise web.HTTPBadRequest(reason=str(exc))
    return web.json_response(result)


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
        category=body.get("category"),
    )
    return web.json_response(result)


# ── Admin users ───────────────────────────────────────────────────────────────

async def list_users(request: web.Request) -> web.Response:
    """GET /admin/users — return all users."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT user_id::text, email, name, role::text, department,
                   approval_threshold::float, keycloak_id,
                   idp_provider::text, created_at::text
            FROM users
            ORDER BY name
            """
        )
    return web.json_response([dict(r) for r in rows])


async def update_user(request: web.Request) -> web.Response:
    """PATCH /admin/users/{user_id} — update approval_threshold and/or department.

    Role is not updatable here — Keycloak is the source of truth and overwrites
    the DB value on every login via user_repo.resolve_user().
    """
    user_id_str = request.match_info["user_id"]
    try:
        body = await request.json()
    except json.JSONDecodeError:
        raise web.HTTPBadRequest(reason="Invalid JSON")

    new_threshold = body.get("approval_threshold")
    new_department = body.get("department")

    if new_threshold is not None:
        try:
            new_threshold = float(new_threshold)
            if new_threshold < 0:
                raise ValueError
        except (ValueError, TypeError):
            raise web.HTTPBadRequest(reason="approval_threshold must be a non-negative number")

    pool = await get_pool()
    async with pool.acquire() as conn:
        user_uuid = _uuid.UUID(user_id_str)
        if new_threshold is not None:
            await conn.execute(
                "UPDATE users SET approval_threshold = $1 WHERE user_id = $2",
                new_threshold, user_uuid,
            )
        if new_department is not None:
            await conn.execute(
                "UPDATE users SET department = $1 WHERE user_id = $2",
                new_department, user_uuid,
            )
        row = await conn.fetchrow(
            """
            SELECT user_id::text, email, name, role::text, department,
                   approval_threshold::float, keycloak_id,
                   idp_provider::text, created_at::text
            FROM users WHERE user_id = $1
            """,
            user_uuid,
        )
    if not row:
        raise web.HTTPNotFound(reason=f"User {user_id_str!r} not found")
    return web.json_response(dict(row))


# ── Approvals ─────────────────────────────────────────────────────────────────

async def list_approvals(request: web.Request) -> web.Response:
    """GET /approvals — list procurement_requests in pending_approval status."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT
                pr.request_id::text,
                pr.pending_transaction_id,
                pr.pending_chosen_item_id,
                pr.raw_input_text   AS item_description,
                pr.created_at::text,
                u.name              AS requester_name,
                u.email             AS requester_email,
                u.department        AS requester_department
            FROM procurement_requests pr
            LEFT JOIN users u ON u.user_id = pr.requester_id
            WHERE pr.status = 'pending_approval'
            ORDER BY pr.created_at
            """
        )
    return web.json_response([dict(r) for r in rows])


async def decide_approval(request: web.Request) -> web.Response:
    """POST /approvals/{request_id}/decide
    Body: { decision: "approved" | "rejected" }
    """
    request_id = request.match_info["request_id"]
    try:
        body = await request.json()
    except json.JSONDecodeError:
        raise web.HTTPBadRequest(reason="Invalid JSON")

    decision = body.get("decision")
    if decision not in ("approved", "rejected"):
        raise web.HTTPBadRequest(reason="decision must be 'approved' or 'rejected'")

    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT request_id FROM procurement_requests WHERE request_id = $1 AND status = 'pending_approval'",
            _uuid.UUID(request_id),
        )
        if not row:
            raise web.HTTPNotFound(reason=f"Pending approval {request_id!r} not found")
        await approval_repo.mark_decided(conn, request_id, decision)

    return web.json_response({"request_id": request_id, "decision": decision})


# ── /normalize/memory/write ──────────────────────────────────────────────────

async def normalize_memory_write(request: web.Request) -> web.Response:
    """POST /normalize/memory/write
    Body: {item_text, provider_name, price, currency, delivery_hours, request_id?}
    Returns: {stored: true}

    Embeds a confirmed transaction and inserts into agent_memory_vectors.
    Never returns an error — silently skips on embedding or DB failure.
    """
    try:
        body = await request.json()
    except json.JSONDecodeError:
        raise web.HTTPBadRequest(reason="Invalid JSON")

    item_text = (body.get("item_text") or "").strip()
    if not item_text:
        raise web.HTTPBadRequest(reason="item_text is required")

    result = await _normalizer.write_memory(
        item_text=item_text,
        provider_name=body.get("provider_name", "unknown"),
        price=float(body.get("price", 0.0)),
        currency=body.get("currency", "INR"),
        delivery_hours=int(body.get("delivery_hours", 24)),
        request_id=body.get("request_id"),
    )
    return web.json_response(result, status=201)


# ── /normalize/memory/search ──────────────────────────────────────────────────

async def normalize_memory_search(request: web.Request) -> web.Response:
    """POST /normalize/memory/search
    Body: {item_text, limit?}
    Returns: {results: [...], count: int}

    ANN search for past transactions semantically similar to item_text.
    Returns empty results on any failure.
    """
    try:
        body = await request.json()
    except json.JSONDecodeError:
        raise web.HTTPBadRequest(reason="Invalid JSON")

    item_text = (body.get("item_text") or "").strip()
    if not item_text:
        raise web.HTTPBadRequest(reason="item_text is required")

    result = await _normalizer.search_memory(
        item_text=item_text,
        limit=int(body.get("limit", 3)),
    )
    return web.json_response(result)


# ── App factory ───────────────────────────────────────────────────────────────

async def _on_shutdown(app: web.Application) -> None:
    await close_pool()


def create_app() -> web.Application:
    app = web.Application(middlewares=[db_error_middleware])
    app.router.add_get("/health",               health)
    app.router.add_post("/normalize/request",   normalize_request)
    app.router.add_post("/normalize/intent",    normalize_intent)
    app.router.add_post("/normalize/discovery", normalize_discovery)
    app.router.add_post("/normalize/scoring",   normalize_scoring)
    app.router.add_post("/normalize/order",     normalize_order)
    app.router.add_get("/order/{request_id}",   get_order)
    app.router.add_post("/normalize/audit",               normalize_audit)
    app.router.add_get("/normalize/audit/{event_id}",     get_audit_event)
    app.router.add_get("/normalize/audit",                list_audit_events)
    app.router.add_route("PATCH", "/normalize/status",    normalize_status)
    app.router.add_route("PATCH", "/normalize/po_status", normalize_po_status)
    app.router.add_get("/admin/users",                       list_users)
    app.router.add_route("PATCH", "/admin/users/{user_id}",  update_user)
    app.router.add_get("/approvals",                         list_approvals)
    app.router.add_post("/approvals/{request_id}/decide",    decide_approval)
    app.router.add_post("/normalize/memory/write",           normalize_memory_write)
    app.router.add_post("/normalize/memory/search",          normalize_memory_search)
    app.on_shutdown.append(_on_shutdown)
    return app


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    port = int(os.getenv("PORT", "8006"))
    web.run_app(create_app(), host="0.0.0.0", port=port)
