"""FastAPI entrypoint for the Discovery Engine.

Exposes:

* ``POST /search/multi-network`` — fan out an intent to every
  configured Beckn network and return one aggregated catalog.
* ``GET /healthz`` — Kubernetes liveness probe.
* ``GET /readyz`` — readiness probe; surfaces the gateway list and
  whether the coordinator was successfully wired up.

The lifespan owns the long-lived ``aiohttp.ClientSession`` (with a
bounded TCP connector pool) and the singleton :class:`MultiNetworkCoordinator`.
Per-request handlers borrow the coordinator from ``app.state`` so a
single session is reused for the lifetime of the pod — connection
pooling is on by default.
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

import aiohttp
from fastapi import FastAPI, HTTPException, Request, status

from .aggregator import ResultAggregator
from .config import CONFIG
from .coordinator import MultiNetworkCoordinator
from .models import IntentPayload, MultiSearchResult
from .resilience import ResilienceManager

logging.basicConfig(
    level=CONFIG.log_level,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────
# Lifespan
# ─────────────────────────────────────────────────────────────────────────


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Bring the aiohttp session + coordinator up at startup, tear down on exit."""
    gateways = CONFIG.gateways
    logger.info(
        "Discovery Engine starting port=%d gateways=%s",
        CONFIG.api_port,
        [g.name for g in gateways],
    )

    session = aiohttp.ClientSession(
        timeout=aiohttp.ClientTimeout(total=CONFIG.http_outer_timeout_s),
        connector=aiohttp.TCPConnector(limit=CONFIG.http_connector_limit),
    )
    aggregator = ResultAggregator(geo_proximity_km=CONFIG.geo_proximity_km)
    resilience = ResilienceManager(
        gateways,
        failure_threshold=CONFIG.circuit_failure_threshold,
        recovery_timeout_s=CONFIG.circuit_recovery_timeout_s,
    )

    # If no gateways were configured at startup, we still let the
    # service boot — /readyz reports the misconfig so an operator
    # notices, but /healthz stays green so K8s doesn't restart-loop.
    coordinator: MultiNetworkCoordinator | None = None
    if gateways:
        coordinator = MultiNetworkCoordinator(
            gateways, resilience=resilience, aggregator=aggregator, session=session
        )
    else:
        logger.error(
            "No gateways configured — DISCOVERY_NETWORKS_JSON is empty or invalid"
        )

    app.state.session = session
    app.state.coordinator = coordinator
    app.state.gateways = gateways

    try:
        yield
    finally:
        logger.info("Discovery Engine shutting down")
        await session.close()
        logger.info("Discovery Engine shutdown complete")


# ─────────────────────────────────────────────────────────────────────────
# App
# ─────────────────────────────────────────────────────────────────────────


app = FastAPI(
    title="Discovery Engine — Multi-Network Search",
    description=(
        "Phase 3 multi-network discovery for the Beckn Procurement Agent. "
        "Fans a single intent out to N independent Beckn networks in "
        "parallel, enforces per-network timeouts + circuit breakers, and "
        "aggregates returned catalogs into one deduplicated result set."
    ),
    version="0.1.0",
    lifespan=lifespan,
)


# ─────────────────────────────────────────────────────────────────────────
# Endpoints
# ─────────────────────────────────────────────────────────────────────────


@app.get("/healthz", tags=["ops"])
async def healthz() -> dict[str, str]:
    """Kubernetes liveness probe — unconditional."""
    return {"status": "ok"}


@app.get("/readyz", tags=["ops"])
async def readyz(request: Request) -> dict:
    """Readiness probe — surfaces gateway count and config sanity."""
    coordinator: MultiNetworkCoordinator | None = getattr(
        request.app.state, "coordinator", None
    )
    if coordinator is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Coordinator not initialised — DISCOVERY_NETWORKS_JSON likely empty.",
        )
    gateways = request.app.state.gateways
    return {
        "status": "ready",
        "gateway_count": len(gateways),
        "gateways": [
            {"name": g.name, "base_url": g.base_url, "timeout_s": g.timeout_s}
            for g in gateways
        ],
        "circuit_failure_threshold": CONFIG.circuit_failure_threshold,
        "circuit_recovery_timeout_s": CONFIG.circuit_recovery_timeout_s,
    }


@app.post(
    "/search/multi-network",
    response_model=MultiSearchResult,
    status_code=status.HTTP_200_OK,
    tags=["discovery"],
    summary="Fan a single intent out to every configured Beckn network.",
    description=(
        "Always returns HTTP 200 with a structured ``MultiSearchResult``. "
        "When some networks fail (timeout, 5xx, refused), the response "
        "carries ``degraded=true`` and lists each failure in "
        "``failed_networks``. When *all* networks fail, an empty ``items`` "
        "list is returned instead of a crash — callers branch on "
        "``len(items)`` and ``degraded`` rather than HTTP status code."
    ),
)
async def multi_network_search(
    intent: IntentPayload, request: Request
) -> MultiSearchResult:
    coordinator: MultiNetworkCoordinator | None = getattr(
        request.app.state, "coordinator", None
    )
    if coordinator is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "No gateways configured. Set DISCOVERY_NETWORKS_JSON "
                "and restart the service."
            ),
        )
    return await coordinator.search(intent)


__all__ = ["app"]
