"""Feature extraction from CatalogNormalizer payloads.

Converts a session's list of catalog items into the canonical
``(n, 3)`` feature matrix ``[price, speed, risk]`` consumed by
``Phase2Scorer``. All three features are bounded to ``[0, 1]`` with
"higher = better" semantics:

  - ``price``: ``1 - minmax(price_value)``         — cheaper is better
  - ``speed``: ``1 - minmax(fulfillment_hours)``   — faster is better
  - ``risk`` : ``minmax(rating)``                  — higher rating is better

When a feature has zero variance within the session it is set to ``1.0``
for every item (neutral prior — the linear scorer cannot discriminate on
a constant column anyway).
"""
from __future__ import annotations

import re
from typing import Any

import numpy as np
import torch

__all__ = [
    "FEATURE_ORDER",
    "extract_features_from_catalog",
    "extract_features_tensor",
]

FEATURE_ORDER: tuple[str, str, str] = ("price", "speed", "risk")

_PRICE_KEYS = ("price_value", "price")
_DELIVERY_KEYS = ("fulfillment_hours", "delivery_time_hours", "delivery_time")
_RATING_KEYS = ("rating", "risk_score")

_NUMERIC_RE = re.compile(r"[^0-9.\-eE]")


def _to_float(value: Any, default: float = 0.0) -> float:
    """Best-effort coercion of ``value`` into a float.

    Strips currency symbols, thousands separators, and other non-numeric
    characters from strings (e.g. ``"₹ 1,200"`` -> ``1200.0``). Returns
    ``default`` when parsing fails or the input is ``None``.
    """
    if value is None:
        return float(default)
    if isinstance(value, bool):  # bool is subclass of int — guard first
        return float(int(value))
    if isinstance(value, (int, float)):
        if np.isnan(value) or np.isinf(value):
            return float(default)
        return float(value)
    text = str(value).strip()
    if not text:
        return float(default)
    cleaned = _NUMERIC_RE.sub("", text)
    if cleaned in ("", "-", ".", "-.", "e", "E"):
        return float(default)
    try:
        return float(cleaned)
    except ValueError:
        return float(default)


def _pick(item: dict, keys: tuple[str, ...]) -> Any:
    for k in keys:
        if k in item and item[k] is not None:
            return item[k]
    return None


def _minmax_invert(col: np.ndarray, invert: bool) -> np.ndarray:
    """Min-max scale ``col`` to ``[0, 1]``; if ``invert``, return ``1 - x``.

    Constant columns collapse to the neutral value ``1.0``.
    """
    lo, hi = float(col.min()), float(col.max())
    if hi - lo <= 0.0:
        return np.ones_like(col, dtype=np.float32)
    scaled = (col - lo) / (hi - lo)
    if invert:
        scaled = 1.0 - scaled
    return scaled.astype(np.float32)


def extract_features_from_catalog(items: list[dict]) -> np.ndarray:
    """Build the ``(n, 3)`` feature matrix from a list of catalog dicts.

    Items must expose at least a price field (``price_value`` or ``price``)
    and a delivery field (``fulfillment_hours`` / ``delivery_time_hours`` /
    ``delivery_time``). Rating (``rating`` or ``risk_score``) is optional —
    when entirely absent the risk column defaults to ``0.5`` for every item.
    """
    if not items:
        return np.zeros((0, 3), dtype=np.float32)

    n = len(items)
    raw_price = np.empty(n, dtype=np.float64)
    raw_speed = np.empty(n, dtype=np.float64)
    raw_rating = np.empty(n, dtype=np.float64)
    has_any_rating = False

    for i, item in enumerate(items):
        raw_price[i] = _to_float(_pick(item, _PRICE_KEYS), default=0.0)
        raw_speed[i] = _to_float(_pick(item, _DELIVERY_KEYS), default=0.0)
        rating_val = _pick(item, _RATING_KEYS)
        if rating_val is not None:
            has_any_rating = True
            raw_rating[i] = _to_float(rating_val, default=0.5)
        else:
            raw_rating[i] = 0.5

    x_price = _minmax_invert(raw_price, invert=True)
    x_speed = _minmax_invert(raw_speed, invert=True)
    if has_any_rating:
        x_risk = _minmax_invert(raw_rating, invert=False)
    else:
        x_risk = np.full(n, 0.5, dtype=np.float32)

    return np.stack([x_price, x_speed, x_risk], axis=1).astype(np.float32)


def extract_features_tensor(items: list[dict]) -> torch.Tensor:
    """Thin tensor wrapper around :func:`extract_features_from_catalog`."""
    return torch.from_numpy(extract_features_from_catalog(items)).to(torch.float32)
