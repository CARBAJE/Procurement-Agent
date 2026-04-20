-- 06_discovery_queries.sql
-- Entity 5: DiscoveryQuery
-- Record of each GET /discover call sent to the Discovery Service via beckn-onix adapter.
-- Store: PostgreSQL 16 (record) + Redis 7 (response cache, TTL 15 min)
-- FK: beckn_intents(beckn_intent_id)

CREATE TABLE IF NOT EXISTS discovery_queries (
    query_id            UUID            PRIMARY KEY DEFAULT uuid_generate_v4(),
    beckn_intent_id     UUID            NOT NULL
                                        REFERENCES beckn_intents(beckn_intent_id) ON DELETE RESTRICT,
    network_id          VARCHAR(100)    NOT NULL,
    cache_hit           BOOLEAN         NOT NULL DEFAULT FALSE,
    results_count       INTEGER         NOT NULL DEFAULT 0 CHECK (results_count >= 0),
    queried_at          TIMESTAMP       NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE discovery_queries IS
    'Record of each GET /discover call. cache_hit=TRUE means response served from Redis.';
COMMENT ON COLUMN discovery_queries.network_id IS
    'Beckn network ID queried, e.g. "ondc-prod-01".';
