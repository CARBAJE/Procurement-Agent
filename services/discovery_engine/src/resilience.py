"""Resilience layer — circuit breaker + structured exception translation.

This module owns the **fail-open** posture documented by Subagent 2:
*"if a specific Beckn network is down or times out, catch the exception,
log a structured warning, and continue aggregating results from the
healthy networks."* Every external call goes through
:meth:`ResilienceManager.call`, which:

1. Consults a per-network :class:`CircuitBreaker` — if OPEN, returns a
   ``NetworkStatus.CIRCUIT_OPEN`` result immediately without spending an
   HTTP socket on a known-bad upstream.
2. Wraps the actual network call in ``asyncio.wait_for`` with the
   gateway's configured ``timeout_s`` — a slow network self-terminates
   without dragging the fan-out's wall-clock.
3. Catches every exception type that ``aiohttp`` can raise (and a final
   ``Exception`` catch-all for defence-in-depth) and converts each one
   to a structured :class:`NetworkResult` with a typed
   :class:`NetworkStatus`.

The breaker is purely cooperative — locked with an ``asyncio.Lock``
since all state mutation runs on the single asyncio thread. The lock
is still required to make state transitions atomic with respect to
*concurrent* tasks that may race on the same breaker (multiple fan-out
calls overlapping during a HALF_OPEN probe).
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Awaitable, Callable, Optional

import aiohttp

from .models import CatalogItem, NetworkGateway, NetworkResult, NetworkStatus

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────
# Network caller protocol
# ─────────────────────────────────────────────────────────────────────────

#: Pluggable HTTP function — the resilience layer is HTTP-agnostic.
#: Tests inject a fake that returns canned items or raises;
#: production injects :func:`default_network_caller` below.
NetworkCaller = Callable[
    [NetworkGateway, dict[str, Any], aiohttp.ClientSession],
    Awaitable[list[CatalogItem]],
]


async def default_network_caller(
    gateway: NetworkGateway,
    intent: dict[str, Any],
    session: aiohttp.ClientSession,
) -> list[CatalogItem]:
    """Default Beckn ``/search`` POST + ``/on_search`` catalog parser.

    Raises whatever ``aiohttp`` raises (``ClientResponseError`` for
    HTTP errors, ``ClientConnectionError`` for refused / dropped
    connections, ``ContentTypeError`` for non-JSON responses, etc.) —
    the resilience layer above is responsible for catching and
    translating these into :class:`NetworkResult`.
    """
    url = f"{gateway.base_url.rstrip('/')}/search"
    async with session.post(url, json=intent, headers=gateway.headers) as resp:
        # Raise for 5xx/4xx so the resilience layer can categorise the failure.
        resp.raise_for_status()
        body = await resp.json()
    return _parse_beckn_catalog(body, gateway.name)


def _parse_beckn_catalog(body: Any, network_name: str) -> list[CatalogItem]:
    """Extract :class:`CatalogItem` rows from a Beckn ``/on_search`` envelope.

    Tolerant by design — malformed providers/items are logged at DEBUG
    and skipped rather than failing the whole network's result set.
    """
    items: list[CatalogItem] = []
    message = (body or {}).get("message") if isinstance(body, dict) else None
    catalog = (message or {}).get("catalog") if isinstance(message, dict) else None
    providers = (catalog or {}).get("providers") or []

    for prov in providers:
        if not isinstance(prov, dict):
            continue
        provider_id = str(prov.get("id") or "unknown")
        descriptor = prov.get("descriptor") or {}
        tax_id = descriptor.get("tax_id") or prov.get("tax_id")

        for item in prov.get("items") or []:
            if not isinstance(item, dict):
                continue
            try:
                price_block = item.get("price") or {}
                qty_block = item.get("quantity") or {}
                items.append(
                    CatalogItem(
                        provider_id=provider_id,
                        item_id=str(item.get("id") or "unknown"),
                        name=str(
                            (item.get("descriptor") or {}).get("name")
                            or item.get("name")
                            or "unknown"
                        ),
                        price=float(price_block.get("value") or 0.0),
                        currency=str(price_block.get("currency") or "INR"),
                        delivery_hours=item.get("delivery_hours"),
                        quantity_available=(qty_block.get("available") or {}).get("count"),
                        tax_id=tax_id,
                        location_coordinates=(item.get("location") or {}).get("gps"),
                        raw_payload=item,
                    )
                )
            except Exception as exc:  # noqa: BLE001 - lenient on per-item parse
                logger.debug(
                    "Skipping unparseable item from %s: %s", network_name, exc
                )
    return items


# ─────────────────────────────────────────────────────────────────────────
# Circuit breaker
# ─────────────────────────────────────────────────────────────────────────


class CircuitState(str, Enum):
    """The classic three-state breaker."""

    CLOSED = "closed"        # requests pass through; counting failures
    OPEN = "open"            # fast-fail; awaiting recovery_timeout
    HALF_OPEN = "half_open"  # next request probes the upstream


@dataclass
class CircuitBreaker:
    """Per-network breaker with async-safe state transitions.

    State machine::

        CLOSED ── failure_count >= threshold ──▶ OPEN
        OPEN   ── recovery_timeout elapsed ──▶ HALF_OPEN
        HALF_OPEN ── probe succeeds ──▶ CLOSED
        HALF_OPEN ── probe fails ──▶ OPEN
    """

    failure_threshold: int = 3
    recovery_timeout_s: float = 30.0
    state: CircuitState = CircuitState.CLOSED
    failure_count: int = 0
    opened_at_monotonic: float = 0.0
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False, compare=False)

    async def allow_request(self) -> bool:
        """Return True if the next request may proceed.

        Transitions OPEN → HALF_OPEN when ``recovery_timeout_s`` has
        elapsed; HALF_OPEN allows the probe through.
        """
        async with self._lock:
            if self.state == CircuitState.CLOSED:
                return True
            if self.state == CircuitState.OPEN:
                if (time.monotonic() - self.opened_at_monotonic) >= self.recovery_timeout_s:
                    self.state = CircuitState.HALF_OPEN
                    logger.info("Circuit transitioning OPEN → HALF_OPEN (probe)")
                    return True
                return False
            # HALF_OPEN — let the probe through.
            return True

    async def record_success(self) -> None:
        """Reset on any success (closes a HALF_OPEN circuit)."""
        async with self._lock:
            if self.state != CircuitState.CLOSED:
                logger.info(
                    "Circuit transitioning %s → CLOSED after success", self.state.value
                )
            self.failure_count = 0
            self.state = CircuitState.CLOSED

    async def record_failure(self) -> None:
        """Increment counter; trip to OPEN at threshold or HALF_OPEN failure."""
        async with self._lock:
            self.failure_count += 1
            if self.state == CircuitState.HALF_OPEN:
                self.state = CircuitState.OPEN
                self.opened_at_monotonic = time.monotonic()
                logger.warning(
                    "Circuit HALF_OPEN probe failed — re-tripping to OPEN"
                )
                return
            if self.failure_count >= self.failure_threshold:
                self.state = CircuitState.OPEN
                self.opened_at_monotonic = time.monotonic()
                logger.warning(
                    "Circuit tripped to OPEN after %d consecutive failures",
                    self.failure_count,
                )


# ─────────────────────────────────────────────────────────────────────────
# ResilienceManager — the public face of this module
# ─────────────────────────────────────────────────────────────────────────


class ResilienceManager:
    """Wraps each per-network call with timeout, breaker, and structured errors.

    The single guarantee: :meth:`call` **never raises**. Every code path
    returns a :class:`NetworkResult`, so the coordinator can rely on a
    homogeneous list back from ``asyncio.gather``.
    """

    def __init__(
        self,
        gateways: list[NetworkGateway],
        *,
        failure_threshold: int = 3,
        recovery_timeout_s: float = 30.0,
        network_caller: NetworkCaller = default_network_caller,
    ) -> None:
        self._breakers: dict[str, CircuitBreaker] = {
            g.name: CircuitBreaker(
                failure_threshold=failure_threshold,
                recovery_timeout_s=recovery_timeout_s,
            )
            for g in gateways
        }
        self._failure_threshold = failure_threshold
        self._recovery_timeout_s = recovery_timeout_s
        self._network_caller = network_caller

    def get_breaker(self, network_name: str) -> CircuitBreaker:
        """Return (creating if needed) the breaker for ``network_name``."""
        breaker = self._breakers.get(network_name)
        if breaker is None:
            breaker = CircuitBreaker(
                failure_threshold=self._failure_threshold,
                recovery_timeout_s=self._recovery_timeout_s,
            )
            self._breakers[network_name] = breaker
        return breaker

    async def call(
        self,
        gateway: NetworkGateway,
        intent: dict[str, Any],
        session: aiohttp.ClientSession,
    ) -> NetworkResult:
        """Single resilient per-network call.

        Sequence:
          1. Breaker gate (fast-fail when OPEN).
          2. ``asyncio.wait_for(..., timeout=gateway.timeout_s)``.
          3. Catch+translate ``aiohttp``/``asyncio`` errors into ``NetworkStatus``.
          4. Record success/failure with the breaker.
        """
        breaker = self.get_breaker(gateway.name)

        if not await breaker.allow_request():
            logger.info("Circuit OPEN for %s — fast-failing", gateway.name)
            return NetworkResult(
                network=gateway.name,
                status=NetworkStatus.CIRCUIT_OPEN,
                error=f"Circuit breaker OPEN for network {gateway.name}",
                latency_ms=0.0,
            )

        start = time.monotonic()
        try:
            items = await asyncio.wait_for(
                self._network_caller(gateway, intent, session),
                timeout=gateway.timeout_s,
            )
            latency = (time.monotonic() - start) * 1000.0
            await breaker.record_success()
            logger.info(
                "Network %s OK items=%d latency_ms=%.1f",
                gateway.name, len(items), latency,
            )
            return NetworkResult(
                network=gateway.name,
                status=NetworkStatus.OK,
                items=items,
                latency_ms=latency,
            )

        except asyncio.TimeoutError:
            latency = (time.monotonic() - start) * 1000.0
            await breaker.record_failure()
            logger.warning(
                "Network %s timed out after %.2fs (latency_ms=%.1f)",
                gateway.name, gateway.timeout_s, latency,
            )
            return NetworkResult(
                network=gateway.name,
                status=NetworkStatus.TIMEOUT,
                latency_ms=latency,
                error=f"Timeout after {gateway.timeout_s}s",
            )

        except aiohttp.ClientResponseError as exc:
            latency = (time.monotonic() - start) * 1000.0
            await breaker.record_failure()
            status = (
                NetworkStatus.UPSTREAM_5XX
                if exc.status >= 500
                else NetworkStatus.UPSTREAM_4XX
            )
            logger.warning(
                "Network %s HTTP %d (%s)", gateway.name, exc.status, exc.message
            )
            return NetworkResult(
                network=gateway.name,
                status=status,
                latency_ms=latency,
                error=f"HTTP {exc.status}: {exc.message}",
            )

        except (aiohttp.ClientConnectionError, ConnectionError, OSError) as exc:
            # aiohttp.ClientConnectionError covers ClientConnectorError,
            # ServerDisconnectedError, ClientResetError. ConnectionError +
            # OSError catch DNS / TCP-level refusals not raised by aiohttp.
            latency = (time.monotonic() - start) * 1000.0
            await breaker.record_failure()
            logger.warning(
                "Network %s connection refused/dropped: %s", gateway.name, exc
            )
            return NetworkResult(
                network=gateway.name,
                status=NetworkStatus.CONNECTION_REFUSED,
                latency_ms=latency,
                error=str(exc),
            )

        except (aiohttp.ContentTypeError, aiohttp.ClientPayloadError, ValueError) as exc:
            # Non-JSON, malformed JSON, or downstream returned an
            # unexpected shape — treat as upstream contract breach.
            latency = (time.monotonic() - start) * 1000.0
            await breaker.record_failure()
            logger.warning(
                "Network %s returned invalid response: %s", gateway.name, exc
            )
            return NetworkResult(
                network=gateway.name,
                status=NetworkStatus.INVALID_RESPONSE,
                latency_ms=latency,
                error=str(exc),
            )

        except aiohttp.ClientError as exc:
            # Any remaining aiohttp client-side error.
            latency = (time.monotonic() - start) * 1000.0
            await breaker.record_failure()
            logger.warning("Network %s client error: %s", gateway.name, exc)
            return NetworkResult(
                network=gateway.name,
                status=NetworkStatus.UNKNOWN_ERROR,
                latency_ms=latency,
                error=str(exc),
            )

        except asyncio.CancelledError:
            # Surface cancellation — do not swallow it. Record as failure
            # so the breaker reacts, then re-raise so the task tree
            # honours the cancellation signal.
            await breaker.record_failure()
            raise

        except Exception as exc:  # noqa: BLE001 — final defence-in-depth
            latency = (time.monotonic() - start) * 1000.0
            await breaker.record_failure()
            logger.exception("Network %s unhandled error", gateway.name)
            return NetworkResult(
                network=gateway.name,
                status=NetworkStatus.UNKNOWN_ERROR,
                latency_ms=latency,
                error=f"{type(exc).__name__}: {exc}",
            )


__all__ = [
    "CircuitBreaker",
    "CircuitState",
    "NetworkCaller",
    "ResilienceManager",
    "default_network_caller",
]
