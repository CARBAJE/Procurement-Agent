"""Dynamic Negotiation Engine mock — ``POST /api/demo/negotiate``.

Drives the **real** LangGraph state machine end-to-end:

1. Compiles the production graph from
   ``services/negotiation_engine/src/graph.py`` with an in-memory
   checkpointer (the only thing we mock — production uses Postgres).
2. Runs ``analyze_target → compute_counter_offer →
   policy_guardrail_check`` against the real Pydantic models and the
   real deterministic 20% discount cap.
3. Parks at the real ``wait_for_async_callback`` interrupt and returns
   ``202 Accepted`` with the LangGraph ``thread_id`` so the front-end
   can poll for state without blocking.
4. Schedules a ``BackgroundTask`` that ``await asyncio.sleep(3)`` and
   then resumes the parked graph via ``Command(resume=...)``, simulating
   a Beckn ``/on_select`` callback arriving 3 seconds later. This is the
   *only* infrastructure we simulate — Redis Pub/Sub + ONIX webhook are
   replaced by an in-process sleep + resume.
5. Exposes ``GET /api/demo/negotiate/{thread_id}`` so the front-end can
   poll the graph's current state — showcasing the async "interrupt &
   resume" pattern visually.
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request, status
from langgraph.types import Command
from pydantic import BaseModel, ConfigDict, Field

# Side-effect: pushes services/negotiation_engine onto sys.path.
from . import _paths  # noqa: F401

from src.models import SupplierOffer  # noqa: E402  (post path inject)

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────
# Simulation tuning
# ─────────────────────────────────────────────────────────────────────────

#: How long the simulated /on_select webhook takes to "arrive". The
#: brief specifies 3 seconds — long enough to be visible in the UI,
#: short enough to keep the demo snappy.
DEFAULT_CALLBACK_DELAY_S: float = 3.0


# ─────────────────────────────────────────────────────────────────────────
# Inbound / outbound schemas
# ─────────────────────────────────────────────────────────────────────────


class DemoNegotiateOffer(BaseModel):
    """One supplier offer — mirror of the production ``SupplierOffer`` shape."""

    model_config = ConfigDict(extra="allow")

    provider_id: str = Field(..., min_length=1)
    item_id: str = Field(..., min_length=1)
    price: float = Field(..., gt=0)
    currency: str = Field(default="INR", min_length=3, max_length=3)
    delivery_hours: int = Field(..., ge=0)
    quantity: int = Field(..., gt=0)
    score: float = 0.0
    round_received: int = 0


class DemoNegotiateRequest(BaseModel):
    """Inbound payload from the front-end demo client."""

    model_config = ConfigDict(extra="forbid")

    transaction_id: Optional[str] = None
    category: str = Field(default="commodity", min_length=1)
    ranked_offers: list[DemoNegotiateOffer] = Field(..., min_length=1)
    policy: dict[str, Any] = Field(default_factory=dict)
    max_rounds: int = Field(default=3, ge=1, le=5)
    simulated_outcome: str = Field(
        default="accepted",
        description=(
            'What the simulated /on_select callback should report after the '
            'BackgroundTask delay. One of: "accepted" | "counter" | "escalate".'
        ),
    )
    callback_delay_s: float = Field(
        default=DEFAULT_CALLBACK_DELAY_S,
        ge=0.0,
        le=30.0,
        description="How long the simulated webhook should sleep before resuming.",
    )


class DemoNegotiateAccepted(BaseModel):
    """``202 Accepted`` response — kicks off the async cycle."""

    thread_id: str
    status: str = "accepted"
    paused_at: Optional[str] = None
    interrupt: Optional[dict] = None
    final_outcome: Optional[str] = None
    callback_delay_s: float
    simulated_outcome: str


class DemoNegotiateSnapshot(BaseModel):
    """Polling response shape for ``GET /api/demo/negotiate/{thread_id}``."""

    thread_id: str
    next: list[str]
    final_outcome: Optional[str] = None
    awaiting_on_select: Optional[bool] = None
    current_target: Optional[dict] = None
    current_counter_offer: Optional[dict] = None
    last_on_select_payload: Optional[dict] = None
    negotiation_round: int = 0
    audit_event_count: int = 0
    resumed: bool = Field(
        ...,
        description='True once the simulated /on_select callback has fired.',
    )


# ─────────────────────────────────────────────────────────────────────────
# Background resume task
# ─────────────────────────────────────────────────────────────────────────


def _build_simulated_on_select_payload(outcome: str) -> dict[str, Any]:
    """Translate the front-end's ``simulated_outcome`` into a Beckn-like resume payload.

    The graph's ``_route_from_evaluate_response`` (see negotiation_engine
    graph.py) reads ``status`` and ``gap_pct`` from this payload, so we
    just emit the corresponding field shape — no LangGraph mocking
    involved.
    """
    now_iso = datetime.now(timezone.utc).isoformat()
    if outcome == "accepted":
        return {"status": "accepted", "received_at": now_iso, "gap_pct": 0.0}
    if outcome == "escalate":
        # gap_pct > policy.hitl_gap_pct (default 0.15) → routes to HITL.
        return {"status": "counter", "received_at": now_iso, "gap_pct": 0.25}
    # default: a normal counter that lets the cycle continue (round+1).
    return {"status": "counter", "received_at": now_iso, "gap_pct": 0.05}


async def _resume_after_delay(
    app: Any,
    thread_id: str,
    delay_s: float,
    simulated_outcome: str,
) -> None:
    """Sleep ``delay_s`` seconds, then resume the parked graph.

    Pure ``asyncio.sleep`` — never ``time.sleep``. Catches everything so
    a failure in this background task doesn't poison the event loop
    (errors land in the logger, the parked graph stays parked and the
    polling endpoint will show no resume — the front-end can recover by
    re-issuing the negotiate request).
    """
    try:
        if delay_s > 0:
            await asyncio.sleep(delay_s)

        payload = _build_simulated_on_select_payload(simulated_outcome)
        config = {"configurable": {"thread_id": thread_id}}
        graph = app.state.negotiation_graph

        logger.info(
            "Resuming graph thread_id=%s simulated_outcome=%s after %.2fs",
            thread_id, simulated_outcome, delay_s,
        )
        await graph.ainvoke(Command(resume=payload), config=config)

        # Mark this thread as resumed in the gateway's lightweight registry
        # so the polling endpoint can distinguish "still waiting" from
        # "resumed and now parked at HITL" (both have non-empty next).
        app.state.negotiation_resumed[thread_id] = True

    except asyncio.CancelledError:
        logger.info("Background resume cancelled for thread_id=%s", thread_id)
        raise
    except Exception as exc:  # noqa: BLE001 — defensive
        logger.exception(
            "Background resume failed for thread_id=%s: %s", thread_id, exc
        )


# ─────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────


def _first_pending_node(graph: Any, config: dict) -> Optional[str]:
    """Extract the first parked-node name from a LangGraph snapshot."""
    try:
        snapshot = graph.get_state(config)
    except Exception:  # pragma: no cover — defensive
        return None
    pending = snapshot.next if snapshot else None
    if not pending:
        return None
    return pending[0] if isinstance(pending, tuple) else str(pending)


# ─────────────────────────────────────────────────────────────────────────
# Router
# ─────────────────────────────────────────────────────────────────────────


router = APIRouter(prefix="/api/demo", tags=["demo:negotiate"])


@router.post(
    "/negotiate",
    response_model=DemoNegotiateAccepted,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Kick off a real LangGraph negotiation session (async).",
)
async def negotiate(
    req: DemoNegotiateRequest,
    request: Request,
    background_tasks: BackgroundTasks,
) -> DemoNegotiateAccepted:
    """Drive the real Negotiation Engine state machine.

    Steady-state behaviour:

    * The graph runs ``analyze_target → compute_counter_offer →
      policy_guardrail_check`` in-process (a few milliseconds).
    * ``policy_guardrail_check`` enforces the **real** ``≤ 0.20`` hard
      cap from ``services/negotiation_engine/src/guardrails.py`` — no
      mocking.
    * The graph parks at ``wait_for_async_callback`` via ``interrupt()``.
    * We return 202 with the ``thread_id`` and the interrupt envelope so
      the front-end can render a "waiting for supplier" state.
    * A ``BackgroundTask`` is scheduled to resume the graph after
      ``callback_delay_s`` seconds with a ``Command(resume=payload)``
      whose shape is determined by ``simulated_outcome``.
    """
    graph = request.app.state.negotiation_graph
    transaction_id = req.transaction_id or f"txn-demo-{uuid.uuid4()}"
    config = {"configurable": {"thread_id": transaction_id}}

    # Validate each offer through the real Pydantic ``SupplierOffer`` so
    # the gateway exercises exactly the same input contract the real
    # state machine does. ``extra='allow'`` on the demo schema means we
    # forward unknown fields verbatim.
    try:
        validated_offers = [
            SupplierOffer.model_validate(o.model_dump()).model_dump()
            for o in req.ranked_offers
        ]
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid ranked_offers payload: {exc}",
        ) from exc

    initial_state: dict[str, Any] = {
        "transaction_id": transaction_id,
        "category": req.category,
        "ranked_candidates": validated_offers,
        "policy": req.policy,
        "negotiation_round": 0,
        "max_rounds": req.max_rounds,
    }

    logger.info(
        "Demo negotiate thread_id=%s category=%s offers=%d outcome=%s delay=%.2fs",
        transaction_id, req.category, len(validated_offers),
        req.simulated_outcome, req.callback_delay_s,
    )

    start = time.perf_counter()
    try:
        result = await graph.ainvoke(initial_state, config=config)
    except Exception as exc:
        logger.exception("Graph invocation failed for thread_id=%s", transaction_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Negotiation startup failed: {exc}",
        ) from exc
    elapsed_ms = (time.perf_counter() - start) * 1000.0

    interrupts = result.get("__interrupt__")
    paused_at = _first_pending_node(graph, config)

    # Register the thread in the gateway-side resumed-flag store so the
    # polling endpoint can distinguish "still parked" from "resumed".
    request.app.state.negotiation_resumed.setdefault(transaction_id, False)

    if interrupts:
        # Schedule the simulated /on_select callback. ``BackgroundTasks``
        # ensures FastAPI runs the coroutine *after* the response is sent.
        background_tasks.add_task(
            _resume_after_delay,
            request.app,
            transaction_id,
            req.callback_delay_s,
            req.simulated_outcome,
        )
        head_value = getattr(interrupts[0], "value", None) or {}
        return DemoNegotiateAccepted(
            thread_id=transaction_id,
            status="accepted",
            paused_at=paused_at,
            interrupt=head_value,
            final_outcome=None,
            callback_delay_s=req.callback_delay_s,
            simulated_outcome=req.simulated_outcome,
        )

    # No interrupt — terminated synchronously (advisory category, empty
    # candidates, etc.). Mark resumed so the polling endpoint surfaces
    # the terminal state immediately.
    request.app.state.negotiation_resumed[transaction_id] = True
    logger.info(
        "Demo negotiate thread_id=%s terminated synchronously in %.2f ms outcome=%s",
        transaction_id, elapsed_ms, result.get("final_outcome"),
    )
    return DemoNegotiateAccepted(
        thread_id=transaction_id,
        status="accepted",
        paused_at=None,
        interrupt=None,
        final_outcome=result.get("final_outcome"),
        callback_delay_s=req.callback_delay_s,
        simulated_outcome=req.simulated_outcome,
    )


@router.get(
    "/negotiate/{thread_id}",
    response_model=DemoNegotiateSnapshot,
    summary="Poll the current state of a running demo negotiation.",
)
async def get_negotiation(thread_id: str, request: Request) -> DemoNegotiateSnapshot:
    """Return the LangGraph checkpoint snapshot for ``thread_id``.

    The front-end polls this endpoint after issuing ``POST /negotiate``;
    typically the first poll within 3 s shows ``resumed=false`` and the
    graph parked at ``wait_for_async_callback``, and subsequent polls
    after the simulated callback fires show the terminal outcome.
    """
    graph = request.app.state.negotiation_graph
    config = {"configurable": {"thread_id": thread_id}}
    snapshot = graph.get_state(config)
    if not snapshot or not snapshot.values:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No checkpoint found for thread_id={thread_id}",
        )

    resumed = bool(request.app.state.negotiation_resumed.get(thread_id, False))

    return DemoNegotiateSnapshot(
        thread_id=thread_id,
        next=list(snapshot.next or ()),
        final_outcome=snapshot.values.get("final_outcome"),
        awaiting_on_select=snapshot.values.get("awaiting_on_select"),
        current_target=snapshot.values.get("current_target"),
        current_counter_offer=snapshot.values.get("current_counter_offer"),
        last_on_select_payload=snapshot.values.get("last_on_select_payload"),
        negotiation_round=int(snapshot.values.get("negotiation_round") or 0),
        audit_event_count=len(snapshot.values.get("audit_events") or []),
        resumed=resumed,
    )


__all__ = [
    "DEFAULT_CALLBACK_DELAY_S",
    "DemoNegotiateAccepted",
    "DemoNegotiateRequest",
    "DemoNegotiateOffer",
    "DemoNegotiateSnapshot",
    "router",
]
