"""catalog-normalizer microservice — aiohttp on port 8005.

Routes:
  POST /normalize   {payload: dict, bpp_id: str, bpp_uri: str}
                    → {offerings: [DiscoverOffering]}
  GET  /health      → {"status": "ok", "service": "catalog-normalizer"}
"""
from __future__ import annotations

import json
import logging
import os
import sys

sys.path.insert(0, "/app")

from aiohttp import web

from src.normalizer import CatalogNormalizer

logger = logging.getLogger(__name__)

_normalizer = CatalogNormalizer()


async def health(request: web.Request) -> web.Response:
    return web.json_response({"status": "ok", "service": "catalog-normalizer"})


async def normalize(request: web.Request) -> web.Response:
    """POST /normalize — normalize a raw catalog payload."""
    try:
        body = await request.json()
    except json.JSONDecodeError:
        raise web.HTTPBadRequest(reason="Invalid JSON")

    payload = body.get("payload")
    bpp_id = body.get("bpp_id", "")
    bpp_uri = body.get("bpp_uri", "")

    if payload is None:
        raise web.HTTPBadRequest(reason="'payload' field is required")

    try:
        offerings = _normalizer.normalize(payload, bpp_id, bpp_uri)
        return web.json_response({"offerings": [o.model_dump() for o in offerings]})
    except Exception as exc:
        logger.error("Normalization failed: %s", exc)
        raise web.HTTPInternalServerError(reason=f"Normalization failed: {exc}")


def create_app() -> web.Application:
    app = web.Application()
    app.router.add_get("/health", health)
    app.router.add_post("/normalize", normalize)
    return app


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    port = int(os.getenv("PORT", "8005"))
    web.run_app(create_app(), host="0.0.0.0", port=port)
