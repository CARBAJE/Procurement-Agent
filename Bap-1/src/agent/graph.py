"""LangGraph StateGraph for the Procurement ReAct loop.

Graph topology (Phase 2 — full transaction lifecycle)
-----------------------------------------------------
    parse_intent → discover ──(offerings)──→ rank_and_select → send_select
                         └──(empty/error)─────────────────────────────────┐
                                                                          │
    send_select ──(ack ok)──→ send_init ──(ok)──→ send_confirm ──→ present_results
                                   └──(error)────┐            └──(error)──┘
                                                 └───────────────→ present_results

Two partial graphs are also exposed for the Comparison UI flow (Milestone 2):

    compare_graph: parse_intent → discover → rank_and_select → present_results
    commit_graph:  send_select → send_init → send_confirm → present_results

All three graphs reuse the same node functions via make_nodes().

/status is NOT part of any graph. It is invoked via
ProcurementAgent.get_status() after the order has been confirmed (periodic
polling from the UI at a 30-second SLA — see KnowledgeBase real_time_tracking).

Public API
----------
    build_graph(client, collector, providers, ...)         → full flow
    build_compare_graph(client, collector, providers, ...) → discover + rank
    build_commit_graph(client, collector, providers, ...)  → select + init + confirm
    ProcurementAgent                                        → high-level entry point
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from langgraph.graph import END, StateGraph

from shared.models import BecknIntent

from ..beckn.adapter import BecknProtocolAdapter
from ..beckn.callbacks import CallbackCollector
from ..beckn.client import BecknClient
from ..beckn.models import SelectedItem, StatusResponse
from ..beckn.providers import ProviderBundle
from .nodes import make_nodes
from .state import ProcurementState

if TYPE_CHECKING:
    pass


# ── Routing ───────────────────────────────────────────────────────────────────


def _route_after_discover(state: ProcurementState) -> str:
    """Skip ranking and everything downstream if discovery produced nothing."""
    if state.get("error") or not state.get("offerings"):
        return "present_results"
    return "rank_and_select"


def _route_after_select(state: ProcurementState) -> str:
    """Skip init/confirm on /select error; present whatever we have."""
    if state.get("error"):
        return "present_results"
    return "send_init"


def _route_after_init(state: ProcurementState) -> str:
    """Skip confirm on /init error; present whatever we have."""
    if state.get("error"):
        return "present_results"
    return "send_confirm"


# ── Graph factories ───────────────────────────────────────────────────────────


def build_graph(
    client: BecknClient,
    collector: CallbackCollector,
    providers: ProviderBundle,
    discover_timeout: float = 15.0,
    callback_timeout: float = 15.0,
):
    """Compile and return the full procurement StateGraph."""
    (
        parse_intent,
        discover,
        rank_and_select,
        send_select,
        send_init,
        send_confirm,
        _send_status,
        present_results,
    ) = make_nodes(
        client,
        collector,
        providers,
        discover_timeout=discover_timeout,
        callback_timeout=callback_timeout,
    )

    graph = StateGraph(ProcurementState)

    graph.add_node("parse_intent",    parse_intent)
    graph.add_node("discover",        discover)
    graph.add_node("rank_and_select", rank_and_select)
    graph.add_node("send_select",     send_select)
    graph.add_node("send_init",       send_init)
    graph.add_node("send_confirm",    send_confirm)
    graph.add_node("present_results", present_results)

    graph.set_entry_point("parse_intent")
    graph.add_edge("parse_intent", "discover")
    graph.add_conditional_edges(
        "discover",
        _route_after_discover,
        {
            "rank_and_select": "rank_and_select",
            "present_results": "present_results",
        },
    )
    graph.add_edge("rank_and_select", "send_select")
    graph.add_conditional_edges(
        "send_select",
        _route_after_select,
        {"send_init": "send_init", "present_results": "present_results"},
    )
    graph.add_conditional_edges(
        "send_init",
        _route_after_init,
        {"send_confirm": "send_confirm", "present_results": "present_results"},
    )
    graph.add_edge("send_confirm",    "present_results")
    graph.add_edge("present_results", END)

    return graph.compile()


def build_compare_graph(
    client: BecknClient,
    collector: CallbackCollector,
    providers: ProviderBundle,
    discover_timeout: float = 15.0,
    callback_timeout: float = 15.0,
):
    """Partial graph — stops after rank_and_select.

    Used by the Comparison UI: the user sees all offerings and the recommended
    pick, then calls /commit to run the rest (select + init + confirm).
    """
    (
        parse_intent,
        discover,
        rank_and_select,
        *_rest,
        present_results,
    ) = make_nodes(
        client,
        collector,
        providers,
        discover_timeout=discover_timeout,
        callback_timeout=callback_timeout,
    )

    graph = StateGraph(ProcurementState)
    graph.add_node("parse_intent",    parse_intent)
    graph.add_node("discover",        discover)
    graph.add_node("rank_and_select", rank_and_select)
    graph.add_node("present_results", present_results)

    graph.set_entry_point("parse_intent")
    graph.add_edge("parse_intent", "discover")
    graph.add_conditional_edges(
        "discover",
        _route_after_discover,
        {
            "rank_and_select": "rank_and_select",
            "present_results": "present_results",
        },
    )
    graph.add_edge("rank_and_select", "present_results")
    graph.add_edge("present_results", END)
    return graph.compile()


def build_commit_graph(
    client: BecknClient,
    collector: CallbackCollector,
    providers: ProviderBundle,
    discover_timeout: float = 15.0,
    callback_timeout: float = 15.0,
):
    """Partial graph — starts at send_select (assumes state.selected already set).

    Used by the Comparison UI's /commit endpoint after the user confirms an
    offering. The incoming state must already contain offerings + selected +
    transaction_id (populated by a prior compare call).
    """
    (
        _parse_intent,
        _discover,
        _rank_and_select,
        send_select,
        send_init,
        send_confirm,
        _send_status,
        present_results,
    ) = make_nodes(
        client,
        collector,
        providers,
        discover_timeout=discover_timeout,
        callback_timeout=callback_timeout,
    )

    graph = StateGraph(ProcurementState)
    graph.add_node("send_select",     send_select)
    graph.add_node("send_init",       send_init)
    graph.add_node("send_confirm",    send_confirm)
    graph.add_node("present_results", present_results)

    graph.set_entry_point("send_select")
    graph.add_conditional_edges(
        "send_select",
        _route_after_select,
        {"send_init": "send_init", "present_results": "present_results"},
    )
    graph.add_conditional_edges(
        "send_init",
        _route_after_init,
        {"send_confirm": "send_confirm", "present_results": "present_results"},
    )
    graph.add_edge("send_confirm",    "present_results")
    graph.add_edge("present_results", END)
    return graph.compile()


# ── High-level agent class ────────────────────────────────────────────────────


class ProcurementAgent:
    """Orchestrates the full procurement ReAct loop.

    Three entry points:
        arun(request)              — full flow from NL text (used by run.py)
        arun_with_intent(intent)   — full flow from a pre-parsed BecknIntent
        arun_compare(intent)       — discover + rank only (Comparison UI)
        arun_commit(state)         — select + init + confirm only (Comparison UI)
        get_status(...)            — single-shot /status polling

    The compare/commit split lets the UI show offerings to the user BEFORE
    committing the order, so a non-default pick is possible.
    """

    def __init__(
        self,
        adapter: BecknProtocolAdapter,
        collector: CallbackCollector,
        *,
        providers: ProviderBundle,
        discover_timeout: float = 15.0,
        callback_timeout: float = 15.0,
    ) -> None:
        self._adapter = adapter
        self._collector = collector
        self._providers = providers
        self._discover_timeout = discover_timeout
        self._callback_timeout = callback_timeout

    async def arun(
        self,
        request: str,
        *,
        user_id: Optional[str] = None,
    ) -> ProcurementState:
        """NL entry point — parse_intent calls Ollama via intent_parser_facade."""
        async with BecknClient(self._adapter) as client:
            graph = build_graph(
                client,
                self._collector,
                self._providers,
                discover_timeout=self._discover_timeout,
                callback_timeout=self._callback_timeout,
            )
            return await graph.ainvoke(
                {
                    "request": request,
                    "intent": None,
                    "user_id": user_id,
                    "offerings": [],
                    "messages": [],
                    "reasoning_steps": [],
                }
            )

    async def arun_with_intent(
        self,
        intent: BecknIntent,
        *,
        user_id: Optional[str] = None,
    ) -> ProcurementState:
        """Pre-built intent — parse_intent skips NLP entirely."""
        async with BecknClient(self._adapter) as client:
            graph = build_graph(
                client,
                self._collector,
                self._providers,
                discover_timeout=self._discover_timeout,
                callback_timeout=self._callback_timeout,
            )
            return await graph.ainvoke(
                {
                    "request": intent.item,
                    "intent": intent,
                    "user_id": user_id,
                    "offerings": [],
                    "messages": [],
                    "reasoning_steps": [],
                }
            )

    async def arun_compare(
        self,
        intent: BecknIntent,
        *,
        user_id: Optional[str] = None,
    ) -> ProcurementState:
        """Comparison UI entry — run discover + rank only, do NOT commit."""
        async with BecknClient(self._adapter) as client:
            graph = build_compare_graph(
                client,
                self._collector,
                self._providers,
                discover_timeout=self._discover_timeout,
                callback_timeout=self._callback_timeout,
            )
            return await graph.ainvoke(
                {
                    "request": intent.item,
                    "intent": intent,
                    "user_id": user_id,
                    "offerings": [],
                    "messages": [],
                    "reasoning_steps": [],
                }
            )

    async def arun_commit(
        self,
        state: ProcurementState,
    ) -> ProcurementState:
        """Comparison UI entry — run select + init + confirm from a pre-populated state.

        `state` must contain at least: transaction_id, selected, intent.
        (offerings is not required at this stage but usually present.)
        """
        async with BecknClient(self._adapter) as client:
            graph = build_commit_graph(
                client,
                self._collector,
                self._providers,
                discover_timeout=self._discover_timeout,
                callback_timeout=self._callback_timeout,
            )
            return await graph.ainvoke(state)

    async def get_status(
        self,
        *,
        transaction_id: str,
        order_id: str,
        bpp_id: str,
        bpp_uri: str,
        items: "list[SelectedItem] | None" = None,
    ) -> StatusResponse:
        """Standalone /status invocation — used for UI polling.

        Intentionally bypasses the main graph to keep the poll path cheap:
        a single HTTP round-trip + one callback, no NLP, no discovery,
        no state machine.

        `items` is required to pass Beckn v2.1 schema validation — the
        /status message inherits Contract's required `commitments`.
        """
        async with BecknClient(self._adapter) as client:
            return await client.status(
                order_id=order_id,
                items=items or [],
                transaction_id=transaction_id,
                bpp_id=bpp_id,
                bpp_uri=bpp_uri,
                collector=self._collector,
                timeout=self._callback_timeout,
            )
