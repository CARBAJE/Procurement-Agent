"""Scoring result dict → scored_offers schema dict."""
from __future__ import annotations


def transform(score: dict) -> dict:
    """Normalize a scoring result to scored_offers column values.

    Type transformations applied:
        composite_score  float 0–1 → total_score float 0–100
    """
    raw = float(score.get("composite_score", score.get("total_score", 0)) or 0)
    total_score = min(100.0, max(0.0, raw * 100))

    tco_raw = score.get("price_value") or score.get("tco_value") or "0"
    try:
        tco = float(tco_raw)
    except (ValueError, TypeError):
        tco = 0.0

    return {
        "rank":         int(score.get("rank") or 1),
        "total_score":  total_score,
        "tco_value":    tco,
        "explanation":  score.get("explanation") or "Automated scoring",
    }
