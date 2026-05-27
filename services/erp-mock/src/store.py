"""In-memory PO store keyed by transaction_id — for vendor-side idempotency."""
from __future__ import annotations

from threading import Lock
from typing import Any

_data: dict[str, dict[str, Any]] = {}
_lock = Lock()


def get(transaction_id: str) -> dict[str, Any] | None:
    with _lock:
        return _data.get(transaction_id)


def put(transaction_id: str, record: dict[str, Any]) -> None:
    with _lock:
        _data[transaction_id] = record


def failure_count(transaction_id: str) -> int:
    """Tracks how many 5xx the mock has returned for this txn — for the
    `po_create_fails` scenario which fails N times then succeeds."""
    with _lock:
        rec = _data.setdefault(transaction_id + ":__failures", {"n": 0})
        return rec["n"]


def increment_failure(transaction_id: str) -> int:
    with _lock:
        rec = _data.setdefault(transaction_id + ":__failures", {"n": 0})
        rec["n"] += 1
        return rec["n"]
