"""parsed_intents + beckn_intents tables."""
from __future__ import annotations

import json
import logging
import uuid as _uuid

from ..db import get_pool

logger = logging.getLogger(__name__)


async def create_parsed_intent(
    request_id: str,
    intent_class: str,
    confidence: float,
    model_version: str,
) -> str:
    """INSERT into parsed_intents, return intent_id (str UUID)."""
    pool = await get_pool()
    # Clamp confidence to valid range
    original_confidence = float(confidence)
    confidence = max(0.0, min(1.0, original_confidence))
    if confidence != original_confidence:
        logger.warning(
            "[intent_repo] confidence %s clamped to %s",
            original_confidence, confidence,
        )
    # Validate intent_class enum
    valid = {"procurement", "query", "support", "out_of_scope"}
    if intent_class in valid:
        ic = intent_class
    else:
        logger.warning(
            "[intent_repo] intent_class %r is not in %s — defaulting to 'out_of_scope'",
            intent_class, sorted(valid),
        )
        ic = "out_of_scope"
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO parsed_intents
                (request_id, intent_class, confidence_score, model_version)
            VALUES ($1, $2::intent_class_type, $3, $4)
            RETURNING intent_id
            """,
            _uuid.UUID(request_id),
            ic,
            confidence,
            model_version or "1.0",
        )
        return str(row["intent_id"])


async def create_beckn_intent(intent_id: str, beckn: dict) -> str:
    """INSERT into beckn_intents, return beckn_intent_id (str UUID).

    Applies defaults for NOT NULL fields that may be absent in the source model:
      - unit                  → 'units'
      - location_coordinates  → '0.0,0.0'
      - delivery_timeline     → 72 hours
    """
    pool = await get_pool()
    budget = beckn.get("budget_constraints") or {}
    budget_min = budget.get("min") if budget else None
    budget_max = budget.get("max") if budget else None

    # Log defaults silently applied to required fields — helps catch upstream bugs.
    if not beckn.get("item"):
        logger.warning("[intent_repo] beckn.item missing — defaulting to 'unknown'")
    if not beckn.get("unit"):
        logger.warning("[intent_repo] beckn.unit missing — defaulting to 'units'")
    if not beckn.get("location_coordinates"):
        logger.warning("[intent_repo] beckn.location_coordinates missing — defaulting to '0.0,0.0'")
    if not beckn.get("delivery_timeline"):
        logger.warning("[intent_repo] beckn.delivery_timeline missing — defaulting to 72h")

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO beckn_intents (
                intent_id, item, descriptions, quantity, unit,
                location_coordinates, delivery_timeline_hours,
                budget_min, budget_max, currency
            )
            VALUES ($1, $2, $3::jsonb, $4, $5, $6, $7, $8, $9, $10)
            RETURNING beckn_intent_id
            """,
            _uuid.UUID(intent_id),
            beckn.get("item") or "unknown",
            json.dumps(beckn.get("descriptions") or []),
            int(beckn.get("quantity") or 1),
            beckn.get("unit") or "units",
            beckn.get("location_coordinates") or "0.0,0.0",
            int(beckn.get("delivery_timeline") or 72),
            float(budget_min) if budget_min is not None else None,
            float(budget_max) if budget_max is not None else None,
            "INR",
        )
        return str(row["beckn_intent_id"])
