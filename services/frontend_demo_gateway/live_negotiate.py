"""Live negotiation router — proxies to the real Negotiation Engine (:8004)
and drives the LLM supplier counter-party.

This replaces the old in-process ``mock_negotiate`` (which embedded the
LangGraph behind a ``MemorySaver``). The wiring is now production-shaped:

    Frontend ──/api/demo/negotiate──────▶ gateway ──HTTP──▶ engine :8004 (buyer agent)
                                                │
    Frontend ──/supplier-respond──▶ gateway ──▶ SupplierAgent (qwen3:8b via Ollama)
                                                │
                                                └─publish──▶ Redis(beckn_on_select_results)
                                                                       │
                                                            engine broker resumes the
                                                            parked LangGraph thread

The buyer (LangGraph) parks at ``wait_for_async_callback`` after drafting a
deterministic, guardrail-bounded counter-offer. The gateway asks the LLM
supplier to respond to that counter, then publishes the supplier's reply to
the Redis channel the engine's ``OnSelectListener`` subscribes to — resuming
the buyer for the next round.

Termination is controlled here (the engine's round loop is left untouched):
the engine is started with ``max_rounds=5`` and ``hitl_gap_pct=0.99`` so it
never self-escalates mid-demo; the gateway ends the session by publishing
``status="accepted"`` either when the supplier accepts or when the demo's own
round budget (``max_rounds``) is exhausted (buyer concedes to the supplier's
final counter).
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import httpx
from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field

from .config import CONFIG
from .supplier_agent import SupplierResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/demo", tags=["negotiation"])


def _date_from_hours(hours: int) -> str:
    """Render a delivery lead-time (the system's native unit) as an ISO date."""
    return (datetime.now(timezone.utc) + timedelta(hours=max(0, hours))).date().isoformat()


def _buyer_justification(counter: dict, category: str) -> str:
    """Synthesize a readable buyer message from the engine's counter-offer.

    The engine's ``current_counter_offer.rationale`` is a terse rule-engine tag;
    we turn its structured fields into a human sentence for the transcript
    WITHOUT calling an LLM or touching the engine.
    """
    disc = float(counter.get("discount_pct") or 0.0) * 100
    price = counter.get("target_price")
    qty = counter.get("target_quantity")
    price_txt = f"₹{float(price):.2f}/unit" if price is not None else "the proposed price"
    qty_txt = f"{qty} units" if qty is not None else "the order"
    return (
        f"Requesting {price_txt} for {qty_txt} — a {disc:.1f}% reduction within our "
        f"{category or 'category'} budget policy (hard-capped at 20% per guardrail G1)."
    )

# Engine policy that keeps the demo on the autonomous happy path: never
# self-escalate to a (non-existent) human, give plenty of round headroom.
_ENGINE_MAX_ROUNDS = 5
_ENGINE_HITL_GAP_PCT = 0.99
_PUBLISHED_GAP_PCT = 0.05  # always < hitl_gap_pct → never triggers escalation

_slug_re = re.compile(r"[^a-z0-9]+")


def _slug(text: str) -> str:
    return _slug_re.sub("-", text.strip().lower()).strip("-") or "item"


# ─────────────────────────────────────────────────────────────────────────
# Request / response models
# ─────────────────────────────────────────────────────────────────────────


class NegotiateKickoff(BaseModel):
    """Demo-friendly kickoff payload from the frontend."""

    supplier_id: str = Field(default="sup-001")
    supplier_name: str = Field(default="Acme Supplies")
    item: str = Field(..., min_length=1)
    quantity: int = Field(..., gt=0)
    target_price: float = Field(..., gt=0, description="Buyer's desired unit price.")
    list_price: Optional[float] = Field(
        default=None, description="Supplier catalog price (default = target × 1.2)."
    )
    delivery_hours: int = Field(default=72, ge=0)
    requested_delivery_date: Optional[str] = Field(
        default=None,
        description=(
            "Buyer's desired delivery date (ISO yyyy-mm-dd). Defaults to a date "
            "derived from delivery_hours when omitted."
        ),
    )
    category: str = Field(default="office_supplies")
    max_rounds: int = Field(default=3, ge=1, le=5)


class KickoffResult(BaseModel):
    thread_id: str
    status: str
    paused_at: Optional[str] = None
    buyer_counter_offer: Optional[dict] = None
    list_price: float
    target_price: float
    requested_delivery_date: str
    max_rounds: int


class NegotiationSnapshot(BaseModel):
    thread_id: str
    negotiation_round: int
    rounds_elapsed: int
    max_rounds: int
    awaiting_supplier: bool
    final_outcome: Optional[str] = None
    buyer_counter_offer: Optional[dict] = None
    list_price: float
    target_price: float
    requested_delivery_date: str
    agreed_delivery_date: Optional[str] = None
    item: str
    history: list[dict]


# ─────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────


def _sessions(request: Request) -> dict[str, dict]:
    return request.app.state.negotiation_sessions


def _engine(request: Request) -> httpx.AsyncClient:
    return request.app.state.engine_client


async def _engine_state(client: httpx.AsyncClient, thread_id: str) -> Optional[dict]:
    """Fetch the buyer graph's current state; None if not found (404)."""
    try:
        resp = await client.get(f"/negotiate/{thread_id}")
    except httpx.HTTPError as exc:  # pragma: no cover — engine down
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Negotiation Engine unreachable: {exc}",
        )
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    return resp.json()


# ─────────────────────────────────────────────────────────────────────────
# Endpoints
# ─────────────────────────────────────────────────────────────────────────


@router.post("/negotiate", response_model=KickoffResult, status_code=status.HTTP_202_ACCEPTED)
async def kickoff(req: NegotiateKickoff, request: Request) -> KickoffResult:
    """Start a real LangGraph negotiation on the engine; return the buyer's
    first counter-offer once the graph parks at ``wait_for_async_callback``."""
    import uuid

    thread_id = f"demo-{uuid.uuid4()}"
    list_price = req.list_price if req.list_price else round(req.target_price * 1.2, 2)
    requested_delivery_date = req.requested_delivery_date or _date_from_hours(
        req.delivery_hours
    )

    offer = {
        "provider_id": req.supplier_id,
        "item_id": _slug(req.item),
        "price": list_price,
        "currency": "INR",
        "delivery_hours": req.delivery_hours,
        "quantity": req.quantity,
        "score": 1.0,
    }
    engine_req = {
        "transaction_id": thread_id,
        "category": req.category,
        "ranked_offers": [offer],
        "policy": {
            "budget_unit_price": req.target_price,
            "hitl_gap_pct": _ENGINE_HITL_GAP_PCT,
            "category_max_discount_pct": 0.20,
            "supplier_max_discount_pct": 0.20,
        },
        "max_rounds": _ENGINE_MAX_ROUNDS,
    }

    client = _engine(request)
    try:
        resp = await client.post("/negotiate", json=engine_req)
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        logger.exception("Engine kickoff failed for %s", thread_id)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Negotiation Engine kickoff failed: {exc}",
        )
    accepted = resp.json()
    interrupt = accepted.get("interrupt") or {}
    buyer_counter = interrupt.get("counter_offer")

    _sessions(request)[thread_id] = {
        "supplier_id": req.supplier_id,
        "supplier_name": req.supplier_name,
        "item": req.item,
        "quantity": req.quantity,
        "list_price": list_price,
        "target_price": req.target_price,
        "category": req.category,
        "requested_delivery_date": requested_delivery_date,
        "agreed_delivery_date": None,
        "max_rounds": req.max_rounds,
        "rounds_elapsed": 0,
        "history": [],
    }

    logger.info(
        "Negotiation kickoff thread_id=%s item=%s list=%.2f target=%.2f paused_at=%s",
        thread_id,
        req.item,
        list_price,
        req.target_price,
        accepted.get("paused_at"),
    )

    return KickoffResult(
        thread_id=thread_id,
        status=accepted.get("status", "accepted"),
        paused_at=accepted.get("paused_at"),
        buyer_counter_offer=buyer_counter,
        list_price=list_price,
        target_price=req.target_price,
        requested_delivery_date=requested_delivery_date,
        max_rounds=req.max_rounds,
    )


@router.get("/negotiate/{thread_id}", response_model=NegotiationSnapshot)
async def poll(thread_id: str, request: Request) -> NegotiationSnapshot:
    """Poll the buyer graph + gateway session for the current negotiation state."""
    session = _sessions(request).get(thread_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"Unknown thread_id={thread_id}")

    state = await _engine_state(_engine(request), thread_id)
    if state is None:
        raise HTTPException(
            status_code=404, detail=f"No engine checkpoint for {thread_id}"
        )

    next_nodes = state.get("next") or []
    awaiting = "wait_for_async_callback" in next_nodes
    final_outcome = state.get("final_outcome")

    return NegotiationSnapshot(
        thread_id=thread_id,
        negotiation_round=int(state.get("negotiation_round") or 0),
        rounds_elapsed=session["rounds_elapsed"],
        max_rounds=session["max_rounds"],
        awaiting_supplier=awaiting and final_outcome is None,
        final_outcome=final_outcome,
        buyer_counter_offer=state.get("current_counter_offer"),
        list_price=session["list_price"],
        target_price=session["target_price"],
        requested_delivery_date=session["requested_delivery_date"],
        agreed_delivery_date=session.get("agreed_delivery_date"),
        item=session["item"],
        history=session["history"],
    )


@router.post("/negotiate/{thread_id}/supplier-respond")
async def supplier_respond(thread_id: str, request: Request) -> dict[str, Any]:
    """Ask the qwen3:8b supplier to respond to the buyer's current counter-offer,
    then publish the reply to Redis to resume the parked buyer graph."""
    session = _sessions(request).get(thread_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"Unknown thread_id={thread_id}")

    state = await _engine_state(_engine(request), thread_id)
    if state is None:
        raise HTTPException(status_code=404, detail=f"No engine checkpoint for {thread_id}")

    if state.get("final_outcome"):
        return {"done": True, "final_outcome": state["final_outcome"]}

    counter = state.get("current_counter_offer") or {}
    buyer_ask = float(counter.get("target_price") or session["target_price"])
    requested_delivery_date = session["requested_delivery_date"]

    agent = request.app.state.supplier_agent
    round_no = session["rounds_elapsed"] + 1
    max_rounds = session["max_rounds"]

    # Previous supplier counter (if any) so the LLM concedes from it.
    prev_price = None
    for turn in reversed(session["history"]):
        if turn.get("supplier_price"):
            prev_price = float(turn["supplier_price"])
            break

    supplier: SupplierResponse = await agent.respond(
        item=session["item"],
        quantity=session["quantity"],
        list_price=session["list_price"],
        buyer_target_price=buyer_ask,
        round_no=round_no,
        max_rounds=max_rounds,
        previous_offer=prev_price,
        requested_delivery_date=requested_delivery_date,
    )

    # Safety clamp: guarantee visible concession even if the model holds firm.
    # A counter must beat its own previous offer (move toward the buyer).
    if (
        supplier.action == "counter"
        and prev_price is not None
        and supplier.counter_price is not None
        and supplier.counter_price >= prev_price
    ):
        stepped = round(max(buyer_ask, prev_price - (prev_price - buyer_ask) * 0.4), 2)
        supplier = supplier.model_copy(update={"counter_price": stepped})

    supplier_delivery = supplier.proposed_delivery_date or requested_delivery_date

    is_final = round_no >= max_rounds
    # Decide the resume signal for the buyer graph.
    if supplier.action == "accept":
        resume_status = "accepted"
        agreed_price = buyer_ask
        agreed_delivery_date = supplier_delivery
    elif is_final:
        # Demo budget exhausted → buyer concedes to the supplier's final price.
        resume_status = "accepted"
        agreed_price = supplier.counter_price or session["list_price"]
        agreed_delivery_date = supplier_delivery
    else:
        resume_status = "counter"
        agreed_price = supplier.counter_price or session["list_price"]
        agreed_delivery_date = None

    redis_payload = {
        "transaction_id": thread_id,
        "status": resume_status,
        "action": supplier.action,
        "proposed_price": agreed_price,
        "gap_pct": _PUBLISHED_GAP_PCT,
        "supplier_id": session["supplier_id"],
        "message": supplier.message,
        "source": supplier.source,
        "round_no": round_no,
    }

    try:
        await request.app.state.redis.publish(
            CONFIG.redis_on_select_channel, json.dumps(redis_payload)
        )
    except Exception as exc:  # pragma: no cover — redis down
        logger.exception("Failed to publish supplier response for %s", thread_id)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Redis publish failed: {exc}",
        )

    session["rounds_elapsed"] = round_no
    if resume_status == "accepted":
        session["agreed_delivery_date"] = agreed_delivery_date

    # Humanize the buyer's (engine-decided) offer via the LLM — natural wording,
    # same numbers. Falls back to the deterministic template on any failure.
    buyer_message = await agent.humanize_buyer_offer(
        item=session["item"],
        quantity=session["quantity"],
        list_price=session["list_price"],
        target_price=buyer_ask,
        delivery_date=requested_delivery_date,
        discount_pct=float(counter.get("discount_pct") or 0.0),
        round_no=round_no,
        max_rounds=max_rounds,
    )

    turn = {
        "round_no": round_no,
        # ── Buyer side (full message; numbers from the engine, wording from LLM) ──
        "buyer_price_offer": buyer_ask,
        "buyer_delivery_offer": requested_delivery_date,
        "buyer_quantity": session["quantity"],
        "buyer_justification": buyer_message,
        # ── Supplier side (qwen3:8b) ──
        "supplier_action": supplier.action,
        "supplier_price": agreed_price if supplier.action != "reject" else None,
        "proposed_delivery_date": supplier_delivery,
        "supplier_message": supplier.message,
        "source": supplier.source,
        "resume_status": resume_status,
        # legacy alias kept for any older client
        "buyer_ask": buyer_ask,
    }
    session["history"].append(turn)

    logger.info(
        "Supplier turn thread_id=%s round=%d buyer_ask=%.2f action=%s price=%s "
        "resume=%s source=%s model=%s",
        thread_id,
        round_no,
        buyer_ask,
        supplier.action,
        agreed_price,
        resume_status,
        supplier.source,
        supplier.model,
    )

    return {
        "done": resume_status == "accepted",
        "round_no": round_no,
        "buyer_ask": buyer_ask,
        "supplier": supplier.model_dump(),
        "agreed_price": agreed_price if resume_status == "accepted" else None,
        "agreed_delivery_date": agreed_delivery_date if resume_status == "accepted" else None,
        "resume_status": resume_status,
        "model": supplier.model,
    }


__all__ = ["router"]
