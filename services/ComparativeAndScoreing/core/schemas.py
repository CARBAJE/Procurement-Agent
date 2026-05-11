"""Pydantic v2 schemas for the Phase 2 ComparativeAndScoring service.

Defines the request/response shape of the scoring API and the
``CatalogItem`` adaptor that maps DiscoverOffering payloads from the
Beckn pipeline into the typed form consumed by ``Phase2Scorer``.
"""
from __future__ import annotations

import re
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

__all__ = [
    "CatalogItem",
    "ScoreRequest",
    "ScoredItem",
    "ScoreResponse",
]

_CURRENCY_RE = re.compile(r"[^0-9.\-eE]")


def _coerce_currency(value: Any) -> float:
    """Parse a price expressed as float/int/str (e.g. ``"₹ 1,200"``) into float.

    Raises ``ValueError`` if the cleaned text cannot be parsed.
    """
    if value is None:
        raise ValueError("price is required")
    if isinstance(value, bool):
        raise ValueError("price must be numeric, not bool")
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text:
        raise ValueError("price string is empty")
    cleaned = _CURRENCY_RE.sub("", text)
    if cleaned in ("", "-", ".", "-.", "e", "E"):
        raise ValueError(f"unparseable price value: {value!r}")
    return float(cleaned)


class CatalogItem(BaseModel):
    """A single candidate offering used as input to the scorer."""

    model_config = ConfigDict(extra="allow")

    id: str = Field(..., description="Stable item identifier (e.g. item_id from DiscoverOffering)")
    price: float
    delivery_time_hours: int
    risk_score: Optional[float] = None
    supplier_name: Optional[str] = None

    @field_validator("price", mode="before")
    @classmethod
    def _coerce_price(cls, v: Any) -> float:
        return _coerce_currency(v)

    @classmethod
    def from_discover_offering(cls, offering: dict) -> "CatalogItem":
        """Map a Beckn ``DiscoverOffering`` dict into a ``CatalogItem``.

        Field mapping:
          - ``id``                  <- ``item_id``
          - ``price``               <- ``price_value`` (str -> float)
          - ``delivery_time_hours`` <- ``fulfillment_hours``
          - ``supplier_name``       <- ``provider_name``
          - ``risk_score``          <- ``rating`` (parsed to float when present)
        """
        rating = offering.get("rating")
        risk_score: Optional[float] = None
        if rating is not None:
            try:
                risk_score = _coerce_currency(rating)
            except ValueError:
                risk_score = None

        fulfillment = offering.get("fulfillment_hours")
        delivery_hours = int(fulfillment) if fulfillment is not None else 0

        return cls(
            id=str(offering.get("item_id", "")),
            price=offering.get("price_value", 0.0),
            delivery_time_hours=delivery_hours,
            risk_score=risk_score,
            supplier_name=offering.get("provider_name"),
        )


class ScoreRequest(BaseModel):
    """Inbound batch of candidates to be scored together."""

    items: list[CatalogItem]
    transaction_id: Optional[str] = None


class ScoredItem(BaseModel):
    """One catalog item annotated with its model score and resulting rank."""

    item: CatalogItem
    score: float
    rank: int


class ScoreResponse(BaseModel):
    """Top recommendation plus the full ranked list returned to callers."""

    recommended: CatalogItem
    ranked_list: list[ScoredItem]
    model_version: str
    pipeline: str = "phase2_ranknet"
