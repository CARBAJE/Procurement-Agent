-- 11_approval_decisions.sql
-- Entity 11: ApprovalDecision
-- Approval workflow state machine. Routing determined by amount_total vs User.approval_threshold.
-- Store: PostgreSQL 16 · IdP: Keycloak · Notifications: Slack/Teams webhooks
-- FK: negotiation_outcomes(negotiation_id) — 1:1 (UNIQUE), users(user_id) ×2

CREATE TABLE IF NOT EXISTS approval_decisions (
    approval_id             UUID                        PRIMARY KEY DEFAULT uuid_generate_v4(),
    negotiation_id          UUID                        NOT NULL UNIQUE
                                                        REFERENCES negotiation_outcomes(negotiation_id) ON DELETE RESTRICT,
    requester_id            UUID                        NOT NULL
                                                        REFERENCES users(user_id) ON DELETE RESTRICT,
    approver_id             UUID
                                                        REFERENCES users(user_id) ON DELETE SET NULL,
    approval_level          approval_level_type         NOT NULL,
    amount_total            DECIMAL(15,2)               NOT NULL CHECK (amount_total > 0),
    status                  approval_status_type        NOT NULL DEFAULT 'pending',
    is_emergency            BOOLEAN                     NOT NULL DEFAULT FALSE,
    deadline_at             TIMESTAMP,
    notification_channel    notification_channel_type   NOT NULL,
    decided_at              TIMESTAMP
);

COMMENT ON TABLE approval_decisions IS
    'Approval state machine. Routing: amount <= requester.threshold→auto | <= approver.threshold→manager | else→cfo.';
COMMENT ON COLUMN approval_decisions.approver_id IS
    'NULL for auto-approvals (approval_level=auto).';
COMMENT ON COLUMN approval_decisions.deadline_at IS
    '60-minute countdown for is_emergency=TRUE; if expired without decision → status=auto_approved.';
COMMENT ON COLUMN approval_decisions.amount_total IS
    'Total order value: final_price × quantity. Compared against RBAC thresholds for routing.';
