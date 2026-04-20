-- 03_procurement_requests.sql
-- Entity 2: ProcurementRequest
-- Root record of every purchase request. Anchor of the entire agent decision chain.
-- Store: PostgreSQL 16
-- FK: users(user_id)

CREATE TABLE IF NOT EXISTS procurement_requests (
    request_id      UUID                PRIMARY KEY DEFAULT uuid_generate_v4(),
    requester_id    UUID                NOT NULL
                                        REFERENCES users(user_id) ON DELETE RESTRICT,
    raw_input_text  TEXT                NOT NULL,
    channel         channel_type        NOT NULL,
    urgency_flag    BOOLEAN             NOT NULL DEFAULT FALSE,
    category        VARCHAR(100),
    status          procurement_status  NOT NULL DEFAULT 'draft',
    created_at      TIMESTAMP           NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMP           NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE procurement_requests IS
    'Root record of every purchase request; anchor of the entire agent decision chain.';
COMMENT ON COLUMN procurement_requests.raw_input_text IS
    'Exact natural-language text submitted by the user, unmodified.';
COMMENT ON COLUMN procurement_requests.urgency_flag IS
    'TRUE when text contains the URGENT: prefix — activates emergency approval mode.';
COMMENT ON COLUMN procurement_requests.status IS
    'Lifecycle: draft→parsing→discovering→scoring→negotiating→pending_approval→confirmed|cancelled.';
