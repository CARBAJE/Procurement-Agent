"""Structured audit log — JSONL to stdout.

A dedicated logger so a downstream Splunk/ELK forwarder can route on the
`erp.audit` name. Schema per the plan §Observability: every meaningful
business event becomes one line.
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any, Mapping

_logger = logging.getLogger("erp.audit")
if not _logger.handlers:
    _h = logging.StreamHandler()
    _h.setFormatter(logging.Formatter("%(message)s"))
    _logger.addHandler(_h)
    _logger.propagate = False
    _logger.setLevel(logging.INFO)


def emit(event: str, **fields: Any) -> None:
    """Emit a single audit line as JSON.

    Required fields are caller-provided; we always inject `event` and `ts`.
    Sensitive fields (full payloads, signatures, tokens) must not be passed.
    """
    payload: Mapping[str, Any] = {
        "event": event,
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        **fields,
    }
    _logger.info(json.dumps(payload, default=str))
