-- 09_scored_offers.sql
-- Entity 9: ScoredOffer
-- Output of the Comparison & Scoring Engine (deterministic Python + GPT-4o ReAct loop).
-- Each normalized offering receives per-dimension scores and a global ranking.
-- Store: PostgreSQL 16
-- FK: seller_offerings(offering_id) — 1:1 (UNIQUE)

CREATE TABLE IF NOT EXISTS scored_offers (
    score_id            UUID            PRIMARY KEY DEFAULT uuid_generate_v4(),
    offering_id         UUID            NOT NULL UNIQUE
                                        REFERENCES seller_offerings(offering_id) ON DELETE CASCADE,
    rank                INTEGER         NOT NULL CHECK (rank > 0),
    total_score         FLOAT           NOT NULL
                                        CHECK (total_score >= 0.0 AND total_score <= 100.0),
    price_score         FLOAT           CHECK (price_score >= 0.0 AND price_score <= 100.0),
    delivery_score      FLOAT           CHECK (delivery_score >= 0.0 AND delivery_score <= 100.0),
    quality_score       FLOAT           CHECK (quality_score >= 0.0 AND quality_score <= 100.0),
    compliance_score    FLOAT           CHECK (compliance_score >= 0.0 AND compliance_score <= 100.0),
    tco_value           DECIMAL(15,2)   NOT NULL,
    explanation_text    TEXT            NOT NULL,
    user_overridden     BOOLEAN         NOT NULL DEFAULT FALSE,
    model_version       VARCHAR(50)     NOT NULL,
    scored_at           TIMESTAMP       NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE scored_offers IS
    'Scoring Engine output. explanation_text is GPT-4o generated; mandatory for audit trail.';
COMMENT ON COLUMN scored_offers.tco_value IS
    'Total Cost of Ownership over the contract period.';
COMMENT ON COLUMN scored_offers.user_overridden IS
    'TRUE when user rejected this recommendation. Triggers recalibration if rate > 30% in 30-day window.';
