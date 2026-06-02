"""Async fan-out / fan-in coordinator for multi-network Beckn search.

Implements Subagent 1's spec: take a single :class:`IntentPayload`,
clone-and-dispatch it concurrently to N :class:`NetworkGateway`
endpoints, and synthesise the per-network results into one
:class:`MultiSearchResult`.

Concurrency model
=================

* One ``asyncio.Task`` per configured gateway, created implicitly by
  passing the coroutines to :func:`asyncio.gather`.
* ``return_exceptions=True`` on the gather call — defence-in-depth in
  case the resilience layer ever leaks an exception (it should not, by
  contract). Any leaked exception is coerced into a
  :class:`NetworkResult` with status ``UNKNOWN_ERROR`` so the
  coordinator can never crash a search transaction.
* The per-network timeout is enforced *inside* the resilience layer's
  ``asyncio.wait_for`` — the coordinator does not impose its own outer
  timeout, since the fan-out's wall-clock is naturally bounded by the
  slowest individual ``gateway.timeout_s``.
* No mutable shared state — each task receives its own argument tuple,
  writes to nothing the others touch, and the aggregator is a pure
  function over the returned list. Safe for arbitrary concurrency.

The coordinator owns the ``aiohttp.ClientSession`` lifecycle only when
it is *not* passed one externally (the ``__aenter__`` path) — when the
FastAPI lifespan provides a long-lived session, the coordinator
borrows it and never closes it.
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from types import TracebackType
from typing import Any, Optional

import aiohttp

from .aggregator import ResultAggregator
from .models import (
    AggregatedItem,
    IntentPayload,
    MultiSearchResult,
    NetworkFailure,
    NetworkGateway,
    NetworkResult,
    NetworkStatus,
)
from .resilience import ResilienceManager

logger = logging.getLogger(__name__)


class MultiNetworkCoordinator:
    """Fan a single intent out to N networks; aggregate the responses.

    Usage (FastAPI lifespan, shared session)::

        coord = MultiNetworkCoordinator(
            gateways, resilience=rm, aggregator=agg, session=app.state.session
        )
        result = await coord.search(intent)

    Usage (one-shot script, owned session)::

        async with MultiNetworkCoordinator(gateways, resilience=rm, aggregator=agg) as coord:
            result = await coord.search(intent)
    """

    def __init__(
        self,
        gateways: list[NetworkGateway],
        *,
        resilience: ResilienceManager,
        aggregator: ResultAggregator,
        session: Optional[aiohttp.ClientSession] = None,
    ) -> None:
        if not gateways:
            raise ValueError("At least one network gateway must be configured")
        # Defensive copy + freeze ordering — gateways are immutable for the
        # lifetime of the coordinator. A redeploy is required to change
        # the network set.
        self._gateways: tuple[NetworkGateway, ...] = tuple(gateways)
        self._resilience = resilience
        self._aggregator = aggregator
        self._session: Optional[aiohttp.ClientSession] = session
        self._owns_session: bool = session is None

    # ── Async context manager (owned-session mode) ──────────────────────

    async def __aenter__(self) -> MultiNetworkCoordinator:
        if self._owns_session:
            self._session = aiohttp.ClientSession()
        return self

    async def __aexit__(
        self,
        exc_type: Optional[type[BaseException]],
        exc: Optional[BaseException],
        tb: Optional[TracebackType],
    ) -> None:
        if self._owns_session and self._session is not None:
            await self._session.close()
            self._session = None

    # ── Properties ──────────────────────────────────────────────────────

    @property
    def gateways(self) -> tuple[NetworkGateway, ...]:
        """Read-only view of the configured gateways."""
        return self._gateways

    # ── Public ──────────────────────────────────────────────────────────

    async def search(self, intent: IntentPayload) -> MultiSearchResult:
        """Fan out one intent; fan in one aggregated catalog.

        The method does **not** raise on any per-network failure — the
        resilience layer translates every error into a
        :class:`NetworkResult`. The only exceptions that can escape are:

        * :class:`RuntimeError` if the coordinator was constructed
          without a session and used outside its ``async with`` block.
        * :class:`asyncio.CancelledError` if the caller cancels the
          ``asyncio.Task`` running this coroutine — propagated by design.
        """
        if self._session is None:
            raise RuntimeError(
                "MultiNetworkCoordinator has no aiohttp session — either "
                "construct with `session=...` or use it as an `async with` "
                "context manager."
            )

        query_id = f"q-{uuid.uuid4()}"
        # Serialise intent once — clone-by-value via the dict so each
        # network task sees an independent payload.
        intent_payload = intent.model_dump(exclude_none=True)

        logger.info(
            "Fan-out query_id=%s item=%r networks=%s",
            query_id,
            intent.item_name,
            [g.name for g in self._gateways],
        )

        start = time.monotonic()
        # Build the list of resilient calls. Each coroutine is an
        # independent unit of work; asyncio.gather schedules them
        # concurrently as Tasks. Per-network timeout is enforced inside
        # ResilienceManager.call via asyncio.wait_for.
        coroutines = [
            self._resilience.call(g, intent_payload, self._session)
            for g in self._gateways
        ]

        # return_exceptions=True so a leaked exception from the resilience
        # layer does not cancel the sibling tasks. ResilienceManager
        # contractually never raises, but the belt-and-braces handler
        # below catches the case where that contract is violated.
        raw_results: list[Any] = await asyncio.gather(
            *coroutines, return_exceptions=True
        )

        total_latency_ms = (time.monotonic() - start) * 1000.0
        results = self._coerce_to_network_results(raw_results)

        # Fan-in synthesis.
        items, ok, failures = self._aggregator.aggregate(results)

        responded = [r.network for r in ok]
        per_network_latency = {r.network: round(r.latency_ms, 2) for r in results}
        degraded = len(failures) > 0

        logger.info(
            "Fan-in query_id=%s items=%d responded=%s failed=%s total_ms=%.1f",
            query_id, len(items), responded,
            [f.network for f in failures], total_latency_ms,
        )

        return MultiSearchResult(
            query_id=query_id,
            requested_networks=[g.name for g in self._gateways],
            responded_networks=responded,
            failed_networks=failures,
            items=items,
            degraded=degraded,
            total_latency_ms=total_latency_ms,
            per_network_latency_ms=per_network_latency,
        )

    # ── Internal helpers ────────────────────────────────────────────────

    def _coerce_to_network_results(self, raw: list[Any]) -> list[NetworkResult]:
        """Convert anything ``gather(return_exceptions=True)`` produced.

        Resilience always returns ``NetworkResult``; if a future bug
        leaks a bare exception, this method makes sure that exception
        is recorded as a structured failure rather than crashing the
        downstream aggregator.
        """
        coerced: list[NetworkResult] = []
        for gateway, item in zip(self._gateways, raw):
            if isinstance(item, NetworkResult):
                coerced.append(item)
            elif isinstance(item, BaseException):
                logger.exception(
                    "Resilience layer leaked %s for network %s — coercing to UNKNOWN_ERROR",
                    type(item).__name__,
                    gateway.name,
                )
                coerced.append(
                    NetworkResult(
                        network=gateway.name,
                        status=NetworkStatus.UNKNOWN_ERROR,
                        error=f"Leaked {type(item).__name__}: {item}",
                    )
                )
            else:
                # Should never happen — type discipline upstream.
                logger.error(
                    "Resilience layer returned non-NetworkResult for %s: %r",
                    gateway.name,
                    item,
                )
                coerced.append(
                    NetworkResult(
                        network=gateway.name,
                        status=NetworkStatus.UNKNOWN_ERROR,
                        error=f"Unexpected result type: {type(item).__name__}",
                    )
                )
        return coerced


__all__ = ["MultiNetworkCoordinator"]
