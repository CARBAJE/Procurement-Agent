"""Pytest configuration — make ``src/`` importable as the ``src`` package.

The Negotiation Engine ships as a flat service directory with no editable
install. Inserting the service root onto ``sys.path`` here lets tests use
absolute imports (``from src.guardrails import ...``) regardless of where
pytest is invoked from, matching the convention used by sibling services
such as ``services/ComparativeAndScoreing``.
"""
from __future__ import annotations

import sys
from pathlib import Path

_SERVICE_ROOT = Path(__file__).resolve().parent
if str(_SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(_SERVICE_ROOT))
