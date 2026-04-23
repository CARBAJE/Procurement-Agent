"""Lambda 3 — Comparative & Scoring microservice.

Extracts rank_and_select logic from Bap-1/src/agent/nodes.py.

POST /score  { "offerings": [DiscoverOffering...] }
→ { "selected": DiscoverOffering } | { "selected": null }

Phase 1: cheapest price wins.
"""
from __future__ import annotations

import json
import logging
import os

from aiohttp import web

logger = logging.getLogger(__name__)


async def health(request: web.Request) -> web.Response:
    return web.json_response({"status": "ok", "service": "comparative-scoring"})


async def score(request: web.Request) -> web.Response:
    """POST /score — rank offerings and return the best one."""
    try:
        body = await request.json()
    except json.JSONDecodeError:
        raise web.HTTPBadRequest(reason="Invalid JSON")

    offerings: list[dict] = body.get("offerings", [])

    if not offerings:
        return web.json_response({"selected": None})

    try:
        selected = min(offerings, key=lambda o: float(o["price_value"]))
    except (KeyError, ValueError, TypeError) as exc:
        raise web.HTTPUnprocessableEntity(
            reason=f"Invalid offering data — price_value must be numeric: {exc}"
        )

    return web.json_response({"selected": selected})


def create_app() -> web.Application:
    app = web.Application()
    app.router.add_get("/health", health)
    app.router.add_post("/score",  score)
    return app


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    port = int(os.getenv("PORT", "8003"))
    web.run_app(create_app(), host="0.0.0.0", port=port)
