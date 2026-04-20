"""Async node functions for the Procurement ReAct graph.

All five nodes are produced by the make_nodes() factory, which closes over
BecknClient and CallbackCollector. This keeps every node a plain async
callable — easy to test by passing mock objects to make_nodes().

Node roles
----------
parse_intent     Reason  — NL text → BecknIntent via intent_parser_facade (Ollama)
discover         Act     — BecknIntent → DiscoverResponse via /bap/caller/discover
rank_and_select  Reason  — pick best offering (cheapest price, Phase 1)
send_select      Act     — POST /bap/caller/select via BecknClient
present_results  Observe — format final summary; always executes

Each node returns a *partial* ProcurementState dict. Fields not returned
are left unchanged by LangGraph's merge step.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from ..beckn.models import SelectOrder, SelectProvider, SelectedItem
from ..nlp.intent_parser_facade import parse_nl_to_intent
from .state import ProcurementState

if TYPE_CHECKING:
    from ..beckn.callbacks import CallbackCollector
    from ..beckn.client import BecknClient


def make_nodes(
    client: "BecknClient",
    collector: "CallbackCollector",
    discover_timeout: float = 15.0,
) -> tuple:
    """Return the five bound async node functions as a tuple.

    Parameters
    ----------
    client:           Open BecknClient (must be inside an async context manager).
    collector:        CallbackCollector shared with the aiohttp server.
    discover_timeout: Seconds to wait for the on_discover callback.
    """

    # ── Node 1: parse_intent ──────────────────────────────────────────────────

    async def parse_intent(state: ProcurementState) -> dict:
        """Reason — convert raw NL request into a BecknIntent.

        Delegates to intent_parser_facade → IntentParser (Ollama qwen3:1.7b).
        Skips the NLP call entirely if state["intent"] is already populated —
        this is the injection point for run.py, tests, and arun_with_intent().
        """
        if state.get("intent") is not None:
            return {"messages": ["[parse_intent] intent pre-loaded — skipping NLP"]}

        query = state["request"]
        try:
            intent = parse_nl_to_intent(query)
            if intent is None:
                return {
                    "error": f"Query not recognised as procurement: {query!r}",
                    "messages": ["[parse_intent] ERROR: non-procurement query"],
                }
            budget_max = (
                intent.budget_constraints.max if intent.budget_constraints else None
            )
            return {
                "intent": intent,
                "messages": [
                    f"[parse_intent] item={intent.item!r} qty={intent.quantity} "
                    f"loc={intent.location_coordinates} "
                    f"timeline={intent.delivery_timeline}h "
                    f"budget_max={budget_max}"
                ],
            }
        except Exception as exc:
            return {
                "error": f"Intent parsing failed: {exc}",
                "messages": [f"[parse_intent] ERROR: {exc}"],
            }

    # ── Node 2: discover ──────────────────────────────────────────────────────

    async def discover(state: ProcurementState) -> dict:
        """Act — POST /bap/caller/discover and collect the on_discover callback."""
        if state.get("error"):
            return {"messages": ["[discover] skipped — prior error"]}

        intent = state.get("intent")
        if intent is None:
            return {
                "error": "Cannot run /discover without a parsed intent",
                "messages": ["[discover] ERROR: intent is None"],
            }

        try:
            resp = await client.discover_async(
                intent, collector, timeout=discover_timeout
            )
            offer_summary = ", ".join(
                f"{o.provider_name}@₹{o.price_value}" for o in resp.offerings
            )
            return {
                "offerings": resp.offerings,
                "transaction_id": resp.transaction_id,
                "messages": [
                    f"[discover] txn={resp.transaction_id} "
                    f"found {len(resp.offerings)} offering(s)"
                    + (f": {offer_summary}" if offer_summary else "")
                ],
            }
        except Exception as exc:
            return {
                "error": f"Discovery failed: {exc}",
                "messages": [f"[discover] ERROR: {exc}"],
            }

    # ── Node 3: rank_and_select ───────────────────────────────────────────────

    async def rank_and_select(state: ProcurementState) -> dict:
        """Reason — rank offerings and pick the best one.

        Phase 1: cheapest price wins.
        Phase 2 extension point: replace this body with the Comparison &
        Scoring Engine. The node signature stays the same.
        """
        offerings = state.get("offerings") or []
        if not offerings:
            return {"messages": ["[rank_and_select] no offerings to rank"]}

        best = min(offerings, key=lambda o: float(o.price_value))
        return {
            "selected": best,
            "messages": [
                f"[rank_and_select] selected {best.provider_name!r} "
                f"₹{best.price_value} (cheapest of {len(offerings)})"
            ],
        }

    # ── Node 4: send_select ───────────────────────────────────────────────────

    async def send_select(state: ProcurementState) -> dict:
        """Act — POST /bap/caller/select for the chosen offering."""
        if state.get("error"):
            return {"messages": ["[send_select] skipped — prior error"]}

        selected = state.get("selected")
        txn_id = state.get("transaction_id")
        intent = state.get("intent")

        if selected is None or txn_id is None:
            return {
                "error": "Cannot send /select without a selected offering and transaction ID",
                "messages": ["[send_select] ERROR: missing selected or transaction_id"],
            }

        try:
            order = SelectOrder(
                provider=SelectProvider(id=selected.provider_id),
                items=[
                    SelectedItem(
                        id=selected.item_id,
                        quantity=intent.quantity if intent else 1,
                        name=selected.item_name,
                        price_value=selected.price_value,
                        price_currency=selected.price_currency,
                    )
                ],
            )
            ack = await client.select(
                order,
                transaction_id=txn_id,
                bpp_id=selected.bpp_id,
                bpp_uri=selected.bpp_uri,
            )
            ack_status = (
                ack.get("message", {}).get("ack", {}).get("status", "UNKNOWN")
            )
            return {
                "select_ack": ack,
                "messages": [
                    f"[send_select] ACK={ack_status} "
                    f"bpp={selected.bpp_id} provider={selected.provider_name}"
                ],
            }
        except Exception as exc:
            return {
                "error": f"/select failed: {exc}",
                "messages": [f"[send_select] ERROR: {exc}"],
            }

    # ── Node 5: present_results ───────────────────────────────────────────────

    async def present_results(state: ProcurementState) -> dict:
        """Observe — build the final summary. Always executes."""
        if state.get("error"):
            summary = f"Procurement flow ended with error: {state['error']}"
        elif not state.get("selected"):
            summary = "No offerings found for the requested item."
        else:
            s = state["selected"]
            intent = state.get("intent")
            qty = intent.quantity if intent else "?"
            summary = (
                f"Order initiated — {s.provider_name} | "
                f"{s.item_name} × {qty} | "
                f"₹{s.price_value} {s.price_currency} | "
                f"txn={state.get('transaction_id')}"
            )
        return {"messages": [f"[present_results] {summary}"]}

    return parse_intent, discover, rank_and_select, send_select, present_results
