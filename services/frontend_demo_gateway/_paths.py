"""Path injection — make sibling production services importable.

Side-effect-only module. Importing this places the
``services/ComparativeAndScoreing`` and ``services/negotiation_engine``
roots on ``sys.path`` so we can do::

    from core.model import Phase2Scorer
    from src.graph import build_graph

…using the same import paths the production prediction-API and
negotiation-engine entrypoints use. This keeps the demo gateway's
math + state machinery *identical* to production — no vendored copies,
no parallel implementations.
"""
from __future__ import annotations

import sys
from pathlib import Path

_SERVICES_ROOT = Path(__file__).resolve().parent.parent

# Order matters: insert at the front so our siblings win against any
# accidentally installed homonyms in the env's site-packages.
for service_dir_name in ("ComparativeAndScoreing", "negotiation_engine"):
    candidate = _SERVICES_ROOT / service_dir_name
    if candidate.is_dir():
        candidate_str = str(candidate)
        if candidate_str not in sys.path:
            sys.path.insert(0, candidate_str)
