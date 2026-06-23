"""Concrete LangGraph node implementations.

This module ships the *brains* of the engine — the node bodies that
:func:`.graph.build_graph` wires into the StateGraph. The topology
(node registration, conditional edges, compile) lives in ``graph.py``;
this module is the *node library*.

Step 1 of the implementation plan placed placeholder bodies directly in
``graph.py``. Step 2 (this file) replaces them with real logic that
calls into:

* ``memory.py``    — Qdrant-backed supplier history retrieval.
* ``strategy.py``  — Phase-1 rule engine (Phase-2 bandit hooks marked).
* ``guardrails.py`` — the **unmodified** deterministic shield from Step 1.

A new node — :func:`evaluate_ambiguous_terms` — uses LangChain's
``ChatOpenAI`` (gpt-4o) for NLP review of warranty / SLA / delivery
terms when the category is advisory-only (IT equipment, medical
devices). It is the *only* LLM call inside the engine and is strictly
non-pricing — it reads terms and writes prose, never numbers on the wire.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from langgraph.types import interrupt

from .audit import log_negotiation_event_sync
from .config import CONFIG
from .guardrails import PolicyViolationError, validate_counter_offer
from .memory import get_supplier_negotiation_history
from .models import (
    ABSOLUTE_MAX_DISCOUNT_PCT,
    AuditEvent,
    CounterOffer,
    NegotiationState,
    SupplierOffer,
)
from .strategy import compute_target_discount, is_advisory_only

logger = logging.getLogger(__name__)


# ── LLM client (lazy, advisory node only) ─────────────────────────────────

# Lazily-instantiated ChatOpenAI singleton. Importing ``langchain_openai``
# triggers a non-trivial dependency graph, so we defer until the advisory
# path is actually exercised AND an API key is configured.
_LLM_INSTANCE: Any | None = None


def _get_llm() -> Any | None:
    """Return the lazy ChatOpenAI instance, or ``None`` if not configured.

    Falls open: if ``OPENAI_API_KEY`` is unset (CI / dev), advisory nodes
    emit a placeholder summary so the graph stays runnable end-to-end.
    """
    global _LLM_INSTANCE
    if _LLM_INSTANCE is not None:
        return _LLM_INSTANCE
    if not CONFIG.openai_api_key:
        logger.info(
            "OPENAI_API_KEY not set — advisory node will emit placeholder analysis"
        )
        return None
    try:
        from langchain_openai import ChatOpenAI  # pragma: no cover

        _LLM_INSTANCE = ChatOpenAI(
            model=CONFIG.openai_model,
            api_key=CONFIG.openai_api_key,
            base_url=CONFIG.openai_base_url,  # local Claude Code proxy
            timeout=CONFIG.openai_timeout_s,
            max_tokens=CONFIG.advisory_max_tokens,
        )
        return _LLM_INSTANCE
    except Exception as exc:  # pragma: no cover — defensive
        logger.error("Failed to instantiate ChatOpenAI: %s", exc)
        return None


# ── Internal helpers ──────────────────────────────────────────────────────


def _utcnow_iso() -> str:
    """Return current UTC time as an ISO-8601 string."""
    return datetime.now(timezone.utc).isoformat()


def _audit(node: str, kind: str, **detail: Any) -> AuditEvent:
    """Construct an ``AuditEvent`` in the canonical shape."""
    return {"ts": _utcnow_iso(), "node": node, "kind": kind, "detail": detail}


# ─────────────────────────────────────────────────────────────────────────
# Node — analyze_target
# ─────────────────────────────────────────────────────────────────────────


def analyze_target(state: NegotiationState) -> dict:
    """Pop the head of ``ranked_candidates`` and pull supplier history.

    Side-effects: appends the selected ``provider_id`` and chosen strategy
    archetype to the audit log; eagerly retrieves the supplier's
    negotiation history from Qdrant (or the synthetic fallback when no
    client is wired) and stashes it inside ``current_strategy["history"]``
    so downstream nodes don't have to re-query.

    The category drives the archetype:
        * advisory categories (IT equipment, medical) → ``advisory_only``
          archetype → graph routes to ``evaluate_ambiguous_terms``;
        * everything else → ``counter_offer`` archetype → graph routes to
          ``compute_counter_offer``.
    """
    candidates = list(state.get("ranked_candidates") or [])
    if not candidates:
        return {
            "current_target": None,
            "audit_events": [_audit("analyze_target", "candidates_exhausted")],
        }

    head = candidates[0]
    remaining = candidates[1:]
    provider_id = head.get("provider_id", "") if isinstance(head, dict) else ""
    category = str(state.get("category") or "")

    # Pull this supplier's prior outcomes. ``qdrant_client=None`` triggers
    # the synthetic fallback per ``memory.py``; the production wiring step
    # will plug a real client in here.
    history = get_supplier_negotiation_history(
        supplier_id=provider_id,
        qdrant_client=None,
    )

    archetype = "advisory_only" if is_advisory_only(category) else "counter_offer"
    strategy: dict[str, Any] = {
        "name": archetype,
        "category": category,
        "history": history,
        "provider_id": provider_id,
    }

    return {
        "current_target": head,
        "current_strategy": strategy,
        "ranked_candidates": remaining,
        "audit_events": [
            _audit(
                "analyze_target",
                "candidate_selected",
                provider_id=provider_id,
                archetype=archetype,
                category=category,
                history_chars=len(history),
            ),
        ],
    }


# ─────────────────────────────────────────────────────────────────────────
# Node — compute_counter_offer
# ─────────────────────────────────────────────────────────────────────────


def compute_counter_offer(state: NegotiationState) -> dict:
    """Draft a counter-offer via the rule-based strategy engine.

    Pulls the supplier offer + history from ``current_strategy``, asks
    ``compute_target_discount`` for the target discount, and builds a
    fully-validated ``CounterOffer`` Pydantic object (L1 of the shield).

    No LLM, no I/O — just deterministic math. The L2 deterministic shield
    still runs after this node (in ``policy_guardrail_check``); the
    pre-decision shielding inside ``compute_target_discount`` is the
    defence-in-depth first cut.
    """
    target_dict = state.get("current_target") or {}
    strategy = state.get("current_strategy") or {}
    policy = state.get("policy") or {}

    if not target_dict:
        return {
            "current_counter_offer": None,
            "audit_events": [_audit("compute_counter_offer", "no_target")],
        }

    try:
        target = SupplierOffer.model_validate(target_dict)
    except Exception as exc:
        logger.warning("Invalid supplier offer in state: %s", exc)
        return {
            "current_counter_offer": None,
            "escalation_reason": "invalid_target",
            "audit_events": [
                _audit(
                    "compute_counter_offer",
                    "invalid_target",
                    error=str(exc),
                )
            ],
        }

    category = str(strategy.get("category") or state.get("category") or "")
    history = str(strategy.get("history") or "")
    budget = float(policy.get("budget_unit_price") or target.price)

    discount = compute_target_discount(
        category=category,
        historical_context=history,
        price=target.price,
        budget=budget,
        policy=policy,
    )

    # Pydantic ``CounterOffer`` re-validates ``discount_pct ∈ [0, 0.20]``
    # (L1 of the guardrail stack) — a bug in ``compute_target_discount``
    # that returned, say, 0.25 would raise here before the offer ever
    # reaches the wire.
    counter = CounterOffer(
        target_price=round(target.price * (1.0 - discount), 4),
        target_delivery_hours=target.delivery_hours,
        target_quantity=target.quantity,
        discount_pct=discount,
        rationale=(
            f"phase1_rule_engine:category={category or 'unknown'}:"
            f"discount={discount:.4f}:hard_cap={ABSOLUTE_MAX_DISCOUNT_PCT}"
        ),
    )

    round_no = int(state.get("negotiation_round") or 0)
    txn = str(state.get("transaction_id") or "")
    log_negotiation_event_sync(
        session_id=txn,
        event_type="counter_offer_drafted",
        payload={
            "round_no": round_no,
            "provider_id": target.provider_id,
            "discount_pct": discount,
            "target_price": counter.target_price,
            "category": category,
        },
        idempotency_key=f"{txn}:counter_drafted:{round_no}",
    )

    return {
        "current_counter_offer": counter.model_dump(),
        "audit_events": [
            _audit(
                "compute_counter_offer",
                "counter_drafted",
                discount_pct=discount,
                target_price=counter.target_price,
                category=category,
            ),
        ],
    }


# ─────────────────────────────────────────────────────────────────────────
# Node — policy_guardrail_check
# ─────────────────────────────────────────────────────────────────────────


def policy_guardrail_check(state: NegotiationState) -> dict:
    """Layer-2 deterministic policy shield.

    **The guardrail logic itself is NOT modified in Step 2.** This node
    is a thin wrapper that drives ``validate_counter_offer`` — the
    canonical L2 enforcement point lives in ``guardrails.py`` and any
    business-rule change goes there, never here.

    On violation: sets ``escalation_reason = "guardrail_violation:G{n}"``
    so the conditional edge routes to ``human_escalation``; emits a
    structured audit event suitable for direct Kafka emission.
    """
    proposed_dict = state.get("current_counter_offer")
    policy = state.get("policy") or {}

    if not proposed_dict:
        return {
            "escalation_reason": "guardrail_no_offer",
            "audit_events": [
                _audit("policy_guardrail_check", "no_offer_to_validate")
            ],
        }

    try:
        proposed = CounterOffer.model_validate(proposed_dict)
    except Exception as exc:  # noqa: BLE001 — convert any L1 error to violation.
        logger.warning("L1 Pydantic rejection in guardrail node: %s", exc)
        return {
            "escalation_reason": "guardrail_violation:L1",
            "audit_events": [
                _audit(
                    "policy_guardrail_check",
                    "policy_violation_blocked",
                    source_layer="L1",
                    error=str(exc),
                ),
            ],
        }

    try:
        validate_counter_offer(proposed, policy)
    except PolicyViolationError as exc:
        logger.warning("L2 policy violation: %s", exc)
        txn = str(state.get("transaction_id") or "")
        round_no = int(state.get("negotiation_round") or 0)
        # Mirror to Kafka — the policy_violations.v1 side-topic is
        # subscribed by compliance/alerting (audit.py handles routing).
        log_negotiation_event_sync(
            session_id=txn,
            event_type="policy_violation_blocked",
            payload={
                "source_layer": "L2",
                "round_no": round_no,
                "severity": "HIGH",
                **exc.to_audit_payload(),
            },
            idempotency_key=f"{txn}:policy_violation:{exc.rule_id}:{round_no}",
        )
        return {
            "escalation_reason": f"guardrail_violation:{exc.rule_id}",
            "audit_events": [
                _audit(
                    "policy_guardrail_check",
                    "policy_violation_blocked",
                    source_layer="L2",
                    **exc.to_audit_payload(),
                ),
            ],
        }

    return {
        "audit_events": [
            _audit(
                "policy_guardrail_check",
                "guardrail_passed",
                discount_pct=proposed.discount_pct,
                hard_cap=ABSOLUTE_MAX_DISCOUNT_PCT,
            ),
        ],
    }


# ─────────────────────────────────────────────────────────────────────────
# Node — evaluate_ambiguous_terms  (NEW in Step 2 — LLM-driven NLP review)
# ─────────────────────────────────────────────────────────────────────────


_ADVISORY_SYSTEM_PROMPT = (
    "You are a procurement advisor reviewing supplier listings for "
    "regulated or specialized categories. Read the supplier description, "
    "warranty terms, and delivery conditions. Flag any ambiguity, risk, "
    "or non-standard clause that warrants human review. "
    "DO NOT propose discounts, prices, or counter-offers — your role is "
    "purely to interpret and surface ambiguity in terms. Output 2-3 "
    "sentences of plain prose."
)


def _build_advisory_human_prompt(
    target: dict[str, Any], history: str
) -> str:
    """Compose the user-side prompt for the advisory LLM call."""
    descriptor = target.get("descriptor") or {}
    return (
        "Supplier listing:\n"
        f"  Provider: {target.get('provider_id', 'unknown')}\n"
        f"  Item ID: {target.get('item_id', 'unknown')}\n"
        f"  Listed price: {target.get('price')} {target.get('currency', 'INR')}\n"
        f"  Delivery hours: {target.get('delivery_hours')}\n"
        f"  Description: {descriptor.get('long_desc', '(none provided)')}\n"
        f"  Warranty: {descriptor.get('warranty', '(none stated)')}\n"
        f"  SLA: {descriptor.get('sla', '(none stated)')}\n"
        "\n"
        "Past supplier behaviour summary:\n"
        f"{history or '(no prior history)'}\n"
        "\n"
        "Provide a concise 2-3 sentence advisory flagging ambiguity or risk."
    )


def evaluate_ambiguous_terms(state: NegotiationState) -> dict:
    """LLM-driven NLP review of warranty / SLA / delivery terms.

    Activated **only** when ``current_strategy.name == "advisory_only"``
    (e.g. IT equipment, medical devices). Uses LangChain's ``ChatOpenAI``
    (gpt-4o) to analyse the supplier's listing and emit a recommendation.
    Critically:

    * It **never** proposes a discount or price. Term review only.
    * It does **not** dispatch a Beckn ``/select``. The category mandates
      a recommendation, not a transaction.
    * On missing API key or LLM error, it emits a placeholder so the
      graph still progresses to ``finalize`` cleanly.
    """
    target = state.get("current_target") or {}
    strategy = state.get("current_strategy") or {}
    history = str(strategy.get("history") or "")

    llm = _get_llm()
    if llm is None:
        advisory_text = (
            "ADVISORY (placeholder — LLM not configured): this category "
            "mandates human review of warranty/SLA terms before any "
            "commercial commitment. No counter-offer dispatched."
        )
        return {
            "final_outcome": "escalated",
            "messages": [{"role": "assistant", "content": advisory_text}],
            "audit_events": [
                _audit(
                    "evaluate_ambiguous_terms",
                    "advisory_placeholder",
                    reason="no_openai_api_key",
                ),
            ],
        }

    human_prompt = _build_advisory_human_prompt(target, history)
    try:
        response = llm.invoke(
            [
                {"role": "system", "content": _ADVISORY_SYSTEM_PROMPT},
                {"role": "user", "content": human_prompt},
            ]
        )
        advisory_text = getattr(response, "content", None) or str(response)
    except Exception as exc:  # pragma: no cover — LLM call defensive
        logger.warning("ChatOpenAI invocation failed: %s", exc)
        advisory_text = (
            f"ADVISORY (LLM error: {exc}): falling back to placeholder. "
            "Human review required."
        )

    return {
        "final_outcome": "escalated",
        "messages": [{"role": "assistant", "content": advisory_text}],
        "audit_events": [
            _audit(
                "evaluate_ambiguous_terms",
                "advisory_generated",
                length_chars=len(advisory_text),
                model=CONFIG.openai_model,
            ),
        ],
    }


# ─────────────────────────────────────────────────────────────────────────
# Auxiliary nodes — still placeholders (LLM + Redis wiring in Step 3+).
# ─────────────────────────────────────────────────────────────────────────


def wait_for_async_callback(state: NegotiationState) -> dict:
    """Dispatch ``/select`` and **park the graph** via :func:`interrupt`.

    This is the canonical *machine* interrupt site (architecture
    ``01_langgraph_state_machine`` §async-interrupt-mechanics): Beckn
    ``/select`` returns an ACK only, so the engine has nothing useful
    to do until the BPP's ``/on_select`` webhook arrives. The runtime:

    1. Persists a checkpoint with ``awaiting_on_select=True`` (via the
       compiled checkpointer — typically ``AsyncPostgresSaver``).
    2. Calls :func:`langgraph.types.interrupt` with a structured
       envelope describing what we're waiting for.
    3. ``Pregel`` propagates ``GraphInterrupt`` up; the ``ainvoke()``
       caller sees ``{"__interrupt__": [Interrupt(...)]}`` and returns.

    The resume side is owned by :mod:`broker` — when a ``/on_select``
    payload arrives on ``beckn_on_select_results``, the broker invokes
    ``graph.ainvoke(Command(resume=payload), config={"configurable":
    {"thread_id": transaction_id}})``. LangGraph replays this node's
    body, ``interrupt()`` returns the resume value, and execution
    continues from the next line.

    .. note::
        Code **before** ``interrupt()`` runs on initial invocation
        *and* on every resume. For idempotency, we keep pre-interrupt
        side-effects to a deterministic Kafka emit with a stable
        ``idempotency_key`` so duplicate audit events de-duplicate at
        the consumer.
    """
    correlation_id = state.get("transaction_id", "") or ""
    redis_channel = (
        f"{CONFIG.redis_on_select_channel}:{correlation_id}" if correlation_id else None
    )
    round_no = int(state.get("negotiation_round") or 0)
    counter = state.get("current_counter_offer") or {}

    # ── Pre-interrupt: emit "counter_offer_dispatched" audit. The Kafka
    # send is idempotency-keyed by (txn, round) so repeated replays
    # collapse on the consumer side.
    log_negotiation_event_sync(
        session_id=correlation_id,
        event_type="counter_offer_dispatched",
        payload={
            "round_no": round_no,
            "redis_channel": redis_channel,
            "counter_offer": counter,
        },
        idempotency_key=f"{correlation_id}:counter_dispatched:{round_no}",
    )

    # ── Park the graph. The dict passed to interrupt() is surfaced to
    # the broker / HITL UI as the interrupt's ``value`` — it's both a
    # human-readable message and a structured handle.
    payload: Any = interrupt(
        {
            "type": "negotiation.awaiting_on_select",
            "message": "Waiting for /on_select from BPP...",
            "correlation_id": correlation_id,
            "redis_channel": redis_channel,
            "round_no": round_no,
            "counter_offer": counter,
        }
    )

    # ── Resume side: ``payload`` is whatever the broker passed via
    # ``Command(resume=...)`` — defensively coerce to a dict.
    if not isinstance(payload, dict):
        logger.warning(
            "wait_for_async_callback resumed with non-dict payload: %r", payload
        )
        payload = {"status": "no_response", "raw": payload}

    log_negotiation_event_sync(
        session_id=correlation_id,
        event_type="on_select_received",
        payload={
            "round_no": round_no,
            "status": payload.get("status"),
            "received_at": _utcnow_iso(),
        },
        idempotency_key=f"{correlation_id}:on_select:{round_no}",
    )

    return {
        "awaiting_on_select": False,
        "on_select_correlation_id": correlation_id,
        "redis_channel": redis_channel,
        "last_on_select_payload": payload,
        "audit_events": [
            _audit(
                "wait_for_async_callback",
                "on_select_received",
                correlation_id=correlation_id,
                status=payload.get("status"),
            ),
        ],
    }


def evaluate_response(state: NegotiationState) -> dict:
    """Classify the ``/on_select`` payload and advance the round counter.

    Placeholder: always treats the payload as a counter (the synthetic
    callback never says "accepted") and increments the round counter so
    the bounded-loop guard at ``round + 1 ≥ max_rounds`` will eventually
    terminate the cycle.
    """
    round_no = int(state.get("negotiation_round") or 0)
    next_round = round_no + 1
    payload = state.get("last_on_select_payload") or {}
    return {
        "negotiation_round": next_round,
        "round_history": [
            {
                "round_no": next_round,
                "provider_id": (state.get("current_target") or {}).get("provider_id", ""),
                "sent": state.get("current_counter_offer") or {},
                "received": payload,
                "decision": "counter",
                "elapsed_ms": 0,
            }
        ],
        "audit_events": [
            _audit("evaluate_response", "round_evaluated", round_no=next_round),
        ],
    }


def human_escalation(state: NegotiationState) -> dict:
    """HITL interrupt — park until ``approval_workflow`` resumes via ``Command(resume=...)``.

    Distinct from the machine interrupt in :func:`wait_for_async_callback`:
    payload shape, deadline horizon (hours / days vs. ~3 minutes), and
    resume source differ by orders of magnitude. The architecture
    forbids unifying them (``01_langgraph_state_machine`` §async-interrupt-mechanics).
    """
    txn = str(state.get("transaction_id") or "")
    reason = state.get("escalation_reason") or "unspecified"
    round_no = int(state.get("negotiation_round") or 0)

    # Pre-interrupt audit emit. Idempotency key collapses replays.
    log_negotiation_event_sync(
        session_id=txn,
        event_type="escalated_to_human",
        payload={
            "reason": reason,
            "round_no": round_no,
            "current_target": state.get("current_target"),
            "current_counter_offer": state.get("current_counter_offer"),
        },
        idempotency_key=f"{txn}:escalated:{round_no}:{reason}",
    )

    # Park the graph. Surface a clear, structured payload to the HITL UI.
    decision: Any = interrupt(
        {
            "type": "negotiation.hitl_required",
            "message": "Waiting for procurement manager approval...",
            "transaction_id": txn,
            "reason": reason,
            "negotiation_round": round_no,
            "current_target": state.get("current_target"),
            "current_counter_offer": state.get("current_counter_offer"),
        }
    )

    # Resume side. The approval_workflow service is expected to call
    # ``Command(resume={"action": "accept|reject|override", ...})``.
    normalised = decision if isinstance(decision, dict) else {"action": "reject"}

    log_negotiation_event_sync(
        session_id=txn,
        event_type="human_decision_recorded",
        payload={
            "round_no": round_no,
            "action": normalised.get("action"),
            "reviewer": normalised.get("reviewer"),
            "reasoning": normalised.get("reasoning"),
        },
        idempotency_key=f"{txn}:hitl_decision:{round_no}",
    )

    return {
        "hitl_decision": normalised,
        "escalation_reason": None,
        "audit_events": [
            _audit(
                "human_escalation",
                "human_decision_recorded",
                action=normalised.get("action"),
                reviewer=normalised.get("reviewer"),
            ),
        ],
    }


def timeout_handler(state: NegotiationState) -> dict:
    """Deadletter terminal stamp."""
    return {
        "final_outcome": "timed_out",
        "audit_events": [_audit("timeout_handler", "timeout_fired")],
    }


def finalize(state: NegotiationState) -> dict:
    """Terminal node — stamp the outcome and emit the closing audit event.

    Qdrant upsert of the ``NegotiationMemory`` document lands in the
    next implementation step (the Phase-3 learning flywheel).
    """
    outcome = state.get("final_outcome") or "accepted"
    txn = str(state.get("transaction_id") or "")

    log_negotiation_event_sync(
        session_id=txn,
        event_type="outcome_received",
        payload={
            "final_outcome": outcome,
            "rounds_used": int(state.get("negotiation_round") or 0),
            "final_target": state.get("current_target"),
            "final_counter_offer": state.get("current_counter_offer"),
        },
        idempotency_key=f"{txn}:outcome",
    )

    return {
        "final_outcome": outcome,
        "audit_events": [_audit("finalize", "outcome_received", outcome=outcome)],
    }


__all__ = [
    "analyze_target",
    "compute_counter_offer",
    "evaluate_ambiguous_terms",
    "evaluate_response",
    "finalize",
    "human_escalation",
    "policy_guardrail_check",
    "timeout_handler",
    "wait_for_async_callback",
]
