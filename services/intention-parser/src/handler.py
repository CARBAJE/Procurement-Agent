"""Lambda 1 — Intention Parser microservice.

Thin aiohttp wrapper around IntentParser.parse_request().
IntentParser/ is mounted at /app/IntentParser via Docker volume.

POST /parse  { "query": "500 A4 paper Bangalore 3 days" }
→ { "intent", "confidence", "beckn_intent", "routed_to" }
"""
from __future__ import annotations

import json
import logging
import os
import sys

# IntentParser/ and shared/ are mounted as volumes at /app/
sys.path.insert(0, "/app")

from aiohttp import web

logger = logging.getLogger(__name__)

_PROCUREMENT_INTENTS = {"SearchProduct", "RequestQuote", "PurchaseOrder"}


async def health(request: web.Request) -> web.Response:
    return web.json_response({"status": "ok", "service": "intention-parser"})


async def parse(request: web.Request) -> web.Response:
    """POST /parse — NL query → ParseResult JSON."""
    try:
        body = await request.json()
    except json.JSONDecodeError:
        raise web.HTTPBadRequest(reason="Invalid JSON")

    query = body.get("query", "").strip()
    if not query:
        raise web.HTTPBadRequest(reason="query is required")

    try:
        from IntentParser import parse_request  # type: ignore[import]
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
        safe_reason = str(exc).replace("\r", " ").replace("\n", " ")[:200]
        raise web.HTTPInternalServerError(
            reason=f"Intent parsing failed: {safe_reason}",
            text=json.dumps({"detail": f"Intent parsing failed: {safe_reason}"}),
            content_type="application/json",
        )


def create_app() -> web.Application:
    app = web.Application()
    app.router.add_get("/health", health)
    app.router.add_post("/parse",  parse)
    return app


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    port = int(os.getenv("PORT", "8001"))
    web.run_app(create_app(), host="0.0.0.0", port=port)
