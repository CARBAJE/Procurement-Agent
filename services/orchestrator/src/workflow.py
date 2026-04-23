"""Step Functions local simulator — orchestrates the 4-step procurement pipeline.

State machine:
  Step 1 — Intention Parser  (POST /parse)
  Step 2 — Beckn BAP Client  (POST /discover)
  Step 3 — Comparative Score (POST /score)
  Step 4 — Beckn BAP Client  (POST /select)

Exposes:
  POST /run  { "query": "..." }
  GET  /health

Service URLs are read from env vars so the orchestrator works both in Docker
(service names) and locally (localhost + ports).
"""
from __future__ import annotations

import json
import logging
import os

import aiohttp
from aiohttp import web

logger = logging.getLogger(__name__)

# ── Service URLs (set via env vars in docker-compose) ─────────────────────────

INTENTION_PARSER_URL     = os.getenv("INTENTION_PARSER_URL",     "http://localhost:8001")
BECKN_BAP_URL            = os.getenv("BECKN_BAP_URL",            "http://localhost:8002")
COMPARATIVE_SCORING_URL  = os.getenv("COMPARATIVE_SCORING_URL",  "http://localhost:8003")


# ── Pipeline ──────────────────────────────────────────────────────────────────


async def _post(session: aiohttp.ClientSession, url: str, body: dict) -> dict:
    """POST JSON to a service and return the parsed response dict."""
    async with session.post(url, json=body) as resp:
        resp.raise_for_status()
        return await resp.json()


async def run_pipeline_from_intent(beckn_intent: dict) -> dict:
    """Execute Steps 2→3→4 of the state machine with a pre-parsed BecknIntent.

    Used by POST /discover (frontend-compatible endpoint) when the NL parse
    step has already happened and the user has confirmed the intent preview.

    Returns the same shape as run_pipeline() but without parse_result.
    """
    messages: list[str] = []

    async with aiohttp.ClientSession(
        headers={"Content-Type": "application/json"}
    ) as session:

        # ── Step 2: Beckn BAP Client Lambda (discover) ───────────────────────
        logger.info("Step 2 — Beckn BAP Client /discover (from pre-parsed intent)")
        discover_result = await _post(
            session, f"{BECKN_BAP_URL}/discover", beckn_intent
        )
        transaction_id = discover_result.get("transaction_id", "")
        offerings = discover_result.get("offerings", [])
        messages.append(
            f"[beckn-bap-client] txn={transaction_id} "
            f"found {len(offerings)} offering(s)"
        )

        if not offerings:
            return {
                "transaction_id": transaction_id,
                "offerings": [],
                "selected": None,
                "messages": messages,
                "status": "live",
            }

        # ── Step 3: Comparative & Scoring Lambda ─────────────────────────────
        logger.info("Step 3 — Comparative Scoring /score")
        score_result = await _post(
            session, f"{COMPARATIVE_SCORING_URL}/score", {"offerings": offerings}
        )
        selected = score_result.get("selected")
        if selected:
            messages.append(
                f"[comparative-scoring] selected {selected.get('provider_name')!r} "
                f"₹{selected.get('price_value')} (cheapest of {len(offerings)})"
            )
        else:
            messages.append("[comparative-scoring] no offering selected")

        if not selected:
            return {
                "transaction_id": transaction_id,
                "offerings": offerings,
                "selected": None,
                "messages": messages,
                "status": "live",
            }

        # ── Step 4: Beckn BAP Client Lambda (select) ─────────────────────────
        logger.info("Step 4 — Beckn BAP Client /select")
        select_body = {
            "transaction_id": transaction_id,
            "bpp_id":         selected.get("bpp_id", ""),
            "bpp_uri":        selected.get("bpp_uri", ""),
            "item_id":        selected.get("item_id", ""),
            "item_name":      selected.get("item_name", ""),
            "provider_id":    selected.get("provider_id", ""),
            "price_value":    selected.get("price_value", "0"),
            "price_currency": selected.get("price_currency", "INR"),
            "quantity":       beckn_intent.get("quantity", 1),
        }
        select_result = await _post(session, f"{BECKN_BAP_URL}/select", select_body)
        ack_status = select_result.get("ack", "UNKNOWN")
        messages.append(
            f"[beckn-bap-client/select] ACK={ack_status} "
            f"bpp={selected.get('bpp_id')} provider={selected.get('provider_name')}"
        )

        qty = beckn_intent.get("quantity", "?")
        summary = (
            f"Order initiated — {selected.get('provider_name')} | "
            f"{selected.get('item_name')} × {qty} | "
            f"₹{selected.get('price_value')} {selected.get('price_currency')} | "
            f"txn={transaction_id}"
        )
        messages.append(f"[orchestrator] {summary}")

        return {
            "transaction_id": transaction_id,
            "offerings":      offerings,
            "selected":       selected,
            "messages":       messages,
            "status":         "live",
        }


async def run_pipeline(query: str) -> dict:
    """Execute the 4-step Step Functions state machine.

    Returns a dict with keys:
      parse_result, discover_result, score_result, select_result, messages
    """
    messages: list[str] = []

    async with aiohttp.ClientSession(
        headers={"Content-Type": "application/json"}
    ) as session:

        # ── Step 1: Intention Parser Lambda ──────────────────────────────────
        logger.info("Step 1 — Intention Parser")
        parse_result = await _post(
            session, f"{INTENTION_PARSER_URL}/parse", {"query": query}
        )
        messages.append(
            f"[intention-parser] intent={parse_result.get('intent')} "
            f"confidence={parse_result.get('confidence')} "
            f"routed_to={parse_result.get('routed_to')}"
        )

        if parse_result.get("intent") != "procurement":
            return {
                "error": f"Query not recognised as procurement: {query!r}",
                "messages": messages,
                "parse_result": parse_result,
            }

        beckn_intent = parse_result.get("beckn_intent")
        if not beckn_intent:
            return {
                "error": "Intent parser returned no beckn_intent",
                "messages": messages,
                "parse_result": parse_result,
            }

        # ── Step 2: Beckn BAP Client Lambda (discover) ───────────────────────
        logger.info("Step 2 — Beckn BAP Client /discover")
        discover_result = await _post(
            session, f"{BECKN_BAP_URL}/discover", beckn_intent
        )
        transaction_id = discover_result.get("transaction_id", "")
        offerings = discover_result.get("offerings", [])
        messages.append(
            f"[beckn-bap-client] txn={transaction_id} "
            f"found {len(offerings)} offering(s)"
        )

        if not offerings:
            return {
                "transaction_id": transaction_id,
                "offerings": [],
                "selected": None,
                "messages": messages,
                "parse_result": parse_result,
                "discover_result": discover_result,
            }

        # ── Step 3: Comparative & Scoring Lambda ─────────────────────────────
        logger.info("Step 3 — Comparative Scoring /score")
        score_result = await _post(
            session, f"{COMPARATIVE_SCORING_URL}/score", {"offerings": offerings}
        )
        selected = score_result.get("selected")
        if selected:
            messages.append(
                f"[comparative-scoring] selected {selected.get('provider_name')!r} "
                f"₹{selected.get('price_value')} (cheapest of {len(offerings)})"
            )
        else:
            messages.append("[comparative-scoring] no offering selected")

        if not selected:
            return {
                "transaction_id": transaction_id,
                "offerings": offerings,
                "selected": None,
                "messages": messages,
                "parse_result": parse_result,
                "discover_result": discover_result,
                "score_result": score_result,
            }

        # ── Step 4: Beckn BAP Client Lambda (select) ─────────────────────────
        logger.info("Step 4 — Beckn BAP Client /select")
        select_body = {
            "transaction_id": transaction_id,
            "bpp_id":         selected.get("bpp_id", ""),
            "bpp_uri":        selected.get("bpp_uri", ""),
            "item_id":        selected.get("item_id", ""),
            "item_name":      selected.get("item_name", ""),
            "provider_id":    selected.get("provider_id", ""),
            "price_value":    selected.get("price_value", "0"),
            "price_currency": selected.get("price_currency", "INR"),
            "quantity":       beckn_intent.get("quantity", 1),
        }
        select_result = await _post(session, f"{BECKN_BAP_URL}/select", select_body)
        ack_status = select_result.get("ack", "UNKNOWN")
        messages.append(
            f"[beckn-bap-client/select] ACK={ack_status} "
            f"bpp={selected.get('bpp_id')} provider={selected.get('provider_name')}"
        )

        # ── Final summary ─────────────────────────────────────────────────────
        qty = beckn_intent.get("quantity", "?")
        summary = (
            f"Order initiated — {selected.get('provider_name')} | "
            f"{selected.get('item_name')} × {qty} | "
            f"₹{selected.get('price_value')} {selected.get('price_currency')} | "
            f"txn={transaction_id}"
        )
        messages.append(f"[orchestrator] {summary}")

        return {
            "transaction_id": transaction_id,
            "offerings":      offerings,
            "selected":       selected,
            "messages":       messages,
            "parse_result":   parse_result,
            "discover_result": discover_result,
            "score_result":   score_result,
            "select_result":  select_result,
        }


# ── HTTP handlers ─────────────────────────────────────────────────────────────


async def health(request: web.Request) -> web.Response:
    return web.json_response({
        "status": "ok",
        "service": "orchestrator",
        "upstream": {
            "intention_parser":    INTENTION_PARSER_URL,
            "beckn_bap_client":    BECKN_BAP_URL,
            "comparative_scoring": COMPARATIVE_SCORING_URL,
        },
    })


async def discover(request: web.Request) -> web.Response:
    """POST /discover — frontend-compatible endpoint (Steps 2→3→4 only).

    Accepts a pre-parsed BecknIntent body (same format as the confirmed intent
    from the frontend's Step 2). Skips the NL parsing step.

    This endpoint mirrors the Bap-1 monolith's POST /discover so the frontend
    only needs to change BAP_URL from port 8000 to port 8004.

    Body:    BecknIntent fields (item, quantity, location_coordinates, …)
    Returns: { transaction_id, offerings, selected, messages, status }
    """
    try:
        beckn_intent = await request.json()
    except json.JSONDecodeError:
        raise web.HTTPBadRequest(reason="Invalid JSON")

    if not beckn_intent.get("item"):
        raise web.HTTPBadRequest(reason="item is required in BecknIntent body")

    try:
        result = await run_pipeline_from_intent(beckn_intent)
    except aiohttp.ClientError as exc:
        logger.error("Service call failed: %s", exc)
        raise web.HTTPBadGateway(reason=f"Upstream service unavailable: {exc}")
    except Exception as exc:
        logger.error("Pipeline error: %s", exc)
        raise web.HTTPInternalServerError(reason=f"Pipeline failed: {exc}")

    return web.json_response(result)


async def run(request: web.Request) -> web.Response:
    """POST /run  { "query": "..." } — execute full procurement pipeline."""
    try:
        body = await request.json()
    except json.JSONDecodeError:
        raise web.HTTPBadRequest(reason="Invalid JSON")

    query = body.get("query", "").strip()
    if not query:
        raise web.HTTPBadRequest(reason="query is required")

    try:
        result = await run_pipeline(query)
    except aiohttp.ClientError as exc:
        logger.error("Service call failed: %s", exc)
        raise web.HTTPBadGateway(reason=f"Upstream service unavailable: {exc}")
    except Exception as exc:
        logger.error("Pipeline error: %s", exc)
        raise web.HTTPInternalServerError(reason=f"Pipeline failed: {exc}")

    return web.json_response(result)


# ── App factory ───────────────────────────────────────────────────────────────


def create_app() -> web.Application:
    app = web.Application()
    app.router.add_get("/health",    health)
    app.router.add_post("/run",      run)       # CLI / full pipeline (takes raw query)
    app.router.add_post("/discover", discover)  # frontend-compatible (takes BecknIntent)
    return app


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    port = int(os.getenv("PORT", "8004"))
    web.run_app(create_app(), host="0.0.0.0", port=port)
