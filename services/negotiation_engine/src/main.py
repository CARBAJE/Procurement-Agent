"""FastAPI entrypoint for the Negotiation Engine microservice.

Exposes one production endpoint and a couple of operational ones:

* ``POST /negotiate`` — kick off a new negotiation session. Returns
  ``202 Accepted`` immediately with the LangGraph ``thread_id``; the
  graph runs through ``analyze_target → compute_counter_offer →
  policy_guardrail_check`` and parks at the ``wait_for_async_callback``
  interrupt within milliseconds. The Redis broker (started by the
  lifespan) resumes the parked thread when ``/on_select`` arrives.
* ``GET /negotiate/{transaction_id}`` — inspect the current LangGraph
  state for a session (useful for HITL operators).
* ``GET /healthz`` — Kubernetes liveness probe.
* ``GET /readyz`` — readiness probe (does the graph compile?).

The lifespan does three things at startup:

1. Build the LangGraph with a durable checkpointer (Postgres when
   ``NEGOTIATION_POSTGRES_DSN`` is set; ``MemorySaver`` otherwise).
2. Spawn the :class:`OnSelectListener` as a supervised background task.
3. (Implicit) The Kafka audit producer is lazily started on first
   ``log_negotiation_event`` call — no work here.

…and the inverse on shutdown: cancel the listener, close the
checkpointer, flush the audit producer.
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Optional

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from . import audit
from .broker import OnSelectListener
from .config import CONFIG
from .graph import build_graph_async
from .models import SupplierOffer

# ─────────────────────────────────────────────────────────────────────────
# Logging
# ─────────────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=CONFIG.log_level,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────
# API request / response models
# ─────────────────────────────────────────────────────────────────────────


class NegotiateRequest(BaseModel):
    """Inbound payload — typically emitted by the Comparative Engine.

    All fields except ``ranked_offers`` and ``category`` are optional;
    sane defaults are picked from :data:`CONFIG` and ``policy`` so the
    operator can ``curl`` the endpoint without filling in every knob.
    """

    model_config = ConfigDict(extra="forbid")

    transaction_id: Optional[str] = Field(
        default=None,
        description=(
            "Beckn transaction id == LangGraph thread_id. Auto-generated "
            "with uuid4 when omitted. MUST be unique per session "
            "(reuse is forbidden per CLAUDE.md)."
        ),
    )
    category: str = Field(
        ...,
        min_length=1,
        description="Procurement category slug (drives strategy archetype).",
    )
    ranked_offers: list[SupplierOffer] = Field(
        ...,
        min_length=1,
        description="Ranked candidate list from the Comparative Engine.",
    )
    policy: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Session policy dict. Recognised keys: budget_unit_price, "
            "category_max_discount_pct, supplier_max_discount_pct, "
            "supplier_lead_time_min, supplier_available_qty, hitl_gap_pct."
        ),
    )
    max_rounds: int = Field(
        default=3,
        ge=1,
        le=5,
        description="Hard ceiling on negotiation rounds (G4 ≤ 5).",
    )


class NegotiateAccepted(BaseModel):
    """``202 Accepted`` response shape.

    The negotiation continues asynchronously — the caller polls
    ``GET /negotiate/{transaction_id}`` or subscribes to the
    ``negotiation_results:{transaction_id}`` Redis channel to learn the
    outcome (the latter is the production pattern).
    """

    thread_id: str = Field(..., description="The LangGraph thread id (==transaction_id).")
    status: str = Field(default="accepted")
    paused_at: Optional[str] = Field(
        default=None,
        description=(
            "Name of the node the graph parked at (typically "
            "``wait_for_async_callback`` for transactional categories "
            "or ``None`` for advisory categories that finalise immediately)."
        ),
    )
    interrupt: Optional[dict] = Field(
        default=None,
        description="The interrupt envelope if the graph is paused, else None.",
    )
    final_outcome: Optional[str] = Field(
        default=None,
        description=(
            "Terminal outcome if the graph completed within this request "
            "(advisory categories, exhausted candidates, etc.). None "
            "while the graph is paused."
        ),
    )


# ─────────────────────────────────────────────────────────────────────────
# Lifespan — owns the LangGraph, the broker listener, and the audit producer
# ─────────────────────────────────────────────────────────────────────────


async def _safe_listener_runner(graph: Any) -> None:
    """Wrap ``OnSelectListener.run`` so it never bubbles to the event loop.

    In a dev / CI environment Redis may not be reachable. A bare
    listener crash would mark the asyncio task with an unhandled
    exception and surface as a warning every shutdown; wrapping it
    keeps the lifespan clean and surfaces failures via the structured
    logger instead.
    """
    listener = OnSelectListener(graph)
    try:
        await listener.run()
    except asyncio.CancelledError:
        logger.info("OnSelectListener cancelled — clean shutdown")
        raise
    except Exception as exc:  # pragma: no cover — Redis unavailable path
        logger.warning(
            "OnSelectListener exited with %s — broker will not resume parked "
            "threads until restarted",
            exc,
        )


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """FastAPI startup / shutdown lifecycle hooks."""
    logger.info("Negotiation Engine starting (port=%d)", CONFIG.api_port)

    # Build the graph inside the durable-checkpointer context manager. The
    # context handles AsyncPostgresSaver setup/teardown when configured
    # and falls back to MemorySaver otherwise (see ``graph.build_graph_async``).
    async with build_graph_async() as graph:
        app.state.graph = graph

        # Capture the running loop so audit events emitted from LangGraph
        # sync-node worker threads can bridge back to it (and reach Kafka)
        # instead of falling through to the logger.
        audit.register_event_loop()

        # Spawn the broker listener as a supervised background task.
        # ``_safe_listener_runner`` swallows its own exceptions so the
        # lifespan stays clean if Redis is down.
        broker_task = asyncio.create_task(
            _safe_listener_runner(graph), name="negotiation-broker"
        )
        app.state.broker_task = broker_task
        logger.info("OnSelectListener task scheduled")

        try:
            yield
        finally:
            logger.info("Negotiation Engine shutting down")
            broker_task.cancel()
            try:
                await broker_task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
            await audit.shutdown()
            logger.info("Negotiation Engine shutdown complete")


# ─────────────────────────────────────────────────────────────────────────
# Application
# ─────────────────────────────────────────────────────────────────────────


app = FastAPI(
    title="Negotiation Engine",
    description=(
        "Beckn Procurement Agent — Phase 3 negotiation microservice. "
        "Implements multi-round /select with strategy-driven counter-offers, "
        "deterministic policy guardrails, and async Beckn callback handling."
    ),
    version="0.4.0",  # Step 4 — observability + entrypoint
    lifespan=lifespan,
)


# ─────────────────────────────────────────────────────────────────────────
# CORS — mounted first so it is the outermost middleware layer.
#
# NOTE: the Next.js frontend reaches this service *server-side* (Node →
# FastAPI proxy routes), where CORS does not apply. This middleware is
# therefore defense-in-depth for any future direct browser→engine call
# (e.g. a dashboard polling /negotiate/{id} from the client), not a fix
# for the current server-proxy architecture.
# ─────────────────────────────────────────────────────────────────────────

_FRONTEND_ORIGINS: list[str] = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_FRONTEND_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─────────────────────────────────────────────────────────────────────────
# Endpoints
# ─────────────────────────────────────────────────────────────────────────


@app.get("/healthz", tags=["ops"])
async def healthz() -> dict[str, str]:
    """Kubernetes liveness probe."""
    return {"status": "ok"}


@app.get("/readyz", tags=["ops"])
async def readyz(request: Request) -> dict[str, Any]:
    """Readiness probe — confirms the LangGraph has been compiled."""
    graph = getattr(request.app.state, "graph", None)
    if graph is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="LangGraph not yet compiled",
        )
    return {
        "status": "ready",
        "tracing_enabled": CONFIG.tracing_enabled,
        "langchain_project": CONFIG.langchain_project,
        "kafka_configured": bool(CONFIG.kafka_bootstrap_servers),
        "postgres_configured": bool(CONFIG.postgres_dsn),
    }


@app.post(
    "/negotiate",
    response_model=NegotiateAccepted,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["negotiation"],
    summary="Kick off a new negotiation session.",
    description=(
        "Accepts a ranked list of supplier offers and starts the LangGraph "
        "state machine. Returns 202 Accepted as soon as the graph parks at "
        "the ``wait_for_async_callback`` interrupt (or earlier for advisory "
        "categories). The negotiation continues asynchronously via the "
        "Redis Pub/Sub broker."
    ),
)
async def negotiate(req: NegotiateRequest, request: Request) -> NegotiateAccepted:
    graph = request.app.state.graph
    transaction_id = req.transaction_id or f"txn-{uuid.uuid4()}"
    config = {"configurable": {"thread_id": transaction_id}}

    initial_state: dict[str, Any] = {
        "transaction_id": transaction_id,
        "category": req.category,
        # Pydantic models serialise cleanly through model_dump so the
        # graph's downstream ``SupplierOffer.model_validate`` works.
        "ranked_candidates": [o.model_dump() for o in req.ranked_offers],
        "policy": req.policy,
        "negotiation_round": 0,
        "max_rounds": req.max_rounds,
    }

    logger.info(
        "Starting negotiation thread_id=%s category=%s candidates=%d",
        transaction_id,
        req.category,
        len(req.ranked_offers),
    )

    try:
        # ``ainvoke`` runs synchronously through the graph until it
        # either terminates or hits an ``interrupt()`` — typically within
        # milliseconds for our placeholder nodes. The negotiation is
        # *not* awaited to completion; the graph parks at the first
        # async-callback interrupt and the broker resumes it later.
        result = await graph.ainvoke(initial_state, config=config)
    except Exception as exc:
        logger.exception("Graph invocation failed for thread_id=%s", transaction_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Negotiation startup failed: {exc}",
        ) from exc

    interrupts = result.get("__interrupt__")
    if interrupts:
        # Graph is paused — surface the interrupt envelope so the caller
        # knows what we are waiting for. Production callers would use
        # this to display a HITL prompt or wire a Redis subscription.
        head = interrupts[0]
        return NegotiateAccepted(
            thread_id=transaction_id,
            status="accepted",
            paused_at=await _first_pending_node(graph, config),
            interrupt=getattr(head, "value", None) or {},
            final_outcome=None,
        )

    # No interrupt: the graph terminated synchronously. This happens
    # for advisory-only categories (e.g. IT equipment, medical) which
    # route through ``evaluate_ambiguous_terms → finalize`` without
    # ever dispatching a counter-offer.
    return NegotiateAccepted(
        thread_id=transaction_id,
        status="accepted",
        paused_at=None,
        interrupt=None,
        final_outcome=result.get("final_outcome"),
    )


@app.get(
    "/negotiate/{transaction_id}",
    tags=["negotiation"],
    summary="Inspect a negotiation's current state.",
)
async def get_negotiation(transaction_id: str, request: Request) -> dict[str, Any]:
    """Return the current LangGraph snapshot for ``transaction_id``.

    Useful for HITL UIs and operators. Returns 404 when the thread_id
    has no checkpoint (either never started or expired from memory).
    """
    graph = request.app.state.graph
    config = {"configurable": {"thread_id": transaction_id}}
    # Use the ASYNC state API: AsyncPostgresSaver forbids synchronous
    # ``get_state`` from the main thread (raises InvalidStateError). The
    # async form works for both AsyncPostgresSaver and MemorySaver.
    snapshot = await graph.aget_state(config)
    if not snapshot or not snapshot.values:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No checkpoint found for thread_id={transaction_id}",
        )
    return {
        "thread_id": transaction_id,
        "next": list(snapshot.next or ()),
        "final_outcome": snapshot.values.get("final_outcome"),
        "current_target": snapshot.values.get("current_target"),
        "current_counter_offer": snapshot.values.get("current_counter_offer"),
        "negotiation_round": snapshot.values.get("negotiation_round", 0),
        "audit_event_count": len(snapshot.values.get("audit_events") or []),
    }


# ─────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────


async def _first_pending_node(graph: Any, config: dict) -> Optional[str]:
    """Return the first pending node name (used for the 202 response).

    Uses the async state API so it is compatible with AsyncPostgresSaver
    (the sync ``get_state`` raises InvalidStateError from the main thread).
    """
    try:
        snapshot = await graph.aget_state(config)
    except Exception:  # pragma: no cover — defensive
        return None
    pending = snapshot.next if snapshot else None
    if not pending:
        return None
    return pending[0] if isinstance(pending, tuple) else str(pending)


# ─────────────────────────────────────────────────────────────────────────
# Standard error handler — surface validation errors as JSON
# ─────────────────────────────────────────────────────────────────────────


@app.exception_handler(HTTPException)
async def _http_exception_handler(_: Request, exc: HTTPException) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail},
    )


__all__ = ["app", "NegotiateAccepted", "NegotiateRequest"]
