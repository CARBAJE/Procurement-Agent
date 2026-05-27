-- 19b_erp_sync_records_outbox.sql
-- Phase 3 / Milestone 2 — ERP Integration.
--
-- Promotes erp_sync_records (entity 13) into a durable outbox for vendor
-- PO push. Purely additive — no new table, no destructive change.
--
-- Depends on the enum extensions in 19_erp_enum_extensions.sql (must run
-- first; the partial-index WHERE clause references the new 'in_progress'
-- enum value).

-- ──────────────────────────────────────────────────────────────────────────────
-- 1. Operational columns required to use this row as a retryable outbox entry.
-- ──────────────────────────────────────────────────────────────────────────────

ALTER TABLE erp_sync_records
    ADD COLUMN IF NOT EXISTS idempotency_key  VARCHAR(128),
    ADD COLUMN IF NOT EXISTS attempts         INTEGER       NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS next_attempt_at  TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    ADD COLUMN IF NOT EXISTS lease_until      TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS worker_id        VARCHAR(64),
    ADD COLUMN IF NOT EXISTS last_error       TEXT,
    ADD COLUMN IF NOT EXISTS payload          JSONB,
    ADD COLUMN IF NOT EXISTS updated_at       TIMESTAMPTZ   NOT NULL DEFAULT NOW();

-- po_id was originally NOT NULL with a FK to purchase_orders(po_id). The outbox
-- flow for M3.2 enqueues a sync attempt BEFORE the canonical purchase_orders
-- row exists (that row belongs to the persistence teammate's work, ARCHITECTURE
-- §7.2 #6). Make po_id nullable — the FK still enforces referential integrity
-- when present.  Idempotent on already-nullable columns.
ALTER TABLE erp_sync_records ALTER COLUMN po_id DROP NOT NULL;

COMMENT ON COLUMN erp_sync_records.idempotency_key IS
    'sha256(transaction_id|vendor|sync_type) — enforces at-most-once enqueue per (txn, vendor, kind) and is forwarded as the Idempotency-Key header to vendors that honor it.';
COMMENT ON COLUMN erp_sync_records.attempts IS
    'Total push attempts so far. DLQ when status=failed AND attempts >= MAX_ATTEMPTS (see worker.BACKOFF).';
COMMENT ON COLUMN erp_sync_records.next_attempt_at IS
    'Earliest wall-clock at which the worker may claim this row. Bumped by the exponential backoff schedule on each transient failure.';
COMMENT ON COLUMN erp_sync_records.lease_until IS
    'Set by the worker on claim. Another worker may reclaim if status=in_progress AND lease_until < NOW().';
COMMENT ON COLUMN erp_sync_records.worker_id IS
    'Opaque worker identifier (hostname:pid or k8s pod). Diagnostic only.';
COMMENT ON COLUMN erp_sync_records.payload IS
    'Vendor-neutral NormalizedPO JSON at enqueue time. Lets a different replica pick up the row without orchestrator memory.';


-- ──────────────────────────────────────────────────────────────────────────────
-- 2. Indexes.
--    a) idempotency_key UNIQUE (partial — NULL allowed for legacy rows pre-M3.2)
--    b) Hot-path index for the worker's claim query.
--
-- The partial-index WHERE clause references the 'in_progress' enum value,
-- which is why this file must NOT be merged with 19_erp_enum_extensions.sql —
-- PG forbids using a newly-added enum value in the same transaction that
-- added it.
-- ──────────────────────────────────────────────────────────────────────────────

CREATE UNIQUE INDEX IF NOT EXISTS uq_erp_sync_idempotency
    ON erp_sync_records (idempotency_key)
    WHERE idempotency_key IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_erp_sync_due
    ON erp_sync_records (next_attempt_at)
    WHERE status IN ('pending', 'in_progress');
