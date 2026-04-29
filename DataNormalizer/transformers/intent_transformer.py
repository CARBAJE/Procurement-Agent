"""BecknIntent dict → beckn_intents schema dict."""
from __future__ import annotations


def transform(beckn_intent: dict) -> dict:
    """Normalize a BecknIntent-shaped dict to beckn_intents column values.

    Defaults for NOT NULL columns that may be absent in the source model:
        unit                 → 'units'
        location_coordinates → '0.0,0.0'
        delivery_timeline    → 72 hours
    """
    budget = beckn_intent.get("budget_constraints") or {}

    budget_min: float | None = None
    budget_max: float | None = None
    if budget:
        raw_min = budget.get("min")
        raw_max = budget.get("max")
        if raw_min is not None:
            budget_min = float(raw_min)
        if raw_max is not None:
            budget_max = float(raw_max)

    return {
        "item":                   beckn_intent.get("item") or "unknown",
        "descriptions":           beckn_intent.get("descriptions") or [],
        "quantity":               int(beckn_intent.get("quantity") or 1),
        "unit":                   beckn_intent.get("unit") or "units",
        "location_coordinates":   beckn_intent.get("location_coordinates") or "0.0,0.0",
        "delivery_timeline_hours": int(beckn_intent.get("delivery_timeline") or 72),
        "budget_min":             budget_min,
        "budget_max":             budget_max,
        "currency":               "INR",
    }
