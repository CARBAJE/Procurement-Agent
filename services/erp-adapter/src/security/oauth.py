"""OAuth2 client_credentials token cache.

In-memory per-process cache, TTL = expires_in - 60s, refresh single-flighted
via `asyncio.Lock`. Never logs the token value.

Used by SAPS4HanaAdapter and OracleERPCloudAdapter — both vendors run
client_credentials against an IDP today; Oracle Fusion Cloud can also use a
JWT bearer assertion grant, which is a future extension (the cache layer is
agnostic — only the form body differs).
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Optional

from aiohttp import ClientError, ClientSession

from observability import metrics

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _Token:
    """Don't ever expose this directly. __repr__ overridden so it can never
    leak into a log message."""
    value: str
    expires_at_monotonic: float

    def __repr__(self) -> str:  # pragma: no cover — purely a safety guard
        ttl = self.expires_at_monotonic - time.monotonic()
        return f"_Token(expires_in≈{int(ttl)}s)"


class OAuthTokenCache:
    """A single (token_url, client_id) credential pair. Construct one per
    vendor adapter — each vendor will have its own IDP, client_id, and secret.
    """

    def __init__(
        self,
        *,
        vendor: str,
        token_url: str,
        client_id: str,
        client_secret: str,
        http: ClientSession,
        early_refresh_seconds: int = 60,
    ) -> None:
        self._vendor = vendor
        self._token_url = token_url
        self._client_id = client_id
        self._client_secret = client_secret
        self._http = http
        self._early = early_refresh_seconds
        self._cache: Optional[_Token] = None
        self._lock = asyncio.Lock()

    async def get(self) -> str:
        """Return a valid bearer token. Refreshes lazily, single-flighted."""
        now = time.monotonic()
        cached = self._cache
        if cached is not None and cached.expires_at_monotonic > now:
            return cached.value
        async with self._lock:
            # Re-check under the lock (single-flight)
            cached = self._cache
            if cached is not None and cached.expires_at_monotonic > time.monotonic():
                return cached.value
            return await self._refresh()

    async def _refresh(self) -> str:
        body = {
            "grant_type": "client_credentials",
            "client_id": self._client_id,
            "client_secret": self._client_secret,
        }
        try:
            async with self._http.post(
                self._token_url,
                data=body,
                headers={"Accept": "application/json"},
            ) as resp:
                payload = await resp.json(content_type=None)
                if resp.status != 200 or not payload.get("access_token"):
                    metrics.token_refresh_total.labels(vendor=self._vendor, outcome="error").inc()
                    raise RuntimeError(
                        f"oauth token refresh failed status={resp.status} body={payload}"
                    )
        except ClientError as exc:
            metrics.token_refresh_total.labels(vendor=self._vendor, outcome="error").inc()
            raise RuntimeError(f"oauth token network error: {exc}") from exc

        expires_in = int(payload.get("expires_in") or 3600)
        ttl = max(60, expires_in - self._early)
        self._cache = _Token(
            value=payload["access_token"],
            expires_at_monotonic=time.monotonic() + ttl,
        )
        metrics.token_refresh_total.labels(vendor=self._vendor, outcome="ok").inc()
        logger.info("[oauth] %s token refreshed ttl=%ds", self._vendor, ttl)
        return self._cache.value

    def invalidate(self) -> None:
        """Drop the cached token — useful when the vendor returns 401 on a call
        that used a (presumably expired) cached value."""
        self._cache = None
