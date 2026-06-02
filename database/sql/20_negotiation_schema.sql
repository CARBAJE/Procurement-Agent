-- 20_negotiation_schema.sql
-- Negotiation Engine relational schema (Phase 3).
--
-- Provides the durable, queryable audit pin-points the LangGraph state
-- machine relies on. The LangGraph *checkpoint* tables (checkpoints,
-- checkpoint_writes, checkpoint_blobs) are NOT defined here — they are
-- provisioned programmatically by ``AsyncPostgresSaver.setup()`` at engine
-- startup, which is the library's canonical mechanism. Hand-writing them
-- would risk drift against the installed langgraph-checkpoint-postgres
-- version.
--
-- This file is idempotent (IF NOT EXISTS throughout) and self-contained:
-- its FK chain (policy_decision -> round -> session) does not reference any
-- table outside this migration, so it can be applied standalone against a
-- fresh database without running the full 01-19 chain.
--
-- FK dependency order (matches lexicographic apply order within the file):
--   negotiation_session  ->  negotiation_round  ->  negotiation_policy_decision

-- ── Session: one row per negotiation lifecycle ───────────────────────────
CREATE TABLE IF NOT EXISTS negotiation_session (
    transaction_id   TEXT PRIMARY KEY,
    buyer_intent     JSONB,
    category         TEXT,
    status           TEXT NOT NULL DEFAULT 'active'
                     CHECK (status IN ('active', 'completed', 'escalated', 'failed', 'timed_out')),
    final_outcome    TEXT,
    rounds_used      SMALLINT NOT NULL DEFAULT 0,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ── Round: one row per negotiation round per session ─────────────────────
CREATE TABLE IF NOT EXISTS negotiation_round (
    round_id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    transaction_id   TEXT NOT NULL REFERENCES negotiation_session(transaction_id) ON DELETE CASCADE,
    round_no         SMALLINT NOT NULL,
    supplier_id      TEXT,
    our_offer        JSONB,
    their_response   JSONB,
    decision         TEXT CHECK (decision IN ('counter', 'accept', 'reject', 'escalate', 'timeout')),
    started_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    settled_at       TIMESTAMPTZ,
    UNIQUE (transaction_id, round_no)
);

-- ── Policy decision: audit of every guardrail decision ───────────────────
-- The relational pin-point for regulatory queries; mirrors the Kafka
-- ``procurement.negotiation.policy_violations.v1`` event stream. See
-- KnowledgeBase/.../discovery_engine and negotiation_engine/03_hard_guardrails_policy.md.
CREATE TABLE IF NOT EXISTS negotiation_policy_decision (
    decision_id      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    round_id         UUID REFERENCES negotiation_round(round_id) ON DELETE CASCADE,
    transaction_id   TEXT NOT NULL REFERENCES negotiation_session(transaction_id) ON DELETE CASCADE,
    rule_violated    TEXT NOT NULL,                       -- 'G1' … 'G12'
    severity         TEXT NOT NULL DEFAULT 'MEDIUM'
                     CHECK (severity IN ('LOW', 'MEDIUM', 'HIGH')),
    attempted_value  JSONB,
    allowed_value    JSONB,
    action_taken     TEXT NOT NULL DEFAULT 'CLAMP'
                     CHECK (action_taken IN ('CLAMP', 'ESCALATE', 'LOG', 'BLOCK')),
    policy_version   TEXT,
    reviewer         TEXT,                                -- HITL operator if escalated
    decided_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ── Indexes for the common audit-replay access patterns ──────────────────
CREATE INDEX IF NOT EXISTS idx_neg_round_txn
    ON negotiation_round (transaction_id, round_no);
CREATE INDEX IF NOT EXISTS idx_neg_policy_txn
    ON negotiation_policy_decision (transaction_id, decided_at);
CREATE INDEX IF NOT EXISTS idx_neg_policy_rule
    ON negotiation_policy_decision (rule_violated, severity);
