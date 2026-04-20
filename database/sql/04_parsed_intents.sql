-- 04_parsed_intents.sql
-- Entity 3: ParsedIntent
-- Intent classification produced by the NL Intent Parser (Stage 1 of 2).
-- Store: PostgreSQL 16
-- FK: procurement_requests(request_id) — 1:1 relationship (UNIQUE)

CREATE TABLE IF NOT EXISTS parsed_intents (
    intent_id           UUID                PRIMARY KEY DEFAULT uuid_generate_v4(),
    request_id          UUID                NOT NULL UNIQUE
                                            REFERENCES procurement_requests(request_id) ON DELETE CASCADE,
    intent_class        intent_class_type   NOT NULL,
    confidence_score    FLOAT               NOT NULL
                                            CHECK (confidence_score >= 0.0 AND confidence_score <= 1.0),
    model_version       VARCHAR(50)         NOT NULL,
    parsed_at           TIMESTAMP           NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE parsed_intents IS
    'Stage-1 NL Intent Parser output: classification before Beckn field extraction.';
COMMENT ON COLUMN parsed_intents.confidence_score IS
    'Classification probability [0.0–1.0]. Target: >= 0.95 for intent_class=procurement.';
COMMENT ON COLUMN parsed_intents.intent_class IS
    'Only procurement records advance to BecknIntent creation.';
