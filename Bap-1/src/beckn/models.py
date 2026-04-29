"""Pydantic v2 models for the Beckn Protocol v2.

Key change from v1: Discovery is now SYNCHRONOUS.
  - v1: POST /search → async /on_search callbacks
  - v2: GET /discover → synchronous DiscoverResponse

The BecknIntent is the Anti-Corruption Layer (ACL) between natural language
and the Beckn Protocol. All fields are canonical machine-processable form:
  - location_coordinates: "lat,lon"  (not city names)
  - delivery_timeline:    hours int   (not ISO 8601 "P3D")
  - budget_constraints:   {max, min}  (not a string amount)
  - descriptions:         list[str]   (atomic specs, not concatenated)
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Literal, Optional
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


# ── Context ───────────────────────────────────────────────────────────────────


class BecknContext(BaseModel):
    """Beckn v2 context.

    Accepts both snake_case (internal/tests) and camelCase (real network)
    thanks to alias_generator + populate_by_name.

    Wire serialization (model_dump(by_alias=True)) produces camelCase
    as required by the real Beckn v2 spec.
    """

    model_config = ConfigDict(
        populate_by_name=True,
        alias_generator=to_camel,  # bap_id→bapId, transaction_id→transactionId, etc.
    )

    # Explicit aliases where field name differs from wire name
    domain: str = Field(default="beckn.one/testnet", alias="networkId")
    core_version: str = Field(default="2.0.0", alias="version")

    action: str
    country: str = "IND"
    city: str = "std:080"
    bap_id: str
    bap_uri: str
    transaction_id: str = Field(default_factory=lambda: str(uuid4()))
    message_id: str = Field(default_factory=lambda: str(uuid4()))
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )
    ttl: str = "PT30S"
    bpp_id: Optional[str] = None
    bpp_uri: Optional[str] = None


# ── Beckn v2 Intent (Anti-Corruption Layer) ───────────────────────────────────
# Imported from shared — single source of truth across all modules.

from shared.models import BecknIntent, BudgetConstraints  # noqa: F401, E402


# ── Discover request/response (v2 synchronous discovery) ─────────────────────


class DiscoverRequest(BaseModel):
    """Sent to the beckn-onix adapter's GET /discover endpoint."""

    context: BecknContext
    message: BecknIntent


class DiscoverOffering(BaseModel):
    """A single offering returned synchronously by the Discovery Service.

    The ONIX adapter collects catalog registrations from BPPs (via /publish)
    and returns matching offerings directly — no async callbacks needed.
    """

    bpp_id: str
    bpp_uri: str
    provider_id: str
    provider_name: str
    item_id: str
    item_name: str
    price_value: str
    price_currency: str = "INR"
    available_quantity: Optional[int] = None
    rating: Optional[str] = None
    specifications: list[str] = Field(default_factory=list)
    fulfillment_hours: Optional[int] = None      # delivery lead time in hours


class DiscoverResponse(BaseModel):
    """Response built from on_discover callback (real network) or direct response (mock)."""

    context: Optional[BecknContext] = None
    transaction_id: str
    offerings: list[DiscoverOffering] = Field(default_factory=list)


# ── /select ───────────────────────────────────────────────────────────────────


class SelectProvider(BaseModel):
    id: str


class SelectedItem(BaseModel):
    id: str
    quantity: int
    name: Optional[str] = None          # item descriptor name (for contract resources)
    price_value: Optional[str] = None   # unit price value (for contract consideration)
    price_currency: str = "INR"


class SelectOrder(BaseModel):
    provider: SelectProvider
    items: list[SelectedItem]
    fulfillment_hours: Optional[int] = None


class SelectMessage(BaseModel):
    order: SelectOrder


class SelectRequest(BaseModel):
    """Sent to ONIX adapter at POST /bap/caller/select.
    ONIX routes to POST /bpp/receiver/select on the chosen BPP.
    """

    context: BecknContext
    message: SelectMessage


# ── Async callbacks (on_select, on_init, on_confirm, on_status) ───────────────
# These arrive at /bap/receiver/{action} from the ONIX adapter after
# the BPP processes select/init/confirm/status requests.


class CallbackPayload(BaseModel):
    """Generic async callback from ONIX adapter."""

    model_config = ConfigDict(extra="allow")

    context: BecknContext
    message: dict = Field(default_factory=dict)
    error: Optional[dict] = None


# ── ACK ───────────────────────────────────────────────────────────────────────


class AckStatus(BaseModel):
    status: str  # "ACK" or "NACK"


class AckMessage(BaseModel):
    ack: AckStatus


class AckResponse(BaseModel):
    message: AckMessage
    error: Optional[dict] = None


# ── /init, /confirm, /status (Phase 2 — order lifecycle) ─────────────────────
# Reference: KnowledgeBase/project_scaffold/components/beckn_bap_client.md
#   init    — initialize the order (buyer sends billing + fulfillment)
#   confirm — commit the order with agreed payment terms
#   status  — poll for current fulfillment state


class Address(BaseModel):
    """Postal address — used by BillingInfo and FulfillmentInfo."""

    door: Optional[str] = None
    building: Optional[str] = None
    street: Optional[str] = None
    city: str
    state: Optional[str] = None
    country: str = "IND"
    area_code: str


class BillingInfo(BaseModel):
    """Buyer billing details sent in /init.

    Produced by a BillingProvider — never built inline by adapter/nodes so
    the source (config/session/DB) can be swapped without touching wire code.
    """

    name: str
    email: str
    phone: str
    address: Address
    tax_id: Optional[str] = None


class FulfillmentInfo(BaseModel):
    """Delivery details sent in /init.

    `end_location` is the drop-off point (GPS + address). `delivery_timeline`
    mirrors BecknIntent.delivery_timeline (hours) so the BPP can bind the SLA.
    """

    type: str = "Delivery"
    end_location: str  # "lat,lon" decimal string
    end_address: Address
    contact_name: str
    contact_phone: str
    delivery_timeline: Optional[int] = None  # hours, same semantics as BecknIntent


# Beckn v2 payment types (spec §Payment):
#   ON_ORDER        — pre-pay before fulfillment (UPI/card)
#   ON_FULFILLMENT  — COD, BPP collects at delivery
#   POST_FULFILLMENT — invoice / NET-30 / NET-60
PaymentType = Literal["ON_ORDER", "ON_FULFILLMENT", "POST_FULFILLMENT"]


class PaymentTerms(BaseModel):
    """Payment terms negotiated in /init and committed in /confirm.

    Produced by a PaymentProvider. Phase 2 stub uses COD (ON_FULFILLMENT).
    Real implementations will populate uri/transaction_id from a payment
    gateway (Razorpay, UPI, etc.).
    """

    type: PaymentType = "ON_FULFILLMENT"
    collected_by: str = "BPP"   # "BAP" for pre-pay, "BPP" for COD
    currency: str = "INR"
    uri: Optional[str] = None            # payment gateway URL (ON_ORDER)
    transaction_id: Optional[str] = None  # gateway reference (ON_ORDER / POST)
    status: str = "NOT-PAID"             # NOT-PAID | PAID


class OrderState(str, Enum):
    """Canonical order lifecycle states — aligned with Beckn v2 spec.

    Not every BPP emits every state. Missing transitions are fine: the UI
    and status node treat absent states as "no update".
    """

    CREATED = "CREATED"
    ACCEPTED = "ACCEPTED"
    PACKED = "PACKED"
    SHIPPED = "SHIPPED"
    OUT_FOR_DELIVERY = "OUT_FOR_DELIVERY"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


# ── /init ─────────────────────────────────────────────────────────────────────


class InitResponse(BaseModel):
    """Parsed on_init callback — payment terms drafted by the BPP.

    The BPP may adjust the payment terms we proposed (e.g., reject COD, offer
    only ON_ORDER). /confirm must use these final terms, not the originals.
    """

    context: Optional[BecknContext] = None
    transaction_id: str
    contract_id: str
    payment_terms: Optional[PaymentTerms] = None
    quote_total: Optional[str] = None   # final price (currency-stringed)
    quote_currency: str = "INR"
    raw_message: dict = Field(default_factory=dict)  # full on_init payload


# ── /confirm ──────────────────────────────────────────────────────────────────


class ConfirmResponse(BaseModel):
    """Parsed on_confirm callback — order is now committed.

    `order_id` is the BPP-assigned identifier used for all subsequent /status
    queries. `state` will typically be CREATED or ACCEPTED at this point.
    """

    context: Optional[BecknContext] = None
    transaction_id: str
    order_id: str
    state: OrderState = OrderState.CREATED
    fulfillment_eta: Optional[str] = None   # RFC 3339 timestamp
    raw_message: dict = Field(default_factory=dict)


# ── /status ───────────────────────────────────────────────────────────────────


class StatusResponse(BaseModel):
    """Parsed on_status callback — current fulfillment state.

    Polled periodically from the UI (Phase 2 SLA: within 30s of any change).
    Only the state and optional ETA/tracking_url are surfaced; the raw message
    is kept for audit.
    """

    context: Optional[BecknContext] = None
    transaction_id: str
    order_id: str
    state: OrderState
    fulfillment_eta: Optional[str] = None
    tracking_url: Optional[str] = None
    raw_message: dict = Field(default_factory=dict)
