"""LangGraph StateGraph for the Procurement ReAct loop.

Graph topology
--------------
    parse_intent → discover ──(offerings)──→ rank_and_select → send_select → present_results
                           └──(empty/error)──────────────────────────────→ present_results

Public API
----------
    build_graph(client, collector, discover_timeout) → CompiledGraph
    ProcurementAgent                                  → high-level entry point
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from langgraph.graph import END, StateGraph

from shared.models import BecknIntent

from ..beckn.adapter import BecknProtocolAdapter
from ..beckn.callbacks import CallbackCollector
from ..beckn.client import BecknClient
from .nodes import make_nodes
from .state import ProcurementState

if TYPE_CHECKING:
    pass


# ── Routing ───────────────────────────────────────────────────────────────────


def _route_after_discover(state: ProcurementState) -> str:
    """Conditional edge after discover.

    Skip ranking and /select if there are no offerings or an error occurred.
    Always surface a result via present_results.
    """
    if state.get("error") or not state.get("offerings"):
        return "present_results"
    return "rank_and_select"


# ── Graph factory ─────────────────────────────────────────────────────────────


def build_graph(
    client: BecknClient,
    collector: CallbackCollector,
    discover_timeout: float = 15.0,
):
    """Compile and return the procurement StateGraph.

    Parameters
    ----------
    client:           Open BecknClient (already inside an async context manager).
    collector:        CallbackCollector shared with the aiohttp server.
    discover_timeout: Seconds to wait for the on_discover callback.
    """
    parse_intent, discover, rank_and_select, send_select, present_results = (
        make_nodes(client, collector, discover_timeout)
    )

    graph = StateGraph(ProcurementState)

    graph.add_node("parse_intent",    parse_intent)
    graph.add_node("discover",        discover)
    graph.add_node("rank_and_select", rank_and_select)
    graph.add_node("send_select",     send_select)
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
    graph.add_edge("send_select",     "present_results")
    graph.add_edge("present_results", END)

    return graph.compile()


# ── High-level agent class ────────────────────────────────────────────────────


class ProcurementAgent:
    """Orchestrates the full procurement ReAct loop.

    Usage (NL query):
        agent = ProcurementAgent(adapter, collector)
        result = await agent.arun("500 reams A4 paper 80gsm Bangalore max 200 INR")

    Usage (pre-built intent — skips NLP):
        result = await agent.arun_with_intent(intent)
    """

    def __init__(
        self,
        adapter: BecknProtocolAdapter,
        collector: CallbackCollector,
        discover_timeout: float = 15.0,
    ) -> None:
        self._adapter = adapter
        self._collector = collector
        self._timeout = discover_timeout

    async def arun(self, request: str) -> ProcurementState:
        """NL entry point — parse_intent calls Ollama via intent_parser_facade."""
        async with BecknClient(self._adapter) as client:
            graph = build_graph(client, self._collector, self._timeout)
            return await graph.ainvoke(
                {
                    "request": request,
                    "intent": None,
                    "offerings": [],
                    "messages": [],
                }
            )

    async def arun_with_intent(self, intent: BecknIntent) -> ProcurementState:
        """Pre-built intent — parse_intent skips NLP entirely."""
        async with BecknClient(self._adapter) as client:
            graph = build_graph(client, self._collector, self._timeout)
            return await graph.ainvoke(
                {
                    "request": intent.item,
                    "intent": intent,
                    "offerings": [],
                    "messages": [],
                }
            )
