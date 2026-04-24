"""ProcurementState — shared memory carried through the LangGraph ReAct loop.

Each node receives the full state and returns a partial dict with only the
fields it modifies. LangGraph merges the partials automatically.

The `messages` and `reasoning_steps` fields use an append-only reducer
(operator.add) so every node can return only its new entries without reading
the existing list.

`messages` is human-readable log lines (kept for back-compat with the current
frontend parsing).
`reasoning_steps` is the machine-readable parallel trace consumed by the new
Comparison UI: each step carries node name, ReAct role, summary, details dict
and timestamp.
"""
from __future__ import annotations

import operator
from typing import Annotated, Optional, TypedDict

from shared.models import BecknIntent

from ..beckn.models import (
    BillingInfo,
    ConfirmResponse,
    DiscoverOffering,
    FulfillmentInfo,
    InitResponse,
    OrderState,
    PaymentTerms,
    StatusResponse,
)


class ReasoningStep(TypedDict, total=False):
    """Structured trace entry emitted by each graph node.

    role is one of "reason" | "act" | "observe" (ReAct loop role).
    details is an optional free-form payload for UI rendering.
    """

    node: str
    role: str
    summary: str
    details: dict
    timestamp: str


class ProcurementState(TypedDict, total=False):
    # ── Request / intent (written by parse_intent) ────────────────────────────
    request:        str                              # raw NL query or intent.item
    intent:         Optional[BecknIntent]            # parsed or pre-loaded intent
    user_id:        Optional[str]                    # for future DB-backed providers

    # ── /discover (written by discover) ───────────────────────────────────────
    transaction_id: Optional[str]                    # Beckn txn ID shared by all actions
    offerings:      list[DiscoverOffering]           # all offerings returned
    selected:       Optional[DiscoverOffering]       # winning offering

    # ── /select (written by send_select) ──────────────────────────────────────
    select_ack:     Optional[dict]                   # raw ONIX ACK from /select
    contract_id:    Optional[str]                    # shared with /init and /confirm

    # ── /init (written by send_init) ──────────────────────────────────────────
    billing:        Optional[BillingInfo]            # from BillingProvider
    fulfillment:    Optional[FulfillmentInfo]        # from FulfillmentProvider
    init_response:  Optional[InitResponse]           # parsed on_init
    payment_terms:  Optional[PaymentTerms]           # final terms (BPP may counter)

    # ── /confirm (written by send_confirm) ────────────────────────────────────
    confirm_response: Optional[ConfirmResponse]      # parsed on_confirm
    order_id:       Optional[str]                    # BPP-assigned order ID

    # ── /status (written by send_status — standalone, not in main graph) ─────
    status_response: Optional[StatusResponse]        # parsed on_status
    order_state:    Optional[OrderState]             # last observed lifecycle state

    # ── Observability ─────────────────────────────────────────────────────────
    messages:        Annotated[list[str], operator.add]             # human-readable trace
    reasoning_steps: Annotated[list[ReasoningStep], operator.add]   # structured trace
    error:           Optional[str]                                  # first failure
