-- 10_negotiation_outcomes.sql
-- Entity 10: NegotiationOutcome
-- Result of negotiation via Beckn /select.
-- Hard constraint: discount_percent <= 20.0 (non-bypassable).
-- Store: PostgreSQL 16
-- FK: scored_offers(score_id) — 1:1 (UNIQUE)

CREATE TABLE IF NOT EXISTS negotiation_outcomes (
    negotiation_id          UUID                            PRIMARY KEY DEFAULT uuid_generate_v4(),
    score_id                UUID                            NOT NULL UNIQUE
                                                            REFERENCES scored_offers(score_id) ON DELETE CASCADE,
    strategy_applied        negotiation_strategy_type       NOT NULL,
    initial_price           DECIMAL(15,2)                   NOT NULL CHECK (initial_price > 0),
    counter_offer_price     DECIMAL(15,2)                   CHECK (counter_offer_price > 0),
    final_price             DECIMAL(15,2)                   NOT NULL CHECK (final_price > 0),
    discount_percent        FLOAT                           NOT NULL DEFAULT 0.0
                                                            CHECK (discount_percent >= 0.0 AND discount_percent <= 20.0),
    acceptance_status       acceptance_status_type          NOT NULL,
    negotiated_at           TIMESTAMP                       NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE negotiation_outcomes IS
    'Negotiation Engine result via Beckn /select. Max discount 20% is a hard, non-bypassable constraint.';
COMMENT ON COLUMN negotiation_outcomes.strategy_applied IS
    'aggressive=commodities | accept_margin=within budget | advisory=high-value | escalate=gap too large | skipped=urgency.';
COMMENT ON COLUMN negotiation_outcomes.counter_offer_price IS
    'NULL when strategy=skipped or strategy=advisory (no counter-offer sent).';
