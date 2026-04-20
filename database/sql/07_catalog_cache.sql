-- 07_catalog_cache.sql
-- Entity 6: CatalogCache
-- PRIMARY store: Redis 7 (TTL 15 min, key: {item_normalized}:{lat}:{lon}).
-- This table is a PostgreSQL mirror for audit traceability and referential integrity.
-- TTL enforcement is handled by Redis; this table retains records for SOX audit.
-- FK: discovery_queries(query_id)

CREATE TABLE IF NOT EXISTS catalog_cache (
    cache_key           VARCHAR(500)    PRIMARY KEY,
    query_id            UUID            NOT NULL
                                        REFERENCES discovery_queries(query_id) ON DELETE CASCADE,
    cached_offerings    JSONB           NOT NULL DEFAULT '[]',
    created_at          TIMESTAMP       NOT NULL DEFAULT NOW(),
    expires_at          TIMESTAMP       NOT NULL
                                        DEFAULT (NOW() + INTERVAL '15 minutes')
);

COMMENT ON TABLE catalog_cache IS
    'PostgreSQL audit mirror of Redis catalog cache (TTL 15 min). Primary store: Redis 7.';
COMMENT ON COLUMN catalog_cache.cache_key IS
    'Composite key format: {item_normalized}:{lat}:{lon}.';
COMMENT ON COLUMN catalog_cache.expires_at IS
    'Mirrors Redis TTL (created_at + 15 min). Expiry enforced by Redis; this column is informational.';
