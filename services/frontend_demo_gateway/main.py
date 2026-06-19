"""FastAPI entrypoint — Frontend Demo Gateway.

Wires together the two dynamic mock routers (``mock_score`` + ``mock_negotiate``)
and exposes them under a single ``/api/demo/*`` namespace at port 8005.

Key design choices:

* **Real components, mocked infrastructure.** The PyTorch model and
  LangGraph state machine are production code. We mock only the external
  infrastructure (no MLflow registry, no Postgres saver, no Redis broker,
  no Beckn networks) — replacing each with a fast deterministic
  simulator.
* **CORS open to the front-end origins.** The Next.js dev server runs at
  ``http://localhost:3000``; production builds may be served from
  arbitrary origins. ``allow_origins`` lists the common dev origins and
  ``allow_origin_regex`` covers anything else.
* **Singleton model + graph at startup.** Loaded once in the lifespan,
  shared across requests via ``app.state``. The Phase2Scorer is small
  (~12 floats) and the graph is stateless — sharing is safe and avoids
  per-request import overhead.
"""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware

# Side-effect: inject sibling service roots onto sys.path. MUST come
# before any of our local modules that import from ``core.*`` or ``src.*``.
from . import _paths  # noqa: F401

import httpx  # noqa: E402
import redis.asyncio as aioredis  # noqa: E402

from .config import CONFIG  # noqa: E402
from .live_negotiate import router as negotiate_router  # noqa: E402
from .mock_score import _build_model, router as score_router  # noqa: E402
from .supplier_agent import SupplierAgent  # noqa: E402

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
    """Boot the singletons (score model, supplier agent, redis, engine client)."""
    logger.info("Frontend Demo Gateway starting")

    # Phase-2 LTR model (real PyTorch nn.Linear, fallback weights).
    app.state.score_model = _build_model()
    app.state.score_model_version = "phase2-fallback-static-weights"

    # ── Supplier Agent — real qwen3:8b via local Ollama (OpenAI SDK). ──
    # Constructed ONCE here; owns an AsyncOpenAI connection pool. Never
    # re-instantiated per request.
    app.state.supplier_agent = SupplierAgent(
        base_url=CONFIG.ollama_base_url,
        api_key=CONFIG.ollama_api_key,
        model=CONFIG.supplier_model,
        buyer_model=CONFIG.buyer_humanize_model,
        acceptable_discount_floor=CONFIG.supplier_acceptable_discount_floor,
        temperature=CONFIG.supplier_temperature,
        timeout_s=CONFIG.supplier_timeout_s,
    )
    ollama_ok = await app.state.supplier_agent.health()
    logger.info(
        "Supplier Agent ready: model=%s ollama=%s reachable=%s",
        CONFIG.supplier_model,
        CONFIG.ollama_base_url,
        ollama_ok,
    )

    # ── Redis client (publishes supplier responses → engine resume). ──
    app.state.redis = aioredis.from_url(CONFIG.redis_url, decode_responses=True)

    # ── Shared httpx client proxying to the live Negotiation Engine. ──
    app.state.engine_client = httpx.AsyncClient(
        base_url=CONFIG.negotiation_engine_url,
        timeout=CONFIG.engine_timeout_s,
    )

    # In-memory session store: thread_id → deal context + round history.
    app.state.negotiation_sessions = {}

    logger.info(
        "Gateway ready: Phase2Scorer loaded, Supplier=%s, proxying buyer to %s, "
        "endpoints under /api/demo/*",
        CONFIG.supplier_model,
        CONFIG.negotiation_engine_url,
    )

    try:
        yield
    finally:
        await app.state.engine_client.aclose()
        try:
            await app.state.redis.aclose()
        except Exception:  # pragma: no cover
            pass
        logger.info("Frontend Demo Gateway shutdown complete")


# ─────────────────────────────────────────────────────────────────────────
# Application
# ─────────────────────────────────────────────────────────────────────────


app = FastAPI(
    title="Frontend Demo Gateway",
    description=(
        "Dynamic mock gateway for the Next.js demo client. Wraps the real "
        "Phase-2 LTR PyTorch model and the real Phase-3 LangGraph "
        "negotiation state machine behind ``/api/demo/*`` endpoints; "
        "isolates only the external infrastructure (Beckn networks, "
        "Qdrant, Kafka, Redis) through fast deterministic simulators."
    ),
    version="0.1.0",
    lifespan=lifespan,
)


# CORS — allow the Next.js dev server (port 3000) and any localhost origin.
# In production, narrow ``allow_origins`` to the deployed front-end URL(s).
_DEV_ORIGINS: list[str] = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:3001",
    "http://127.0.0.1:3001",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_DEV_ORIGINS,
    allow_origin_regex=r"http://localhost(:\d+)?",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─────────────────────────────────────────────────────────────────────────
# Mount the dynamic-mock routers
# ─────────────────────────────────────────────────────────────────────────

app.include_router(score_router)
app.include_router(negotiate_router)


# ─────────────────────────────────────────────────────────────────────────
# Ops endpoints
# ─────────────────────────────────────────────────────────────────────────


@app.get("/healthz", tags=["ops"])
async def healthz() -> dict[str, str]:
    """Kubernetes-style liveness probe."""
    return {"status": "ok"}


@app.get("/readyz", tags=["ops"])
async def readyz(request: Request) -> dict:
    """Readiness probe — confirms the singletons are loaded + Ollama reachable."""
    model = getattr(request.app.state, "score_model", None)
    agent = getattr(request.app.state, "supplier_agent", None)
    if model is None or agent is None:
        return {"status": "starting"}, status.HTTP_503_SERVICE_UNAVAILABLE  # type: ignore[return-value]
    return {
        "status": "ready",
        "score_model_version": request.app.state.score_model_version,
        "score_model_weights": model.get_weights(),
        "supplier_model": agent.model,
        "ollama_reachable": await agent.health(),
        "active_sessions": len(request.app.state.negotiation_sessions),
    }


__all__ = ["app"]
