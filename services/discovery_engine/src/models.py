"""Shared Pydantic v2 data contracts for the Discovery Engine.

Centralising every cross-module type here keeps the coordinator,
resilience, and aggregator modules tightly typed and decouples them
from each other's internal structure. Every field uses strict
type hints (Python 3.11+ union syntax).
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field


# ─────────────────────────────────────────────────────────────────────────
# Network status taxonomy
# ─────────────────────────────────────────────────────────────────────────


class NetworkStatus(str, Enum):
    """The closed set of outcomes for a single per-network call."""

    OK = "ok"
    TIMEOUT = "timeout"
    UPSTREAM_5XX = "upstream_5xx"
    UPSTREAM_4XX = "upstream_4xx"
    CONNECTION_REFUSED = "connection_refused"
    CIRCUIT_OPEN = "circuit_open"
    INVALID_RESPONSE = "invalid_response"
    UNKNOWN_ERROR = "unknown_error"


# ─────────────────────────────────────────────────────────────────────────
# Gateway configuration
# ─────────────────────────────────────────────────────────────────────────


class NetworkGateway(BaseModel):
    """A configured Beckn-network endpoint the engine can fan out to."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(..., min_length=1, description="Stable network identifier.")
    base_url: str = Field(
        ..., min_length=1, description="Gateway origin (e.g. https://network-a.example.com)."
    )
    timeout_s: float = Field(
        default=8.0,
        gt=0.0,
        le=60.0,
        description=(
            "Per-network wall-clock timeout for a single /search round-trip. "
            "Enforced via asyncio.wait_for inside the resilience layer."
        ),
    )
    headers: dict[str, str] = Field(
        default_factory=dict,
        description="Static request headers (e.g. Authorization, X-Network-Token).",
    )


# ─────────────────────────────────────────────────────────────────────────
# Intent payload (mirrors shared.models.BecknIntent — kept local for
# service independence; can be replaced with the shared import later).
# ─────────────────────────────────────────────────────────────────────────


class IntentPayload(BaseModel):
    """Minimal local mirror of ``shared.models.BecknIntent``."""

    model_config = ConfigDict(extra="allow")

    item_name: str = Field(..., min_length=1)
    quantity: Optional[int] = Field(default=None, ge=1)
    location_coordinates: Optional[str] = Field(
        default=None,
        description='"lat,lon" decimal string per the anti-corruption-layer convention.',
    )
    delivery_timeline: Optional[int] = Field(
        default=None,
        ge=0,
        description="Hours until required delivery (int hours, not ISO 8601).",
    )
    budget_constraints: Optional[dict[str, float]] = Field(
        default=None,
        description='Typed {"min": ..., "max": ...} not raw strings.',
    )


# ─────────────────────────────────────────────────────────────────────────
# Catalog items — what each network returns + what the aggregator emits
# ─────────────────────────────────────────────────────────────────────────


class CatalogItem(BaseModel):
    """A single item returned by one network's ``/search``."""

    model_config = ConfigDict(extra="allow")

    provider_id: str = Field(..., min_length=1)
    item_id: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1)
    price: float = Field(..., ge=0)
    currency: str = Field(default="INR", min_length=3, max_length=3)
    delivery_hours: Optional[int] = Field(default=None, ge=0)
    quantity_available: Optional[int] = Field(default=None, ge=0)
    tax_id: Optional[str] = Field(
        default=None,
        description="Supplier tax registration (GST/PAN/EIN) — primary dedup signal.",
    )
    location_coordinates: Optional[str] = Field(
        default=None, description='"lat,lon" — secondary geographic dedup signal.'
    )
    raw_payload: dict[str, Any] = Field(
        default_factory=dict,
        description="Original Beckn item dict for downstream replay / audit.",
    )


class AggregatedItem(BaseModel):
    """A deduplicated item with provenance from one or more networks."""

    model_config = ConfigDict(extra="allow")

    provider_id: str
    item_id: str
    name: str
    price: float
    currency: str = "INR"
    delivery_hours: Optional[int] = None
    quantity_available: Optional[int] = None
    tax_id: Optional[str] = None
    location_coordinates: Optional[str] = None
    sources: list[str] = Field(
        default_factory=list,
        description="Names of the networks this item was seen on.",
    )
    duplicate_keys: list[str] = Field(
        default_factory=list,
        description=(
            'Stable "{provider_id}:{item_id}" keys for every input item '
            "that merged into this aggregate. Empty when no merge occurred."
        ),
    )


# ─────────────────────────────────────────────────────────────────────────
# Per-network and final results
# ─────────────────────────────────────────────────────────────────────────


class NetworkResult(BaseModel):
    """Per-network call outcome — structured success or structured failure.

    The :class:`~resilience.ResilienceManager` guarantees that *every*
    network call produces one of these — exceptions never escape the
    resilience layer, so the coordinator can rely on receiving a
    homogeneous list of ``NetworkResult`` objects from ``asyncio.gather``.
    """

    model_config = ConfigDict(extra="forbid")

    network: str
    status: NetworkStatus
    items: list[CatalogItem] = Field(default_factory=list)
    latency_ms: float = Field(default=0.0, ge=0.0)
    error: Optional[str] = None

    @property
    def is_success(self) -> bool:
        """Whether this network responded with usable catalog data."""
        return self.status == NetworkStatus.OK


class NetworkFailure(BaseModel):
    """Compact failure record surfaced in the final ``MultiSearchResult``."""

    model_config = ConfigDict(extra="forbid")

    network: str
    status: NetworkStatus
    error: Optional[str] = None
    latency_ms: float = 0.0


class MultiSearchResult(BaseModel):
    """Final fan-in response returned to the API caller.

    Always returned with HTTP 200, even when *every* network failed — the
    ``degraded`` flag + ``failed_networks`` list expose the operational
    state in a structured way that callers can branch on without trying
    to parse error responses.
    """

    model_config = ConfigDict(extra="forbid")

    query_id: str
    requested_networks: list[str]
    responded_networks: list[str]
    failed_networks: list[NetworkFailure]
    items: list[AggregatedItem]
    degraded: bool = Field(
        ...,
        description="True if at least one configured network failed (timeout, 5xx, refused).",
    )
    total_latency_ms: float = Field(default=0.0, ge=0.0)
    per_network_latency_ms: dict[str, float] = Field(default_factory=dict)


__all__ = [
    "AggregatedItem",
    "CatalogItem",
    "IntentPayload",
    "MultiSearchResult",
    "NetworkFailure",
    "NetworkGateway",
    "NetworkResult",
    "NetworkStatus",
]
