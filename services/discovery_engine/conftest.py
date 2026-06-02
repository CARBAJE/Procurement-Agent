"""Pytest configuration — put the service root on ``sys.path``.

Lets tests use absolute imports (``from src.coordinator import ...``)
regardless of where pytest is invoked from, matching the convention
used by the sibling ``negotiation_engine`` service.
"""
from __future__ import annotations

import sys
from pathlib import Path

_SERVICE_ROOT = Path(__file__).resolve().parent
if str(_SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(_SERVICE_ROOT))
