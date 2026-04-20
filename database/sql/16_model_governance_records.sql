-- 16_model_governance_records.sql
-- Entity 16: ModelGovernanceRecord
-- Version registry and evaluation metrics for each AI model.
-- Weekly evaluation pipeline updates accuracy_score and override_rate.
-- Auto-triggers status=review_triggered when metrics fall below thresholds.
-- Store: PostgreSQL 16 · Traces: LangSmith

CREATE TABLE IF NOT EXISTS model_governance_records (
    record_id           UUID                    PRIMARY KEY DEFAULT uuid_generate_v4(),
    model_name          model_name_type         NOT NULL,
    model_version       VARCHAR(50)             NOT NULL,
    provider            ai_provider_type        NOT NULL,
    accuracy_score      FLOAT                   NOT NULL
                                                CHECK (accuracy_score >= 0.0 AND accuracy_score <= 1.0),
    override_rate       FLOAT                   NOT NULL
                                                CHECK (override_rate >= 0.0 AND override_rate <= 1.0),
    evaluation_date     DATE                    NOT NULL,
    status              governance_status_type  NOT NULL DEFAULT 'active',
    CONSTRAINT uq_model_evaluation UNIQUE (model_name, model_version, evaluation_date)
);

COMMENT ON TABLE model_governance_records IS
    'AI model version registry and weekly evaluation metrics. Feeds auto review_triggered status.';
COMMENT ON COLUMN model_governance_records.accuracy_score IS
    'Thresholds: intent_parsing<0.95 | comparison_scoring<0.85 | negotiation_strategy<0.80 → review_triggered.';
COMMENT ON COLUMN model_governance_records.override_rate IS
    'Thresholds: intent_parsing>0.10 | comparison_scoring>0.30 | negotiation_strategy>0.25 → review_triggered.';
