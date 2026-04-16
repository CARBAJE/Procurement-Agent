from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field, field_validator

# ── Location lookup ───────────────────────────────────────────────────────────

_CITY_COORDS: dict[str, str] = {
    "bangalore": "12.9716,77.5946", "bengaluru": "12.9716,77.5946",
    "mumbai":    "19.0760,72.8777", "delhi":     "28.7041,77.1025",
    "new delhi": "28.6139,77.2090", "chennai":   "13.0827,80.2707",
    "hyderabad": "17.3850,78.4867", "pune":      "18.5204,73.8567",
    "kolkata":   "22.5726,88.3639",
}


def resolve_location(text: str) -> str:
    lower = text.strip().lower()
    return next((v for k, v in _CITY_COORDS.items() if k in lower), text)


# ── Models ────────────────────────────────────────────────────────────────────

class ParsedIntent(BaseModel):
    intent: str = Field(description="PascalCase intent, e.g. 'SearchProduct', 'RequestQuote'")
    product_name: Optional[str] = None
    quantity: Optional[int] = None
    confidence: float
    reasoning: str

    @field_validator("confidence")
    @classmethod
    def _check(cls, v: float) -> float:
        if not 0.0 <= v <= 1.0:
            raise ValueError(f"confidence must be 0–1, got {v}")
        return round(v, 2)


class BudgetConstraints(BaseModel):
    max: float
    min: float = 0.0


class BecknIntent(BaseModel):
    item: str
    descriptions: list[str] = Field(description="Tech specs, e.g. ['80gsm', 'A4', 'Cat6']")
    quantity: int
    location_coordinates: str = Field(description="'lat,lon' or raw text if city unknown")
    delivery_timeline: int = Field(description="In hours: 1 day=24h, 1 week=168h")
    budget_constraints: BudgetConstraints

    @field_validator("location_coordinates")
    @classmethod
    def _resolve(cls, v: str) -> str:
        return resolve_location(v)

    @field_validator("delivery_timeline")
    @classmethod
    def _positive(cls, v: int) -> int:
        if v <= 0:
            raise ValueError(f"delivery_timeline must be > 0, got {v}")
        return v


class ParseResult(BaseModel):
    intent: str
    confidence: Optional[float] = None
    beckn_intent: Optional[BecknIntent] = None
    routed_to: Optional[str] = None
