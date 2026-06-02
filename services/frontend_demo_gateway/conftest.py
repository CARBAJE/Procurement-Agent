"""Pytest configuration — make the gateway package importable.

The gateway lives at ``services/frontend_demo_gateway/``. We put the
*parent* of that directory (``services/``) on ``sys.path`` so tests can
do ``from frontend_demo_gateway.main import app`` — the same import
style production code (and uvicorn) uses.
"""
from __future__ import annotations

import sys
from pathlib import Path

_SERVICES_ROOT = Path(__file__).resolve().parent.parent
if str(_SERVICES_ROOT) not in sys.path:
    sys.path.insert(0, str(_SERVICES_ROOT))
