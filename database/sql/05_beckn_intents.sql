-- 05_beckn_intents.sql
-- Entity 4: BecknIntent
-- Structured canonical form; anti-corruption layer between NL and Beckn protocol.
-- All fields normalized: GPS coordinates, hours, ISO 4217 currency.
-- Store: PostgreSQL 16
-- FK: parsed_intents(intent_id) — 1:1 relationship (UNIQUE)

CREATE TABLE IF NOT EXISTS beckn_intents (
    beckn_intent_id             UUID            PRIMARY KEY DEFAULT uuid_generate_v4(),
    intent_id                   UUID            NOT NULL UNIQUE
                                                REFERENCES parsed_intents(intent_id) ON DELETE CASCADE,
    item                        VARCHAR(255)    NOT NULL,
    descriptions                JSONB           NOT NULL DEFAULT '[]',
    quantity                    INTEGER         NOT NULL CHECK (quantity > 0),
    unit                        VARCHAR(50)     NOT NULL,
    location_coordinates        VARCHAR(50)     NOT NULL,
    delivery_timeline_hours     INTEGER         NOT NULL CHECK (delivery_timeline_hours > 0),
    budget_min                  DECIMAL(15,2)   CHECK (budget_min >= 0),
    budget_max                  DECIMAL(15,2)   CHECK (budget_max >= 0),
    currency                    CHAR(3)         NOT NULL DEFAULT 'INR',
    compliance_requirements     JSONB           NOT NULL DEFAULT '[]',
    CONSTRAINT chk_budget_range CHECK (
        budget_min IS NULL OR budget_max IS NULL OR budget_min <= budget_max
    )
);

COMMENT ON TABLE beckn_intents IS
    'Boundary between NL and Beckn protocol. Units: GPS coords, hours, ISO 4217 currency.';
COMMENT ON COLUMN beckn_intents.location_coordinates IS
    'GPS coordinates in "lat,lon" format, e.g. "12.9716,77.5946".';
COMMENT ON COLUMN beckn_intents.descriptions IS
    'List of atomic technical specifications, e.g. ["80gsm", "white", "ISO 216"].';
COMMENT ON COLUMN beckn_intents.compliance_requirements IS
    'Required certifications, e.g. ["ISO 27001", "BIS"].';
