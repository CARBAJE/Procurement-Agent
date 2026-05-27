"""Background worker — drains the outbox and pushes POs to the vendor.

Lives as an asyncio.Task launched in main._on_startup. One task per replica is
fine: claim_batch already serializes correctly via `FOR UPDATE SKIP LOCKED`
(asyncpg impl) or an asyncio.Lock (in-memory impl).

For each claimed row:
  * Reconstruct NormalizedPO from row.payload
  * Call adapter.push_po(po, idempotency_key)
  * On success                              → mark_success + Redis publish
  * On VendorTransientError + retries left  → reschedule(backoff[attempts-1])
  * On VendorTransientError + retries done  → mark_dead (DLQ)
  * On VendorPermanentError                 → mark_dead

The audit + Prometheus emissions match the schema declared in
observability/{metrics,audit}.py.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Optional

from adapters.base import ERPAdapter, VendorPermanentError, VendorTransientError
from models import NormalizedPO
from observability import audit, metrics
from outbox import BACKOFF_SCHEDULE, MAX_ATTEMPTS, OutboxRepo, OutboxRow
from resilience import CircuitOpenError

logger = logging.getLogger(__name__)

POLL_INTERVAL = 2.0      # seconds between empty claim cycles
DEFAULT_CONCURRENCY = 10  # rows per claim


class OutboxWorker:
    def __init__(
        self,
        *,
        repo: OutboxRepo,
        adapter: ERPAdapter,
        redis=None,
        concurrency: int = DEFAULT_CONCURRENCY,
        poll_interval: float = POLL_INTERVAL,
        backoff: tuple[int, ...] = BACKOFF_SCHEDULE,
    ) -> None:
        self._repo = repo
        self._adapter = adapter
        self._redis = redis
        self._concurrency = concurrency
        self._poll_interval = poll_interval
        self._backoff = backoff
        self._task: Optional[asyncio.Task] = None
        self._stop = asyncio.Event()

    def start(self) -> None:
        if self._task is not None:
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._run(), name="erp-outbox-worker")
        logger.info("outbox worker started concurrency=%s backoff=%s", self._concurrency, self._backoff)

    async def stop(self) -> None:
        if self._task is None:
            return
        self._stop.set()
        self._task.cancel()
        try:
            await self._task
        except (asyncio.CancelledError, Exception):
            pass
        self._task = None
        logger.info("outbox worker stopped")

    async def _run(self) -> None:
        while not self._stop.is_set():
            try:
                rows = await self._repo.claim_batch(limit=self._concurrency)
            except Exception as exc:
                logger.warning("outbox claim failed: %s", exc)
                await self._sleep_or_stop(self._poll_interval)
                continue

            if not rows:
                await self._sleep_or_stop(self._poll_interval)
                continue

            await asyncio.gather(*(self._process(row) for row in rows))

    async def _sleep_or_stop(self, seconds: float) -> None:
        try:
            await asyncio.wait_for(self._stop.wait(), timeout=seconds)
        except asyncio.TimeoutError:
            pass

    def _resolve_adapter(self, vendor: str):
        """Pick the right vendor adapter from a possibly-multi facade."""
        a = self._adapter
        for_vendor = getattr(a, "for_vendor", None)
        if callable(for_vendor):
            child = for_vendor(vendor)
            if child is not None:
                return child
        return a

    async def _process(self, row: OutboxRow) -> None:
        vendor = row.vendor
        attempt = row.attempts  # already incremented by claim_batch
        started = time.perf_counter()
        audit.emit("PO_SYNC_ATTEMPT", vendor=vendor, transaction_id=row.transaction_id,
                   sync_id=str(row.sync_id), attempt=attempt)
        try:
            po = NormalizedPO.model_validate(row.payload)
        except Exception as exc:
            await self._repo.mark_dead(row.sync_id, error=f"payload_invalid: {exc}")
            metrics.po_sync_total.labels(vendor=vendor, outcome="permanent_error").inc()
            metrics.po_outbox_dead_total.inc()
            audit.emit("PO_DLQ", vendor=vendor, transaction_id=row.transaction_id,
                       sync_id=str(row.sync_id), reason=f"payload_invalid: {exc}")
            return

        adapter = self._resolve_adapter(vendor)
        try:
            result = await adapter.push_po(po, row.idempotency_key)
        except CircuitOpenError as exc:
            # Treat circuit-open as transient — respects breaker recovery.
            elapsed = time.perf_counter() - started
            metrics.po_sync_duration_seconds.labels(vendor=vendor).observe(elapsed)
            if attempt >= len(self._backoff):
                await self._repo.mark_dead(row.sync_id, error=f"circuit_open_exhausted: {exc}")
                metrics.po_sync_total.labels(vendor=vendor, outcome="dead").inc()
                metrics.po_outbox_dead_total.inc()
                audit.emit("PO_DLQ", vendor=vendor, transaction_id=row.transaction_id,
                           sync_id=str(row.sync_id), attempts=attempt,
                           reason=f"circuit_open: {exc}")
            else:
                delay = self._backoff[min(attempt - 1, len(self._backoff) - 1)]
                await self._repo.reschedule(row.sync_id, delay_seconds=delay, error=str(exc))
                metrics.po_sync_total.labels(vendor=vendor, outcome="retry").inc()
                audit.emit("PO_SYNC_RETRY", vendor=vendor, transaction_id=row.transaction_id,
                           sync_id=str(row.sync_id), attempt=attempt, delay=delay,
                           reason="circuit_open")
            return
        except VendorTransientError as exc:
            elapsed = time.perf_counter() - started
            metrics.po_sync_duration_seconds.labels(vendor=vendor).observe(elapsed)
            if attempt >= len(self._backoff):
                await self._repo.mark_dead(row.sync_id, error=f"transient_exhausted: {exc}")
                metrics.po_sync_total.labels(vendor=vendor, outcome="dead").inc()
                metrics.po_outbox_dead_total.inc()
                audit.emit("PO_DLQ", vendor=vendor, transaction_id=row.transaction_id,
                           sync_id=str(row.sync_id), attempts=attempt, reason=str(exc))
            else:
                delay = self._backoff[min(attempt - 1, len(self._backoff) - 1)]
                await self._repo.reschedule(row.sync_id, delay_seconds=delay, error=str(exc))
                metrics.po_sync_total.labels(vendor=vendor, outcome="retry").inc()
                audit.emit("PO_SYNC_RETRY", vendor=vendor, transaction_id=row.transaction_id,
                           sync_id=str(row.sync_id), attempt=attempt, delay=delay)
            return
        except VendorPermanentError as exc:
            elapsed = time.perf_counter() - started
            metrics.po_sync_duration_seconds.labels(vendor=vendor).observe(elapsed)
            await self._repo.mark_dead(row.sync_id, error=f"permanent: {exc}")
            metrics.po_sync_total.labels(vendor=vendor, outcome="permanent_error").inc()
            metrics.po_outbox_dead_total.inc()
            audit.emit("PO_DLQ", vendor=vendor, transaction_id=row.transaction_id,
                       sync_id=str(row.sync_id), reason=f"permanent: {exc}")
            return
        except Exception as exc:
            # Unexpected — treat as transient with the standard schedule.
            logger.exception("unexpected push_po failure sync_id=%s", row.sync_id)
            elapsed = time.perf_counter() - started
            metrics.po_sync_duration_seconds.labels(vendor=vendor).observe(elapsed)
            if attempt >= len(self._backoff):
                await self._repo.mark_dead(row.sync_id, error=f"unexpected: {exc}")
                metrics.po_sync_total.labels(vendor=vendor, outcome="dead").inc()
                metrics.po_outbox_dead_total.inc()
                audit.emit("PO_DLQ", vendor=vendor, transaction_id=row.transaction_id,
                           sync_id=str(row.sync_id), reason=f"unexpected: {exc}")
            else:
                delay = self._backoff[min(attempt - 1, len(self._backoff) - 1)]
                await self._repo.reschedule(row.sync_id, delay_seconds=delay, error=f"unexpected: {exc}")
                metrics.po_sync_total.labels(vendor=vendor, outcome="retry").inc()
            return

        elapsed = time.perf_counter() - started
        metrics.po_sync_duration_seconds.labels(vendor=vendor).observe(elapsed)
        await self._repo.mark_success(row.sync_id, erp_reference_id=result.erp_reference_id)
        metrics.po_sync_total.labels(vendor=vendor, outcome="success").inc()
        audit.emit("PO_SYNC_SENT", vendor=vendor, transaction_id=row.transaction_id,
                   sync_id=str(row.sync_id), erp_reference_id=result.erp_reference_id,
                   attempts=attempt)

        if self._redis is not None:
            try:
                channel = f"po.committed:{row.transaction_id}"
                msg = json.dumps({
                    "sync_id": str(row.sync_id),
                    "vendor": vendor,
                    "transaction_id": row.transaction_id,
                    "erp_reference_id": result.erp_reference_id,
                    "order_id": row.payload.get("order_id"),
                })
                await self._redis.publish(channel, msg)
            except Exception as exc:
                logger.warning("redis publish failed channel=%s err=%s", channel, exc)
