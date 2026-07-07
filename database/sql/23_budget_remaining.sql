-- 23_budget_remaining.sql
-- Adds a budget_remaining column to users for per-user spending tracking.
-- Separate from approval_threshold (per-order RBAC limit) so RBAC logic is unchanged.

ALTER TABLE users
    ADD COLUMN IF NOT EXISTS budget_remaining DECIMAL(15,2) NOT NULL DEFAULT 0.00;

-- Initialise existing rows: budget_remaining starts equal to approval_threshold.
UPDATE users
SET budget_remaining = approval_threshold
WHERE budget_remaining = 0.00;

COMMENT ON COLUMN users.budget_remaining IS
    'Remaining procurement budget for this user. Decremented on each confirmed order. '
    'Distinct from approval_threshold which governs per-order auto-approval limits.';
