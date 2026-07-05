"""Vendor-neutral Pydantic models exchanged on the adapter's HTTP surface.

These mirror what services/orchestrator/src/erp/models.py exposes — both ends
must validate compatibly. Keep field names stable; vendor mappers translate
to/from these in adapters/{sap,oracle,mock}.py.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class BudgetCheckRequest(BaseModel):
    """Synchronous budget gate input.

    Posted by the orchestrator on /commit before the Beckn select/init/confirm
    chain runs. Total budget on the wire ≤ 800ms.
    """
    cost_center: str = Field(..., description="ERP cost center / WBS / GL account key")
    requested_amount: Decimal = Field(..., gt=0)
    currency: str = Field(default="INR", min_length=3, max_length=3)
    category: str = Field(default="uncategorized")
    requester_id: str = Field(default="anonymous")
    transaction_id: str = Field(..., description="Beckn transaction_id — used for tracing and idempotency")


class BudgetCheckResult(BaseModel):
    """Synchronous budget gate output."""
    allowed: bool
    available_balance: Optional[Decimal] = None
    hold_id: Optional[str] = None
    expires_at: Optional[datetime] = None
    reasons: list[str] = Field(default_factory=list)
    vendor: Optional[str] = None
    fallback: bool = Field(
        default=False,
        description="True when the orchestrator marked this as fail-open; the orchestrator sets it client-side."
    )


class LineItem(BaseModel):
    item_id: str
    name: str
    quantity: int = Field(..., gt=0)
    unit: str = "each"
    unit_price: Decimal
    currency: str = "INR"
    category: Optional[str] = None


class Buyer(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: Optional[str] = None
    name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    tax_id: Optional[str] = None
    cost_center: Optional[str] = None
    address: Optional[dict[str, Any]] = None


class Supplier(BaseModel):
    bpp_id: str
    bpp_uri: Optional[str] = None
    name: Optional[str] = None


class PaymentTerms(BaseModel):
    model_config = ConfigDict(extra="ignore")
    type: Optional[str] = None
    collector: Optional[str] = None
    currency: Optional[str] = None
    net_days: Optional[int] = None


class Fulfillment(BaseModel):
    model_config = ConfigDict(extra="ignore")
    eta: Optional[str] = None
    delivery_address: Optional[dict[str, Any]] = None
    contact: Optional[dict[str, Any]] = None


class Totals(BaseModel):
    subtotal: Decimal
    currency: str = "INR"


class NormalizedPO(BaseModel):
    """Vendor-neutral PO payload sent on /api/v1/po/sync (M3.2)."""
    transaction_id: str
    order_id: str
    contract_id: Optional[str] = None
    buyer: Buyer
    supplier: Supplier
    line_items: list[LineItem]
    totals: Totals
    payment_terms: PaymentTerms = Field(default_factory=PaymentTerms)
    fulfillment: Fulfillment = Field(default_factory=Fulfillment)
    metadata: dict[str, Any] = Field(default_factory=dict)


class PushResult(BaseModel):
    """Result of a successful vendor PO push."""
    vendor: str
    erp_reference_id: str
    raw: dict[str, Any] = Field(default_factory=dict)


class InboundStatus(BaseModel):
    """Normalized inbound webhook payload (M3.3)."""
    vendor: str
    transaction_id: str
    erp_reference_id: Optional[str] = None
    state: str
    event_ts: datetime
    vendor_event_id: Optional[str] = None
    raw: dict[str, Any] = Field(default_factory=dict)


# ── Policy evaluation ─────────────────────────────────────────────────────────

class PolicyConstraintKind(str):
    """Stable string enum for constraint kinds (avoids an extra Enum import)."""
    REQUIRES_APPROVAL = "requires_approval"
    PREFERRED_SUPPLIER = "preferred_supplier"
    BLOCKED_SUPPLIER = "blocked_supplier"
    BLOCKED_CATEGORY = "blocked_category"
    BUDGET_EXCEEDED = "budget_exceeded"
    AUTO_COMMIT_BLOCKED = "auto_commit_blocked"


class PolicyConstraint(BaseModel):
    """One ERP-sourced procurement constraint, attached to a PolicyEnvelope for audit."""
    kind: str = Field(..., description="Stable kind key from PolicyConstraintKind")
    value: Optional[str] = None    # supplier_id, category, etc.
    source: str = "erp"            # "cost_center" | "po_policy" | "category_policy" | …
    note: Optional[str] = None


class PolicyEvaluateRequest(BaseModel):
    """Input sent to POST /api/v1/policy/evaluate.

    Mirrors services/orchestrator/src/erp/client.py::PolicyEvaluateRequest — keep
    field names identical on both sides.
    """
    transaction_id: str = Field(..., description="Beckn transaction_id — used for tracing")
    cost_center: str = Field(default="default")
    order_total: Decimal = Field(..., gt=0)
    currency: str = Field(default="INR", min_length=3, max_length=3)
    category: str = Field(default="uncategorized")
    requester_id: str = Field(default="anonymous")
    item_ids: list[str] = Field(default_factory=list)
    provider_ids: list[str] = Field(default_factory=list)


class PolicyEnvelope(BaseModel):
    """ERP policy evaluation result.

    The PolicyEngine reads preferred_supplier_ids, approval_required,
    auto_commit_allowed, and fallback. constraints is for the audit trail.
    """
    preferred_supplier_ids: list[str] = Field(default_factory=list)
    approval_required: bool = False
    auto_commit_allowed: bool = True
    fallback: bool = Field(
        default=False,
        description="True when the orchestrator used a fail-open result (ERP unavailable).",
    )
    constraints: list[PolicyConstraint] = Field(default_factory=list)
    vendor: Optional[str] = None


# ── Health/readiness response shapes (not strictly needed but documents intent)

class HealthResponse(BaseModel):
    status: Literal["ok"]


class ReadyResponse(BaseModel):
    ready: bool
    checks: dict[str, str]
