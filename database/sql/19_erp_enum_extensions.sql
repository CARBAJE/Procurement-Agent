-- 19_erp_enum_extensions.sql
-- Phase 3 / Milestone 2 — ERP Integration.
--
-- Extends two existing enums so the outbox can express its in-flight state
-- and so the local-dev "mock" vendor is a first-class system identifier.
--
-- Must run in its OWN transaction (PostgreSQL 12+ allows ALTER TYPE ADD VALUE
-- inside a transaction block, but the newly added value cannot be referenced
-- in the same transaction — see 19b_erp_sync_records_outbox.sql, which uses
-- 'in_progress' in a partial-index WHERE clause).

-- erp_sync_status: existing values success | failed | pending.
ALTER TYPE erp_sync_status ADD VALUE IF NOT EXISTS 'in_progress';

-- erp_system_type: existing values sap_s4hana | oracle_erp_cloud.
ALTER TYPE erp_system_type ADD VALUE IF NOT EXISTS 'mock';
