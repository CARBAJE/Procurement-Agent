"""Data contracts for the Negotiation Engine.

Two layers live here:

1. **Pydantic v2 models** — externally-facing structured payloads
   (``CounterOffer``, ``SupplierOffer``, ``HitlDecision``). These are the
   *first* layer of the guardrail stack (L1) per
   ``03_hard_guardrails_policy.md``: ``CounterOffer.discount_pct`` is
   structurally bounded to ``[0.0, 0.20]`` so an LLM cannot construct an
   instance that violates G1.

2. **LangGraph TypedDict state** — ``NegotiationState``. Every field
   declares an explicit reducer via ``Annotated[..., reducer]`` so merge
   semantics are self-documenting. ``operator.add`` is used on
   accumulating lists; a local ``last_value`` reducer is used on scalar
   pointer fields to make overwrite explicit (the LangGraph default is
   silent last-write-wins).

References:
- ``KnowledgeBase/project_scaffold/architecture/negotiation_engine/01_langgraph_state_machine.md`` §state-schema
- ``KnowledgeBase/project_scaffold/architecture/negotiation_engine/03_hard_guardrails_policy.md`` §G1 / §G11
"""
from __future__ import annotations

from operator import add
from typing import Annotated, Any, Literal, Optional, TypedDict

from langgraph.graph.message import add_messages
from pydantic import BaseModel, ConfigDict, Field, field_validator

# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

#: Absolute hard cap on requested discount, per guardrail G1.
#: Mirrored at the database layer by ``CHECK (max_discount_pct <= 0.20)``.
ABSOLUTE_MAX_DISCOUNT_PCT: float = 0.20

#: Allowed terminal outcomes — used as the ``final_outcome`` literal.
FinalOutcome = Literal[
    "accepted",
    "rejected",
    "escalated",
    "timed_out",
    "abandoned",
    "human_override",
]

#: Allowed strategy archetypes the planner can choose.
StrategyName = Literal[
    "counter_offer",
    "accept_within_margin",
    "escalate_to_human",
    "advisory_only",
]


# ---------------------------------------------------------------------------
# LangGraph reducer — explicit last-write-wins for scalar pointer fields.
# ---------------------------------------------------------------------------


def last_value(_old: Any, new: Any) -> Any:
    """Scalar reducer: overwrite the previous value with the new one.

    LangGraph's default channel semantics are last-write-wins, but they are
    silent — a partial-dict return from a node implicitly overwrites without
    declaring intent. Attaching this reducer via ``Annotated[T, last_value]``
    makes the contract explicit in the schema and visible in checkpoint
    diffs.
    """
    return new


# ---------------------------------------------------------------------------
# Pydantic models — externally-facing structured payloads.
# ---------------------------------------------------------------------------


class SupplierOffer(BaseModel):
    """Snapshot of a ranked candidate offer from the comparison_scoring_engine.

    The Negotiation Engine receives a frozen list of these inside the
    trigger payload (``negotiation:requested`` Pub/Sub channel). The engine
    never reads ``comparative_scoring.*`` tables directly — the snapshot is
    the canonical source of truth for the negotiation's duration.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    provider_id: str = Field(..., min_length=1, description="BPP identifier.")
    item_id: str = Field(..., min_length=1)
    price: float = Field(..., gt=0, description="Listed unit price.")
    currency: str = Field(default="INR", min_length=3, max_length=3)
    delivery_hours: int = Field(..., ge=0, description="Quoted lead time in hours.")
    quantity: int = Field(..., gt=0, description="Available quantity at this price.")
    score: float = Field(..., description="Ranking score from comparative engine.")
    round_received: int = Field(default=0, ge=0)


class CounterOffer(BaseModel):
    """A counter-offer drafted by the strategy module.

    L1 of the guardrail stack: ``discount_pct`` is structurally bounded to
    ``[0.0, 0.20]`` via Pydantic field constraints AND a redundant
    ``field_validator`` (belt-and-braces, intentional — see G1 in
    ``03_hard_guardrails_policy.md``). An LLM going through ``Instructor``
    is structurally unable to materialise a ``CounterOffer`` outside this
    range; the L2 ``policy_guardrail_check`` node re-enforces the same
    invariant for defence-in-depth.
    """

    model_config = ConfigDict(extra="forbid")

    target_price: float = Field(..., gt=0, description="Counter-offered unit price.")
    target_delivery_hours: int = Field(..., ge=0)
    target_quantity: int = Field(..., gt=0)
    discount_pct: float = Field(
        ...,
        ge=0.0,
        le=ABSOLUTE_MAX_DISCOUNT_PCT,
        description=(
            "Requested discount as a fraction of list price. "
            f"HARD-bounded to [0.0, {ABSOLUTE_MAX_DISCOUNT_PCT}] by guardrail G1."
        ),
    )
    rationale: str = Field(
        ...,
        min_length=1,
        max_length=2000,
        description="Audit-only LLM/rule explanation for the chosen terms.",
    )

    @field_validator("discount_pct")
    @classmethod
    def _enforce_hard_cap(cls, value: float) -> float:
        """Re-assert G1 inside the validator (redundant with ``le=`` for clarity).

        Pydantic's ``le=`` already rejects values above the cap with a
        ``ValidationError``. This explicit validator exists so a code
        reader sees the guardrail rule by name in the model, not buried in
        Field constraint kwargs.
        """
        if value < 0.0:
            raise ValueError("discount_pct must be non-negative")
        if value > ABSOLUTE_MAX_DISCOUNT_PCT:
            raise ValueError(
                f"discount_pct={value!r} exceeds G1 hard cap of {ABSOLUTE_MAX_DISCOUNT_PCT}"
            )
        return value


class HitlDecision(BaseModel):
    """Structured human-in-the-loop response delivered through approval_workflow.

    Resumes the ``human_escalation`` LangGraph interrupt via
    ``Command(resume=hitl_decision)``.
    """

    model_config = ConfigDict(extra="forbid")

    action: Literal["accept", "reject", "override"]
    reasoning: str = Field(default="", max_length=2000)
    override_offer: Optional[CounterOffer] = Field(
        default=None,
        description="If action == 'override', the human-edited counter-offer.",
    )
    reviewer: str = Field(default="", description="Approver identifier.")


# ---------------------------------------------------------------------------
# LangGraph state — TypedDict with explicit reducers.
# ---------------------------------------------------------------------------


class RoundRecord(TypedDict, total=False):
    """One entry in the ``round_history`` accumulator."""

    round_no: int
    provider_id: str
    sent: dict
    received: Optional[dict]
    decision: Literal["counter", "accept", "reject", "escalate", "timeout"]
    elapsed_ms: int


class AuditEvent(TypedDict, total=False):
    """One entry in the ``audit_events`` accumulator.

    Mirrors what gets emitted to the Kafka audit topic ``procurement.negotiation.v1``.
    """

    ts: str
    node: str
    kind: str
    detail: dict


class NegotiationState(TypedDict, total=False):
    """Full LangGraph state for a single negotiation session.

    The ``transaction_id`` doubles as the LangGraph ``thread_id`` (binding
    the Beckn correlation id to the checkpoint partition key — see
    ``01_langgraph_state_machine.md`` §memory-and-checkpointing).
    """

    # --- identity (immutable per session) -----------------------------------
    transaction_id: Annotated[str, last_value]
    category: Annotated[str, last_value]
    policy: Annotated[dict, last_value]

    # --- round control ------------------------------------------------------
    negotiation_round: Annotated[int, last_value]
    max_rounds: Annotated[int, last_value]

    # --- candidate ranking & active pointers --------------------------------
    ranked_candidates: Annotated[list[dict], last_value]
    current_target: Annotated[Optional[dict], last_value]
    current_strategy: Annotated[Optional[dict], last_value]
    current_counter_offer: Annotated[Optional[dict], last_value]

    # --- async machine-interrupt bookkeeping --------------------------------
    awaiting_on_select: Annotated[bool, last_value]
    on_select_correlation_id: Annotated[Optional[str], last_value]
    redis_channel: Annotated[Optional[str], last_value]
    last_on_select_payload: Annotated[Optional[dict], last_value]

    # --- HITL ---------------------------------------------------------------
    escalation_reason: Annotated[Optional[str], last_value]
    hitl_decision: Annotated[Optional[dict], last_value]

    # --- accumulators (operator.add) ----------------------------------------
    round_history: Annotated[list[RoundRecord], add]
    audit_events: Annotated[list[AuditEvent], add]
    messages: Annotated[list, add_messages]

    # --- terminal -----------------------------------------------------------
    final_outcome: Annotated[Optional[FinalOutcome], last_value]
    final_contract_draft: Annotated[Optional[dict], last_value]


__all__ = [
    "ABSOLUTE_MAX_DISCOUNT_PCT",
    "AuditEvent",
    "CounterOffer",
    "FinalOutcome",
    "HitlDecision",
    "NegotiationState",
    "RoundRecord",
    "StrategyName",
    "SupplierOffer",
    "last_value",
]
