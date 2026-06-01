"""LangGraph topology — Negotiation Engine ``StateGraph`` factory.

This module is intentionally thin: it imports the concrete node bodies
from :mod:`.nodes`, registers them, and wires the conditional-edge
routers that match the edge table in
``KnowledgeBase/project_scaffold/architecture/negotiation_engine/01_langgraph_state_machine.md``.

Step 2 adds one new node — :func:`.nodes.evaluate_ambiguous_terms` — and
one new branch from ``analyze_target``:

* When ``current_strategy.name == "advisory_only"`` (IT equipment,
  medical devices) the graph routes ``analyze_target →
  evaluate_ambiguous_terms → finalize`` and **skips** the
  counter-offer + dispatch path entirely.

All other transitions are unchanged from Step 1.
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Optional

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from .config import CONFIG
from .models import NegotiationState
from .nodes import (
    analyze_target,
    compute_counter_offer,
    evaluate_ambiguous_terms,
    evaluate_response,
    finalize,
    human_escalation,
    policy_guardrail_check,
    timeout_handler,
    wait_for_async_callback,
)

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────
# Conditional-edge routers
# ─────────────────────────────────────────────────────────────────────────


def _route_from_analyze_target(state: NegotiationState) -> str:
    """Route based on chosen strategy archetype and candidate availability."""
    if not state.get("current_target"):
        return "finalize"
    strategy = state.get("current_strategy") or {}
    if strategy.get("name") == "advisory_only":
        return "evaluate_ambiguous_terms"
    return "compute_counter_offer"


def _route_from_policy_guardrail_check(state: NegotiationState) -> str:
    """L2 violation → HITL; otherwise dispatch /select."""
    return "human_escalation" if state.get("escalation_reason") else "wait_for_async_callback"


def _route_from_wait_for_async_callback(state: NegotiationState) -> str:
    """Timeout / no-response → deadletter; otherwise evaluate /on_select."""
    payload = state.get("last_on_select_payload") or {}
    status = payload.get("status")
    if status in {"timeout", "no_response"}:
        return "timeout_handler"
    return "evaluate_response"


def _route_from_evaluate_response(state: NegotiationState) -> str:
    """Accept → finalize; bounded counter loop → analyze_target; gap > HITL → escalate."""
    payload = state.get("last_on_select_payload") or {}
    if payload.get("status") == "accepted":
        return "finalize"

    round_no = int(state.get("negotiation_round") or 0)
    max_rounds = int(state.get("max_rounds") or 3)
    policy = state.get("policy") or {}
    hitl_gap_pct = float(policy.get("hitl_gap_pct") or 0.15)
    observed_gap = float(payload.get("gap_pct") or 0.0)

    if observed_gap > hitl_gap_pct:
        return "human_escalation"
    if round_no >= max_rounds:
        return "human_escalation"
    return "analyze_target"


def _route_from_human_escalation(state: NegotiationState) -> str:
    """HITL approval override → re-dispatch; otherwise finalize."""
    decision = state.get("hitl_decision") or {}
    action = decision.get("action", "reject")
    if action == "override":
        return "wait_for_async_callback"
    return "finalize"


# ─────────────────────────────────────────────────────────────────────────
# Graph builder
# ─────────────────────────────────────────────────────────────────────────


def build_graph(checkpointer: Optional[BaseCheckpointSaver] = None):
    """Construct and compile the Negotiation Engine ``StateGraph``.

    Parameters
    ----------
    checkpointer:
        Optional LangGraph checkpoint saver. Production wires
        ``AsyncPostgresSaver``; tests typically pass ``MemorySaver``;
        ``None`` compiles a stateless graph (note: ``interrupt()`` needs
        a checkpointer at *runtime*, even if the graph compiles without one).

    Returns
    -------
    CompiledStateGraph
        Runnable LangGraph object exposing ``invoke`` / ``ainvoke`` /
        ``stream`` / ``astream``.
    """
    builder = StateGraph(NegotiationState)

    # --- node registration ---
    builder.add_node("analyze_target", analyze_target)
    builder.add_node("compute_counter_offer", compute_counter_offer)
    builder.add_node("policy_guardrail_check", policy_guardrail_check)
    builder.add_node("wait_for_async_callback", wait_for_async_callback)
    builder.add_node("evaluate_response", evaluate_response)
    builder.add_node("human_escalation", human_escalation)
    builder.add_node("evaluate_ambiguous_terms", evaluate_ambiguous_terms)
    builder.add_node("timeout_handler", timeout_handler)
    builder.add_node("finalize", finalize)

    # --- entry ---
    builder.add_edge(START, "analyze_target")

    # --- analyze_target → {compute_counter_offer | evaluate_ambiguous_terms | finalize} ---
    builder.add_conditional_edges(
        "analyze_target",
        _route_from_analyze_target,
        {
            "compute_counter_offer": "compute_counter_offer",
            "evaluate_ambiguous_terms": "evaluate_ambiguous_terms",
            "finalize": "finalize",
        },
    )

    # --- compute_counter_offer → policy_guardrail_check (unconditional) ---
    builder.add_edge("compute_counter_offer", "policy_guardrail_check")

    # --- policy_guardrail_check → {wait_for_async_callback | human_escalation} ---
    builder.add_conditional_edges(
        "policy_guardrail_check",
        _route_from_policy_guardrail_check,
        {
            "wait_for_async_callback": "wait_for_async_callback",
            "human_escalation": "human_escalation",
        },
    )

    # --- wait_for_async_callback → {evaluate_response | timeout_handler} ---
    builder.add_conditional_edges(
        "wait_for_async_callback",
        _route_from_wait_for_async_callback,
        {
            "evaluate_response": "evaluate_response",
            "timeout_handler": "timeout_handler",
        },
    )

    # --- evaluate_response → {finalize | analyze_target | human_escalation} ---
    builder.add_conditional_edges(
        "evaluate_response",
        _route_from_evaluate_response,
        {
            "finalize": "finalize",
            "analyze_target": "analyze_target",
            "human_escalation": "human_escalation",
        },
    )

    # --- human_escalation → {wait_for_async_callback | finalize} ---
    builder.add_conditional_edges(
        "human_escalation",
        _route_from_human_escalation,
        {
            "wait_for_async_callback": "wait_for_async_callback",
            "finalize": "finalize",
        },
    )

    # --- evaluate_ambiguous_terms → finalize (unconditional; advisory never transacts) ---
    builder.add_edge("evaluate_ambiguous_terms", "finalize")

    # --- timeout_handler → finalize (unconditional) ---
    builder.add_edge("timeout_handler", "finalize")

    # --- finalize → END ---
    builder.add_edge("finalize", END)

    return builder.compile(checkpointer=checkpointer)


# ─────────────────────────────────────────────────────────────────────────
# Durable-checkpointer factory
# ─────────────────────────────────────────────────────────────────────────


@asynccontextmanager
async def build_graph_async(
    *,
    prefer_postgres: bool = True,
) -> AsyncIterator[Any]:
    """Async context manager that yields a graph with a durable checkpointer.

    Selects between three saver backends in this preference order:

    1. :class:`AsyncPostgresSaver` from ``langgraph-checkpoint-postgres``
       — production choice when ``NEGOTIATION_POSTGRES_DSN`` is set
       (architecture ``01_langgraph_state_machine`` §memory-and-checkpointing).
    2. :class:`MemorySaver` — falls open when Postgres is unavailable,
       the package isn't installed, or ``prefer_postgres=False``.

    The saver's lifecycle (connection pool open / close) is bound to the
    context manager — callers should ``async with`` this for the
    duration of their listener loop.

    Usage::

        async with build_graph_async() as graph:
            await graph.ainvoke(state, config=...)
    """
    saver_cm: Any = None

    if prefer_postgres and CONFIG.postgres_dsn:
        try:
            # Imported lazily so missing ``langgraph-checkpoint-postgres``
            # doesn't break the sync ``build_graph`` path used by tests.
            from langgraph.checkpoint.postgres.aio import (  # pragma: no cover
                AsyncPostgresSaver,
            )

            saver_cm = AsyncPostgresSaver.from_conn_string(CONFIG.postgres_dsn)
            saver = await saver_cm.__aenter__()
            # ``setup()`` is idempotent — provisions the checkpoint tables
            # (architecture mentions migration ``19_langgraph_checkpoints.sql``).
            await saver.setup()
            logger.info("Negotiation graph using AsyncPostgresSaver")
        except ImportError:
            logger.warning(
                "langgraph-checkpoint-postgres not installed — falling back "
                "to MemorySaver (state will not survive process restart)"
            )
            saver_cm = None
            saver = MemorySaver()
        except Exception as exc:  # pragma: no cover - Postgres unavailable
            logger.warning(
                "AsyncPostgresSaver setup failed (%s) — falling back to MemorySaver",
                exc,
            )
            saver_cm = None
            saver = MemorySaver()
    else:
        saver = MemorySaver()
        logger.info(
            "Negotiation graph using MemorySaver (no NEGOTIATION_POSTGRES_DSN configured)"
        )

    try:
        yield build_graph(checkpointer=saver)
    finally:
        if saver_cm is not None:
            try:
                await saver_cm.__aexit__(None, None, None)
            except Exception:  # pragma: no cover - cleanup is best-effort
                logger.exception("Error closing AsyncPostgresSaver")


__all__ = ["build_graph", "build_graph_async"]
