"""Module-level configuration for the Comparative & Scoring prediction API.

Per project convention (CLAUDE.md), env-driven config lives in module-level
``config.py`` and is read at import time. Never call ``os.getenv(...)`` inline
elsewhere in this service — import from here instead.
"""
from __future__ import annotations

import os

MLFLOW_TRACKING_URI: str = os.getenv("MLFLOW_TRACKING_URI", "http://mlflow-server:5000")
MODEL_NAME: str = os.getenv("MODEL_NAME", "ProcurementRanker")
MODEL_STAGE: str = os.getenv("MODEL_STAGE", "Production")
PORT: int = int(os.getenv("PORT", "8004"))
LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO").upper()
ALLOW_FALLBACK_WEIGHTS: bool = os.getenv("ALLOW_FALLBACK_WEIGHTS", "true").lower() in ("1", "true", "yes")
FALLBACK_WEIGHTS: list[float] = [0.4, 0.3, 0.3]  # [price, speed, risk]
FALLBACK_BIAS: float = 0.0
