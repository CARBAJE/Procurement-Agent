"""All data-transfer objects for the IntentParser service."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, field_validator

from shared.models import BecknIntent, BudgetConstraints, DiscoverOffering  # noqa: F401

__all__ = [
    "BecknIntent",
    "BudgetConstraints",
    "DiscoverOffering",
    "ParsedIntent",
    "ValidationZone",
    "CacheMatch",
    "ValidationResult",
    "ParseResponse",
]


# ── Stage 1 output ────────────────────────────────────────────────────────────


class ParsedIntent(BaseModel):
    intent: str = Field(description="PascalCase intent, e.g. 'SearchProduct'")
    product_name: Optional[str] = None
    quantity: Optional[int] = None
    confidence: float
    reasoning: str

    @field_validator("confidence")
    @classmethod
    def _check_range(cls, v: float) -> float:
        if not 0.0 <= v <= 1.0:
            raise ValueError(f"confidence must be 0–1, got {v}")
        return round(v, 2)


# ── Stage 3 types ─────────────────────────────────────────────────────────────


class ValidationZone(str, Enum):
    VALIDATED = "VALIDATED"
    AMBIGUOUS = "AMBIGUOUS"
    CACHE_MISS = "CACHE_MISS"


@dataclass
class CacheMatch:
    item_name: str
    bpp_id: str
    similarity: float


@dataclass
class ValidationResult:
    zone: ValidationZone
    top_match: Optional[CacheMatch] = None
    mcp_validated: bool = False
    mcp_item_name: Optional[str] = None
    mcp_bpp_id: Optional[str] = None
    mcp_bpp_uri: Optional[str] = None
    not_found: bool = False
    broadened_item_name: Optional[str] = None


# ── Final API response ────────────────────────────────────────────────────────


class ParseResponse(BaseModel):
    intent: str
    confidence: Optional[float] = None
    beckn_intent: Optional[BecknIntent] = None
    validation: Optional[dict] = None
    recovery_log: list[str] = Field(default_factory=list)
    routed_to: Optional[str] = None
