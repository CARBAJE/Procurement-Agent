"""Transaction session store for the two-step procurement flow.

`/compare` runs discover+rank and stores the resulting `ProcurementState`
here keyed by `transaction_id`. `/commit` retrieves the state, applies the
user's selection override, runs select+init+confirm, and updates the entry.
`/status` looks up the stored state to recover BPP context for polling.

The `StateBackend` Protocol isolates storage from the server. `InMemoryBackend`
is the only implementation today.

TODO(persistence): a teammate will implement `PostgresBackend` against the
same Protocol, wired in `server.py::create_app` with no other code changes.
See: Bap-1/docs/ARCHITECTURE.md §7.2 #6 for full blocker context.
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Optional, Protocol

from .state import ProcurementState

logger = logging.getLogger(__name__)

DEFAULT_TTL_SECONDS = 1800.0      # 30 minutes
DEFAULT_SWEEP_INTERVAL = 300.0    # 5 minutes


@dataclass
class _Entry:
    state: ProcurementState
    created_at: float


class StateBackend(Protocol):
    """Swappable storage for procurement session state."""

    def put(self, txn_id: str, state: ProcurementState) -> None: ...
    def get(self, txn_id: str) -> Optional[ProcurementState]: ...
    def delete(self, txn_id: str) -> None: ...
    def sweep(self, now: float, ttl: float) -> int: ...


@dataclass
class InMemoryBackend:
    """Dict-based backend — single-process dev and tests."""

    _store: dict[str, _Entry] = field(default_factory=dict)

    def put(self, txn_id: str, state: ProcurementState) -> None:
        self._store[txn_id] = _Entry(state=state, created_at=time.monotonic())

    def get(self, txn_id: str) -> Optional[ProcurementState]:
        entry = self._store.get(txn_id)
        return entry.state if entry else None

    def delete(self, txn_id: str) -> None:
        self._store.pop(txn_id, None)

    def sweep(self, now: float, ttl: float) -> int:
        expired = [k for k, e in self._store.items() if now - e.created_at > ttl]
        for k in expired:
            del self._store[k]
        return len(expired)

    def __len__(self) -> int:
        return len(self._store)


class TransactionSessionStore:
    """Facade over a `StateBackend` with an async expiration sweeper."""

    def __init__(
        self,
        backend: Optional[StateBackend] = None,
        *,
        ttl_seconds: float = DEFAULT_TTL_SECONDS,
        sweep_interval: float = DEFAULT_SWEEP_INTERVAL,
    ) -> None:
        self._backend: StateBackend = backend or InMemoryBackend()
        self._ttl = ttl_seconds
        self._sweep_interval = sweep_interval
        self._sweeper: Optional[asyncio.Task] = None

    def put(self, txn_id: str, state: ProcurementState) -> None:
        self._backend.put(txn_id, state)

    def get(self, txn_id: str) -> Optional[ProcurementState]:
        return self._backend.get(txn_id)

    def update(self, txn_id: str, **patch) -> ProcurementState:
        current = self._backend.get(txn_id) or {}
        merged: ProcurementState = {**current, **patch}  # type: ignore[typeddict-item]
        self._backend.put(txn_id, merged)
        return merged

    def delete(self, txn_id: str) -> None:
        self._backend.delete(txn_id)

    def sweep_now(self) -> int:
        return self._backend.sweep(time.monotonic(), self._ttl)

    async def start_sweeper(self) -> None:
        if self._sweeper is None or self._sweeper.done():
            self._sweeper = asyncio.create_task(self._sweep_loop())

    async def stop_sweeper(self) -> None:
        if self._sweeper and not self._sweeper.done():
            self._sweeper.cancel()
            try:
                await self._sweeper
            except asyncio.CancelledError:
                pass
            self._sweeper = None

    async def _sweep_loop(self) -> None:
        while True:
            try:
                await asyncio.sleep(self._sweep_interval)
                removed = self._backend.sweep(time.monotonic(), self._ttl)
                if removed:
                    logger.debug("Session sweeper removed %d expired entries", removed)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Session sweeper iteration failed")
