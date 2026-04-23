"""Async node functions for the Procurement ReAct graph.

All nodes are produced by the make_nodes() factory, which closes over
BecknClient, CallbackCollector, and a ProviderBundle. This keeps every node a
plain async callable — easy to test by passing mocks to make_nodes().

Main-graph node roles
---------------------
parse_intent     Reason  — NL text → BecknIntent via intent_parser_facade (Ollama)
discover         Act     — BecknIntent → DiscoverResponse via /bap/caller/discover
rank_and_select  Reason  — pick best offering (cheapest price, Phase 1)
send_select      Act     — POST /bap/caller/select via BecknClient
send_init        Act     — POST /bap/caller/init  + await on_init (Phase 2)
send_confirm     Act     — POST /bap/caller/confirm + await on_confirm (Phase 2)
present_results  Observe — format final summary; always executes

Standalone node (NOT in the main graph — invoked by ProcurementAgent.get_status)
-----------------------------------------------------------------------------
send_status      Act     — POST /bap/caller/status + await on_status

Each node returns a *partial* ProcurementState dict. Fields not returned
are left unchanged by LangGraph's merge step.
"""
from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import uuid4

from ..beckn.models import SelectOrder, SelectProvider, SelectedItem
from ..nlp.intent_parser_facade import parse_nl_to_intent
from .state import ProcurementState

if TYPE_CHECKING:
    from ..beckn.callbacks import CallbackCollector
    from ..beckn.client import BecknClient
    from ..beckn.providers import ProviderBundle


def make_nodes(
    client: "BecknClient",
    collector: "CallbackCollector",
    providers: "ProviderBundle",
    discover_timeout: float = 15.0,
    callback_timeout: float = 15.0,
) -> tuple:
    """Return the bound async node functions as a tuple.

    Parameters
    ----------
    client:           Open BecknClient (must be inside an async context manager).
    collector:        CallbackCollector shared with the aiohttp server.
    providers:        Swappable sources for billing / fulfillment / payment.
    discover_timeout: Seconds to wait for the on_discover callback.
    callback_timeout: Seconds to wait for on_init / on_confirm / on_status.

    Returns
    -------
    (parse_intent, discover, rank_and_select, send_select,
     send_init, send_confirm, send_status, present_results)
    """

    # ── Node 1: parse_intent ──────────────────────────────────────────────────

    async def parse_intent(state: ProcurementState) -> dict:
        """Reason — convert raw NL request into a BecknIntent."""
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
        """Reason — rank offerings and pick the best one (cheapest, Phase 1)."""
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
        """Act — POST /bap/caller/select for the chosen offering.

        Also generates a contract_id for /init and /confirm to share. The
        contract_id is NOT the order_id — that is assigned by the BPP in
        on_confirm.
        """
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
            contract_id = str(uuid4())
            return {
                "select_ack": ack,
                "contract_id": contract_id,
                "messages": [
                    f"[send_select] ACK={ack_status} "
                    f"bpp={selected.bpp_id} provider={selected.provider_name} "
                    f"contract={contract_id[:8]}…"
                ],
            }
        except Exception as exc:
            return {
                "error": f"/select failed: {exc}",
                "messages": [f"[send_select] ERROR: {exc}"],
            }

    # ── Node 5: send_init (Phase 2) ───────────────────────────────────────────

    async def send_init(state: ProcurementState) -> dict:
        """Act — POST /bap/caller/init and await on_init.

        Draws billing / fulfillment from the ProviderBundle so the source of
        this data is a one-line swap in providers/__init__.py.
        """
        if state.get("error"):
            return {"messages": ["[send_init] skipped — prior error"]}

        selected = state.get("selected")
        intent = state.get("intent")
        txn_id = state.get("transaction_id")
        contract_id = state.get("contract_id")

        if selected is None or txn_id is None or contract_id is None:
            return {
                "error": "Cannot send /init without a selected offering, transaction_id, and contract_id",
                "messages": ["[send_init] ERROR: missing prerequisites"],
            }

        try:
            billing = providers.billing.get_billing(user_id=state.get("user_id"))
            fulfillment = providers.fulfillment.get_fulfillment(
                intent=intent, user_id=state.get("user_id")
            ) if intent else None

            if fulfillment is None:
                return {
                    "error": "Cannot send /init without a fulfillment (intent missing)",
                    "messages": ["[send_init] ERROR: fulfillment unavailable"],
                }

            items = [
                SelectedItem(
                    id=selected.item_id,
                    quantity=intent.quantity if intent else 1,
                    name=selected.item_name,
                    price_value=selected.price_value,
                    price_currency=selected.price_currency,
                )
            ]

            init_resp = await client.init(
                contract_id=contract_id,
                items=items,
                billing=billing,
                fulfillment=fulfillment,
                transaction_id=txn_id,
                bpp_id=selected.bpp_id,
                bpp_uri=selected.bpp_uri,
                collector=collector,
                timeout=callback_timeout,
            )

            # Fall back to a provider-proposed term if the BPP didn't reply.
            payment_terms = init_resp.payment_terms or providers.payment.propose_terms(
                total_value=init_resp.quote_total,
                currency=init_resp.quote_currency,
                user_id=state.get("user_id"),
            )

            quote_note = (
                f" quote=₹{init_resp.quote_total}" if init_resp.quote_total else ""
            )

            return {
                "billing": billing,
                "fulfillment": fulfillment,
                "init_response": init_resp,
                "payment_terms": payment_terms,
                "messages": [
                    f"[send_init] on_init received "
                    f"contract={contract_id[:8]}… "
                    f"payment={payment_terms.type}/{payment_terms.collected_by}"
                    f"{quote_note}"
                ],
            }
        except Exception as exc:
            return {
                "error": f"/init failed: {exc}",
                "messages": [f"[send_init] ERROR: {exc}"],
            }

    # ── Node 6: send_confirm (Phase 2) ────────────────────────────────────────

    async def send_confirm(state: ProcurementState) -> dict:
        """Act — POST /bap/caller/confirm and await on_confirm.

        Uses the payment terms from on_init verbatim (BPP may have countered).
        The BPP responds with an order_id that drives all /status polling.
        """
        if state.get("error"):
            return {"messages": ["[send_confirm] skipped — prior error"]}

        selected = state.get("selected")
        txn_id = state.get("transaction_id")
        contract_id = state.get("contract_id")
        payment_terms = state.get("payment_terms")

        if selected is None or txn_id is None or contract_id is None:
            return {
                "error": "Cannot send /confirm without prior /select and /init",
                "messages": ["[send_confirm] ERROR: missing prerequisites"],
            }

        # Fallback if /init never populated terms (e.g., timeout) — propose COD.
        if payment_terms is None:
            payment_terms = providers.payment.propose_terms(
                user_id=state.get("user_id")
            )

        try:
            confirm_resp = await client.confirm(
                contract_id=contract_id,
                payment=payment_terms,
                transaction_id=txn_id,
                bpp_id=selected.bpp_id,
                bpp_uri=selected.bpp_uri,
                collector=collector,
                timeout=callback_timeout,
            )
            eta_note = (
                f" eta={confirm_resp.fulfillment_eta}"
                if confirm_resp.fulfillment_eta
                else ""
            )
            return {
                "confirm_response": confirm_resp,
                "order_id": confirm_resp.order_id,
                "order_state": confirm_resp.state,
                "messages": [
                    f"[send_confirm] on_confirm received "
                    f"order_id={confirm_resp.order_id} "
                    f"state={confirm_resp.state.value}"
                    f"{eta_note}"
                ],
            }
        except Exception as exc:
            return {
                "error": f"/confirm failed: {exc}",
                "messages": [f"[send_confirm] ERROR: {exc}"],
            }

    # ── Standalone: send_status (invoked via ProcurementAgent.get_status) ────

    async def send_status(state: ProcurementState) -> dict:
        """Act — POST /bap/caller/status and await on_status.

        Not part of the main graph. Callers invoke this after the order is
        confirmed (periodic polling). Requires order_id, transaction_id, and
        the selected offering to be present in state.
        """
        selected = state.get("selected")
        txn_id = state.get("transaction_id")
        order_id = state.get("order_id")

        if selected is None or txn_id is None or order_id is None:
            return {
                "error": "Cannot send /status without a confirmed order",
                "messages": ["[send_status] ERROR: missing order_id or context"],
            }

        try:
            status_resp = await client.status(
                order_id=order_id,
                transaction_id=txn_id,
                bpp_id=selected.bpp_id,
                bpp_uri=selected.bpp_uri,
                collector=collector,
                timeout=callback_timeout,
            )
            eta_note = (
                f" eta={status_resp.fulfillment_eta}"
                if status_resp.fulfillment_eta
                else ""
            )
            return {
                "status_response": status_resp,
                "order_state": status_resp.state,
                "messages": [
                    f"[send_status] state={status_resp.state.value} "
                    f"order_id={status_resp.order_id}{eta_note}"
                ],
            }
        except Exception as exc:
            return {
                "error": f"/status failed: {exc}",
                "messages": [f"[send_status] ERROR: {exc}"],
            }

    # ── Node 7: present_results ───────────────────────────────────────────────

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
            order_id = state.get("order_id")
            order_state = state.get("order_state")

            if order_id:
                state_txt = (
                    order_state.value if order_state is not None else "UNKNOWN"
                )
                summary = (
                    f"Order CONFIRMED — {s.provider_name} | "
                    f"{s.item_name} × {qty} | "
                    f"₹{s.price_value} {s.price_currency} | "
                    f"order={order_id} state={state_txt} | "
                    f"txn={state.get('transaction_id')}"
                )
            else:
                summary = (
                    f"Order initiated (pre-confirm) — {s.provider_name} | "
                    f"{s.item_name} × {qty} | "
                    f"₹{s.price_value} {s.price_currency} | "
                    f"txn={state.get('transaction_id')}"
                )
        return {"messages": [f"[present_results] {summary}"]}

    return (
        parse_intent,
        discover,
        rank_and_select,
        send_select,
        send_init,
        send_confirm,
        send_status,
        present_results,
    )
