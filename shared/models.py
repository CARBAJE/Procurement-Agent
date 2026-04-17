"""Shared Pydantic models used by both IntentParser and Bap-1.

Single source of truth for BudgetConstraints and BecknIntent —
the Anti-Corruption Layer between natural language and the Beckn Protocol.

All fields are canonical machine-processable form:
  - location_coordinates: "lat,lon" decimal string (not city names)
  - delivery_timeline:    positive integer in HOURS (not ISO 8601 "P3D")
  - budget_constraints:   typed range {max, min} (not a raw string)
  - descriptions:         list of atomic technical attributes
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field, field_validator


class BudgetConstraints(BaseModel):
    """Budget as a numeric range.

    min defaults to 0.0 (open lower bound): a buyer who says "under Rs 2/sheet"
    welcomes any price below max, including very low prices.
    """

    max: float
    min: float = 0.0


class BecknIntent(BaseModel):
    """Canonical procurement intent shared across all modules.

    - location_coordinates: "lat,lon" decimal string
    - delivery_timeline:    positive int in HOURS (1 day=24, 1 week=168)
    - descriptions:         atomic technical specs, e.g. ["80gsm", "A4", "Cat6"]
    - budget_constraints:   typed range, not a raw string amount
    """

    item: str
    descriptions: list[str] = Field(
        default_factory=list,
        description="Tech specs, e.g. ['80gsm', 'A4', 'Cat6']",
    )
    quantity: int
    location_coordinates: Optional[str] = Field(
        default=None,
        description="'lat,lon' decimal string",
    )
    delivery_timeline: Optional[int] = Field(
        default=None,
        description="In hours: 1 day=24h, 1 week=168h",
    )
    budget_constraints: Optional[BudgetConstraints] = None

    @field_validator("quantity")
    @classmethod
    def quantity_positive(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("quantity must be a positive integer")
        return v

    @field_validator("delivery_timeline")
    @classmethod
    def timeline_positive(cls, v: Optional[int]) -> Optional[int]:
        if v is not None and v <= 0:
            raise ValueError("delivery_timeline must be positive (hours)")
        return v
