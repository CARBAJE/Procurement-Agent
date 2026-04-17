"""ProcurementState — shared memory carried through the LangGraph ReAct loop.

Each node receives the full state and returns a partial dict with only the
fields it modifies. LangGraph merges the partials automatically.

The `messages` field uses an append-only reducer (operator.add) so every node
can return only its new log lines without reading the existing list.
"""
from __future__ import annotations

import operator
from typing import Annotated, Optional, TypedDict

from shared.models import BecknIntent

from ..beckn.models import DiscoverOffering


class ProcurementState(TypedDict):
    request:        str                              # raw NL query or intent.item
    intent:         Optional[BecknIntent]            # parsed or pre-loaded intent
    transaction_id: Optional[str]                    # Beckn txn ID from /discover
    offerings:      list[DiscoverOffering]           # all offerings returned
    selected:       Optional[DiscoverOffering]       # winning offering
    select_ack:     Optional[dict]                   # raw ONIX ACK from /select
    messages:       Annotated[list[str], operator.add]  # append-only reasoning trace
    error:          Optional[str]                    # first failure; subsequent nodes skip
