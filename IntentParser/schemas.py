"""Backward-compatible schema re-exports.

New code should import from .models directly.
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel

from .models import BecknIntent, BudgetConstraints, ParsedIntent  # noqa: F401


class ParseResult(BaseModel):
    """Returned by the sync parse_request() entry point (Stage 1+2 only)."""

    intent: str
    confidence: Optional[float] = None
    beckn_intent: Optional[BecknIntent] = None
    routed_to: Optional[str] = None
