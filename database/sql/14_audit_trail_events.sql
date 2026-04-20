-- 14_audit_trail_events.sql
-- Entity 14: AuditTrailEvent
-- Every agent decision recorded with full reasoning_payload.
-- Complies with SOX 404, GDPR, IT Act 2000. Minimum retention: 7 years.
-- Store: PostgreSQL 16 (transactional) + Splunk/ServiceNow (SIEM) + LangSmith (LLM traces)
-- FK: procurement_requests(request_id), purchase_orders(po_id), users(user_id) — all NULLABLE

CREATE TABLE IF NOT EXISTS audit_trail_events (
    event_id            UUID                NOT NULL PRIMARY KEY DEFAULT uuid_generate_v4(),
    request_id          UUID
                                            REFERENCES procurement_requests(request_id) ON DELETE SET NULL,
    po_id               UUID
                                            REFERENCES purchase_orders(po_id) ON DELETE SET NULL,
    actor_id            UUID
                                            REFERENCES users(user_id) ON DELETE SET NULL,
    event_type          audit_event_type    NOT NULL,
    agent_action        TEXT                NOT NULL,
    reasoning_payload   JSONB               NOT NULL DEFAULT '{}',
    kafka_offset        BIGINT              NOT NULL,
    splunk_indexed      BOOLEAN             NOT NULL DEFAULT FALSE,
    event_timestamp     TIMESTAMP           NOT NULL DEFAULT NOW(),
    retention_until     TIMESTAMP           NOT NULL DEFAULT (NOW() + INTERVAL '7 years')
);

COMMENT ON TABLE audit_trail_events IS
    'Complete agent decision log with reasoning. Retention ≥ 7 years (SOX 404 / GDPR / IT Act 2000).';
COMMENT ON COLUMN audit_trail_events.reasoning_payload IS
    'Complete reasoning: inputs, outputs, scores, LLM traces (LangSmith).';
COMMENT ON COLUMN audit_trail_events.kafka_offset IS
    'Kafka offset on the relevant topic; used for event correlation and replay.';
COMMENT ON COLUMN audit_trail_events.actor_id IS
    'NULL for autonomous agent decisions; set when a human performed the action.';
COMMENT ON COLUMN audit_trail_events.splunk_indexed IS
    'TRUE once ingested by Splunk/ServiceNow SIEM pipeline.';
