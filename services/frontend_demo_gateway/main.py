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

from .mock_negotiate import router as negotiate_router  # noqa: E402
from .mock_score import _build_model, router as score_router  # noqa: E402

# Import once for the LangGraph builder.
from langgraph.checkpoint.memory import MemorySaver  # noqa: E402
from src.graph import build_graph  # noqa: E402  (negotiation_engine)

logging.basicConfig(
    level=os.getenv("FRONTEND_DEMO_GATEWAY_LOG_LEVEL", "INFO"),
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────
# Lifespan
# ─────────────────────────────────────────────────────────────────────────


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Boot the model + graph singletons. Tear them down on shutdown."""
    logger.info("Frontend Demo Gateway starting")

    # Phase-2 LTR model (real PyTorch nn.Linear, fallback weights).
    app.state.score_model = _build_model()
    app.state.score_model_version = "phase2-fallback-static-weights"

    # Real LangGraph state machine with MemorySaver — only the
    # checkpointer is mocked; nodes, guardrails, and Pydantic models
    # are all production.
    app.state.negotiation_graph = build_graph(checkpointer=MemorySaver())
    app.state.negotiation_resumed = {}  # thread_id → bool

    logger.info(
        "Gateway ready: Phase2Scorer loaded, LangGraph compiled, "
        "endpoints mounted under /api/demo/*"
    )

    try:
        yield
    finally:
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
    """Readiness probe — confirms both singletons are loaded."""
    model = getattr(request.app.state, "score_model", None)
    graph = getattr(request.app.state, "negotiation_graph", None)
    if model is None or graph is None:
        return {"status": "starting"}, status.HTTP_503_SERVICE_UNAVAILABLE  # type: ignore[return-value]
    return {
        "status": "ready",
        "score_model_version": request.app.state.score_model_version,
        "score_model_weights": model.get_weights(),
        "active_threads": len(request.app.state.negotiation_resumed),
    }


__all__ = ["app"]
