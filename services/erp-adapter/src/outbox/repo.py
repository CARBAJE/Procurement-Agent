"""Outbox repository for vendor PO push.

The "outbox" is the existing `erp_sync_records` table promoted by migration 19
to carry retry/lease/idempotency state — no new table.

Two implementations behind a single Protocol:

  * AsyncpgOutboxRepo — production. SELECT ... FOR UPDATE SKIP LOCKED claim,
    lease-based reclaim of crashed worker rows.
  * InMemoryOutboxRepo — used when the DB pool fails to come up (dev/CI).
    Same semantics (idempotency, lease, backoff) protected by a Lock so
    concurrent worker tasks behave correctly. The adapter falls back to this
    automatically — mirrors services/analytics's mock-data fallback.

Both implementations expose the same surface so the worker code is identical.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import socket
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Optional, Protocol
from uuid import UUID, uuid4

logger = logging.getLogger(__name__)


# ── Constants ────────────────────────────────────────────────────────────────

SYNC_TYPE_PO_PUSH = "po_creation"   # matches erp_sync_type enum value
BACKOFF_SCHEDULE = (5, 30, 120, 600, 3600)  # seconds — len == MAX_ATTEMPTS
MAX_ATTEMPTS = len(BACKOFF_SCHEDULE)
LEASE_DURATION = timedelta(minutes=5)

WORKER_ID = f"{socket.gethostname()}:{int(time.time())%100_000}"


def compute_idempotency_key(transaction_id: str, vendor: str, sync_type: str = SYNC_TYPE_PO_PUSH) -> str:
    return hashlib.sha256(f"{transaction_id}|{vendor}|{sync_type}".encode()).hexdigest()


# ── Row shape (vendor-neutral, mirrors the table) ────────────────────────────

@dataclass
class OutboxRow:
    sync_id: UUID
    transaction_id: str
    vendor: str            # logical vendor: 'mock' | 'sap' | 'oracle'
    erp_system: str        # DB enum: 'mock' | 'sap_s4hana' | 'oracle_erp_cloud'
    sync_type: str
    status: str            # pending | in_progress | success | failed
    attempts: int
    next_attempt_at: datetime
    lease_until: Optional[datetime]
    worker_id: Optional[str]
    erp_reference_id: Optional[str]
    last_error: Optional[str]
    idempotency_key: str
    payload: dict[str, Any]
    created_at: datetime
    updated_at: datetime

    def is_terminal(self) -> bool:
        return self.status in ("success", "failed")


def vendor_to_erp_system(vendor: str) -> str:
    """Map our internal vendor identifier to the DB enum erp_system_type."""
    return {
        "sap":    "sap_s4hana",
        "oracle": "oracle_erp_cloud",
        "mock":   "mock",
    }.get(vendor, vendor)


# ── Protocol ─────────────────────────────────────────────────────────────────

class OutboxRepo(Protocol):
    async def insert_pending(
        self,
        *,
        transaction_id: str,
        vendor: str,
        payload: dict[str, Any],
    ) -> tuple[OutboxRow, bool]:
        """Insert a new row in 'pending' or return the existing one if a row
        with the same idempotency_key already exists.

        Returns (row, inserted_now). `inserted_now` is False when the row
        already existed — callers should not treat that as an error.
        """

    async def get(self, sync_id: UUID) -> Optional[OutboxRow]: ...

    async def claim_batch(self, *, limit: int) -> list[OutboxRow]:
        """Atomic claim — transitions matching rows to 'in_progress' and
        bumps `attempts` + sets `lease_until`. Rows are eligible when
        status='pending' AND next_attempt_at <= NOW(), OR status='in_progress'
        AND lease_until < NOW() (reclaim of crashed worker)."""

    async def mark_success(self, sync_id: UUID, *, erp_reference_id: str) -> None: ...

    async def reschedule(self, sync_id: UUID, *, delay_seconds: float, error: str) -> None:
        """Push the row back to 'pending' with next_attempt_at = NOW()+delay."""

    async def mark_dead(self, sync_id: UUID, *, error: str) -> None:
        """Mark 'failed' permanently — exhausted retries (status='failed' AND
        attempts >= MAX_ATTEMPTS) or vendor returned a permanent error."""

    async def update_inbound_state(
        self, *, transaction_id: str, vendor: str, erp_reference_id: str | None,
    ) -> "OutboxRow | None":
        """Apply an inbound webhook update to the matching outbox row.

        Looks up by (transaction_id, vendor) — uses idempotency_key derived
        from the same inputs the enqueue path used. Sets erp_reference_id if
        not already set, bumps updated_at. Returns the row or None if no
        match (e.g. webhook arrived for a transaction we never pushed)."""

    async def replay(self, sync_id: UUID) -> "OutboxRow | None":
        """Reset a DLQ'd row (status=failed) back to pending and let the worker
        try again. Resets attempts to 0 and clears last_error.

        Returns the refreshed row on success, or None when the row is missing
        or not in 'failed' state — replay is only valid for DLQ entries."""


# ── Asyncpg implementation ───────────────────────────────────────────────────

class AsyncpgOutboxRepo:
    vendor: str = "asyncpg"

    def __init__(self, pool, *, lease_duration: timedelta = LEASE_DURATION) -> None:
        self._pool = pool
        self._lease_duration = lease_duration

    async def insert_pending(self, *, transaction_id, vendor, payload):
        idem = compute_idempotency_key(transaction_id, vendor)
        erp_system = vendor_to_erp_system(vendor)
        async with self._pool.acquire() as c:
            # Idempotent insert: ON CONFLICT on idempotency_key returns existing row.
            row = await c.fetchrow(
                """
                INSERT INTO erp_sync_records (
                    po_id, erp_system, sync_type, status, attempts,
                    next_attempt_at, idempotency_key, payload
                ) VALUES (
                    NULL, $1::erp_system_type, $2::erp_sync_type, 'pending',
                    0, NOW(), $3, $4
                )
                ON CONFLICT (idempotency_key) WHERE idempotency_key IS NOT NULL
                  DO UPDATE SET updated_at = erp_sync_records.updated_at
                RETURNING sync_id, status, attempts, next_attempt_at, lease_until,
                          worker_id, erp_reference_id, last_error, synced_at, updated_at,
                          (xmax = 0) AS inserted
                """,
                erp_system, SYNC_TYPE_PO_PUSH, idem, payload,
            )
            return (
                OutboxRow(
                    sync_id=row["sync_id"],
                    transaction_id=transaction_id,
                    vendor=vendor,
                    erp_system=erp_system,
                    sync_type=SYNC_TYPE_PO_PUSH,
                    status=row["status"],
                    attempts=row["attempts"],
                    next_attempt_at=row["next_attempt_at"],
                    lease_until=row["lease_until"],
                    worker_id=row["worker_id"],
                    erp_reference_id=row["erp_reference_id"],
                    last_error=row["last_error"],
                    idempotency_key=idem,
                    payload=payload,
                    # DB column is named `synced_at` (migration 13); we expose
                    # it via the `created_at` field on OutboxRow so the InMemory
                    # and Asyncpg impls share the same Python API.
                    created_at=row["synced_at"],
                    updated_at=row["updated_at"],
                ),
                bool(row["inserted"]),
            )

    async def get(self, sync_id):
        async with self._pool.acquire() as c:
            row = await c.fetchrow(
                "SELECT * FROM erp_sync_records WHERE sync_id = $1", sync_id
            )
        if row is None:
            return None
        return self._row(row)

    async def claim_batch(self, *, limit):
        async with self._pool.acquire() as c, c.transaction():
            rows = await c.fetch(
                """
                SELECT sync_id FROM erp_sync_records
                 WHERE sync_type = $1::erp_sync_type
                   AND (
                        (status = 'pending'      AND next_attempt_at <= NOW())
                     OR (status = 'in_progress'  AND lease_until      < NOW())
                   )
                 ORDER BY next_attempt_at
                 FOR UPDATE SKIP LOCKED
                 LIMIT $2
                """,
                SYNC_TYPE_PO_PUSH, limit,
            )
            ids = [r["sync_id"] for r in rows]
            if not ids:
                return []
            claimed = await c.fetch(
                """
                UPDATE erp_sync_records
                   SET status      = 'in_progress',
                       attempts    = attempts + 1,
                       lease_until = NOW() + ($1::INT || ' seconds')::interval,
                       worker_id   = $2,
                       updated_at  = NOW()
                 WHERE sync_id = ANY($3::uuid[])
                 RETURNING *
                """,
                int(self._lease_duration.total_seconds()), WORKER_ID, ids,
            )
            return [self._row(r) for r in claimed]

    async def mark_success(self, sync_id, *, erp_reference_id):
        async with self._pool.acquire() as c:
            await c.execute(
                """
                UPDATE erp_sync_records
                   SET status = 'success',
                       erp_reference_id = $1,
                       lease_until = NULL,
                       last_error = NULL,
                       updated_at = NOW()
                 WHERE sync_id = $2
                """,
                erp_reference_id, sync_id,
            )

    async def reschedule(self, sync_id, *, delay_seconds, error):
        async with self._pool.acquire() as c:
            await c.execute(
                """
                UPDATE erp_sync_records
                   SET status = 'pending',
                       next_attempt_at = NOW() + ($1::INT || ' seconds')::interval,
                       lease_until = NULL,
                       last_error = $2,
                       updated_at = NOW()
                 WHERE sync_id = $3
                """,
                int(delay_seconds), error, sync_id,
            )

    async def mark_dead(self, sync_id, *, error):
        async with self._pool.acquire() as c:
            await c.execute(
                """
                UPDATE erp_sync_records
                   SET status = 'failed',
                       lease_until = NULL,
                       last_error = $1,
                       updated_at = NOW()
                 WHERE sync_id = $2
                """,
                error, sync_id,
            )

    async def update_inbound_state(self, *, transaction_id, vendor, erp_reference_id):
        idem = compute_idempotency_key(transaction_id, vendor)
        async with self._pool.acquire() as c:
            row = await c.fetchrow(
                """
                UPDATE erp_sync_records
                   SET erp_reference_id = COALESCE(erp_reference_id, $1),
                       updated_at = NOW()
                 WHERE idempotency_key = $2
                 RETURNING *
                """,
                erp_reference_id, idem,
            )
        return self._row(row) if row else None

    async def replay(self, sync_id):
        async with self._pool.acquire() as c:
            row = await c.fetchrow(
                """
                UPDATE erp_sync_records
                   SET status = 'pending',
                       attempts = 0,
                       next_attempt_at = NOW(),
                       lease_until = NULL,
                       last_error = NULL,
                       updated_at = NOW()
                 WHERE sync_id = $1 AND status = 'failed'
                 RETURNING *
                """,
                sync_id,
            )
        return self._row(row) if row else None

    @staticmethod
    def _row(r) -> OutboxRow:
        # Reverse-map enum erp_system_type → our vendor identifier.
        inverse = {"sap_s4hana": "sap", "oracle_erp_cloud": "oracle", "mock": "mock"}
        # `payload` is JSONB — asyncpg may give us a string or a dict depending
        # on pool config; coerce defensively.
        payload = r["payload"] or {}
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except Exception:
                payload = {}
        return OutboxRow(
            sync_id=r["sync_id"],
            transaction_id=str(payload.get("transaction_id") or "") if payload else "",
            vendor=inverse.get(r["erp_system"], r["erp_system"]),
            erp_system=r["erp_system"],
            sync_type=r["sync_type"],
            status=r["status"],
            attempts=r["attempts"],
            next_attempt_at=r["next_attempt_at"],
            lease_until=r["lease_until"],
            worker_id=r["worker_id"],
            erp_reference_id=r["erp_reference_id"],
            last_error=r["last_error"],
            idempotency_key=r["idempotency_key"] or "",
            payload=payload,
            # See insert_pending: the DB column is `synced_at`.
            created_at=r["synced_at"],
            updated_at=r["updated_at"],
        )


# ── In-memory implementation (DB-less fallback) ──────────────────────────────

@dataclass
class _MemRow:
    sync_id: UUID
    transaction_id: str
    vendor: str
    erp_system: str
    sync_type: str
    status: str
    attempts: int
    next_attempt_at: datetime
    lease_until: Optional[datetime]
    worker_id: Optional[str]
    erp_reference_id: Optional[str]
    last_error: Optional[str]
    idempotency_key: str
    payload: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class InMemoryOutboxRepo:
    """Process-local outbox — survives nothing but a single process lifetime.

    Used when the asyncpg pool fails to come up (e.g. local dev without a
    Postgres). Semantics match the asyncpg version closely enough for the
    smoke test, including atomic claim-with-attempts-bump via an asyncio.Lock.
    """

    def __init__(self, *, lease_duration: timedelta = LEASE_DURATION) -> None:
        self._rows: dict[UUID, _MemRow] = {}
        self._by_idem: dict[str, UUID] = {}
        self._lock = asyncio.Lock()
        self._lease = lease_duration

    async def insert_pending(self, *, transaction_id, vendor, payload):
        idem = compute_idempotency_key(transaction_id, vendor)
        async with self._lock:
            existing_id = self._by_idem.get(idem)
            if existing_id is not None:
                r = self._rows[existing_id]
                return self._to_row(r), False
            now = datetime.now(timezone.utc)
            sync_id = uuid4()
            r = _MemRow(
                sync_id=sync_id,
                transaction_id=transaction_id,
                vendor=vendor,
                erp_system=vendor_to_erp_system(vendor),
                sync_type=SYNC_TYPE_PO_PUSH,
                status="pending",
                attempts=0,
                next_attempt_at=now,
                lease_until=None,
                worker_id=None,
                erp_reference_id=None,
                last_error=None,
                idempotency_key=idem,
                payload=payload,
                created_at=now,
                updated_at=now,
            )
            self._rows[sync_id] = r
            self._by_idem[idem] = sync_id
            return self._to_row(r), True

    async def get(self, sync_id):
        async with self._lock:
            r = self._rows.get(sync_id)
            return self._to_row(r) if r else None

    async def claim_batch(self, *, limit):
        out: list[OutboxRow] = []
        async with self._lock:
            now = datetime.now(timezone.utc)
            for r in sorted(self._rows.values(), key=lambda x: x.next_attempt_at):
                if len(out) >= limit:
                    break
                eligible = (
                    (r.status == "pending" and r.next_attempt_at <= now)
                    or (r.status == "in_progress" and r.lease_until is not None and r.lease_until < now)
                )
                if not eligible:
                    continue
                r.status = "in_progress"
                r.attempts += 1
                r.lease_until = now + self._lease
                r.worker_id = WORKER_ID
                r.updated_at = now
                out.append(self._to_row(r))
        return out

    async def mark_success(self, sync_id, *, erp_reference_id):
        async with self._lock:
            r = self._rows.get(sync_id)
            if r is None:
                return
            r.status = "success"
            r.erp_reference_id = erp_reference_id
            r.lease_until = None
            r.last_error = None
            r.updated_at = datetime.now(timezone.utc)

    async def reschedule(self, sync_id, *, delay_seconds, error):
        async with self._lock:
            r = self._rows.get(sync_id)
            if r is None:
                return
            r.status = "pending"
            r.next_attempt_at = datetime.now(timezone.utc) + timedelta(seconds=delay_seconds)
            r.lease_until = None
            r.last_error = error
            r.updated_at = datetime.now(timezone.utc)

    async def mark_dead(self, sync_id, *, error):
        async with self._lock:
            r = self._rows.get(sync_id)
            if r is None:
                return
            r.status = "failed"
            r.lease_until = None
            r.last_error = error
            r.updated_at = datetime.now(timezone.utc)

    async def update_inbound_state(self, *, transaction_id, vendor, erp_reference_id):
        idem = compute_idempotency_key(transaction_id, vendor)
        async with self._lock:
            sync_id = self._by_idem.get(idem)
            if sync_id is None:
                return None
            r = self._rows[sync_id]
            if r.erp_reference_id is None and erp_reference_id is not None:
                r.erp_reference_id = erp_reference_id
            r.updated_at = datetime.now(timezone.utc)
            return self._to_row(r)

    async def replay(self, sync_id):
        async with self._lock:
            r = self._rows.get(sync_id)
            if r is None or r.status != "failed":
                return None
            now = datetime.now(timezone.utc)
            r.status = "pending"
            r.attempts = 0
            r.next_attempt_at = now
            r.lease_until = None
            r.last_error = None
            r.updated_at = now
            return self._to_row(r)

    @staticmethod
    def _to_row(r: _MemRow) -> OutboxRow:
        return OutboxRow(**r.__dict__)
