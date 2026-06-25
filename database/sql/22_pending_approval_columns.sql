-- 22_pending_approval_columns.sql
-- Idempotent: adds two nullable columns to procurement_requests so a pending
-- approval can be resumed even after the in-memory session TTL expires.

ALTER TABLE procurement_requests
  ADD COLUMN IF NOT EXISTS pending_chosen_item_id  VARCHAR(255),
  ADD COLUMN IF NOT EXISTS pending_transaction_id  VARCHAR(255);

COMMENT ON COLUMN procurement_requests.pending_chosen_item_id IS
  'item_id selected by the requester before threshold check triggered pending_approval.';
COMMENT ON COLUMN procurement_requests.pending_transaction_id IS
  'BAP session transaction_id — allows the approver to resume arun_commit() if session is still live.';
