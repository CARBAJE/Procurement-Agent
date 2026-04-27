"""Comparative scoring engine — Phase 1: cheapest price wins."""
from __future__ import annotations


def score(offerings: list[dict]) -> dict | None:
    """Rank offerings and return the best one.

    Phase 1: minimum price_value wins.
    Returns None if offerings is empty.
    """
    if not offerings:
        return None
    return min(offerings, key=lambda o: float(o["price_value"]))
