"""Bearer-token middleware for internal /api/v1/* routes.

This is the first auth gate anywhere in the active services. It is intentionally
narrow: it protects only the adapter's internal surface (BAP → adapter calls).
Public endpoints — /healthz, /readyz, /metrics, /api/v1/webhooks/* — are
explicitly exempt (the webhooks use their own HMAC verification).

When Keycloak ships, swap the constant-time bearer compare for JWT verification
without touching any route.
"""
from __future__ import annotations

import hmac
import logging
from typing import Awaitable, Callable

from aiohttp import web

logger = logging.getLogger(__name__)

_PROTECTED_PREFIX = "/api/v1/"
_EXEMPT_PREFIXES = ("/api/v1/webhooks/",)


def make_auth_middleware(expected_token: str) -> Callable:
    """Build an aiohttp middleware that requires Bearer <expected_token> on
    protected routes. Exempt paths: anything under /api/v1/webhooks/, plus
    everything outside /api/v1/ (e.g. /healthz, /metrics).
    """

    @web.middleware
    async def _mw(request: web.Request, handler: Callable[[web.Request], Awaitable[web.StreamResponse]]):
        path = request.path
        if not path.startswith(_PROTECTED_PREFIX) or any(path.startswith(p) for p in _EXEMPT_PREFIXES):
            return await handler(request)

        header = request.headers.get("Authorization", "")
        if not header.startswith("Bearer "):
            return web.json_response({"error": "missing_bearer"}, status=401)

        token = header[len("Bearer "):]
        if not hmac.compare_digest(token, expected_token):
            logger.warning("auth.reject path=%s remote=%s", path, request.remote)
            return web.json_response({"error": "invalid_token"}, status=401)

        return await handler(request)

    return _mw
