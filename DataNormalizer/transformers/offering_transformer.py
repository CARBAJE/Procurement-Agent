"""DiscoverOffering dict → seller_offerings schema dict."""
from __future__ import annotations


def transform(offering: dict) -> dict:
    """Normalize a DiscoverOffering-shaped dict to seller_offerings column values.

    Type transformations applied:
        price_value   str → float  (DECIMAL 15,2)
        rating        str → float  (FLOAT 0–5), None if absent
        fulfillment_hours int|None → int (default 24)
    """
    price_raw = offering.get("price_value") or "0"
    try:
        price = float(price_raw)
    except (ValueError, TypeError):
        price = 0.0

    rating_raw = offering.get("rating")
    try:
        quality_rating: float | None = float(rating_raw) if rating_raw else None
    except (ValueError, TypeError):
        quality_rating = None

    delivery_hours = int(offering.get("fulfillment_hours") or 24)
    delivery_hours = max(1, delivery_hours)  # CHECK > 0

    return {
        "item_id":        offering.get("item_id") or "",
        "price":          price,
        "currency":       offering.get("price_currency") or "INR",
        "delivery_eta_hours": delivery_hours,
        "quality_rating": quality_rating,
        "certifications": offering.get("specifications") or [],
        "inventory_count": offering.get("available_quantity"),
        "bpp_uri":        offering.get("bpp_uri") or "",
        "provider_name":  offering.get("provider_name") or "",
    }
