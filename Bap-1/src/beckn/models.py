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
from typing import Optional
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
