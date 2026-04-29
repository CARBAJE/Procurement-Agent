-- 18_bpp_catalog_semantic_cache.sql
-- Stage 3: Hybrid BPP Item Existence Validation — Semantic Cache
--
-- Architecture reference:
--   BPP_Item_Validation/09_bpp_catalog_semantic_cache_Schema.md
--   BPP_Item_Validation/10_HNSW_Index_Strategy.md
--
-- Two write paths populate this table:
--   Path A (CatalogCacheWriter): source='bpp_publish', strategy='item_name_only',
--                                descriptions=NULL
--   Path B (MCPResultAdapter):   source='mcp_feedback', strategy='item_name_and_specs',
--                                descriptions=buyer spec tokens
--
-- Query path: HNSW cosine ANN search with SET hnsw.ef_search = 100
-- Three-zone decision: >= 0.92 VALIDATED | 0.75–0.91 AMBIGUOUS | < 0.75 CACHE MISS

-- pgvector extension already enabled by 00_extensions_and_types.sql
-- Included here for standalone execution safety.
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pgcrypto;   -- gen_random_uuid()

CREATE TABLE IF NOT EXISTS bpp_catalog_semantic_cache (
    id                  UUID            PRIMARY KEY DEFAULT gen_random_uuid(),
    item_name           TEXT            NOT NULL,
    item_embedding      vector(1536)    NOT NULL,
    descriptions        TEXT[],
    bpp_id              TEXT            NOT NULL,
    bpp_uri             TEXT            NOT NULL,
    provider_id         TEXT,
    category_tag        TEXT,
    source              TEXT            NOT NULL
                            CHECK (source IN ('bpp_publish', 'mcp_feedback')),
    embedding_strategy  TEXT            NOT NULL
                            CHECK (embedding_strategy IN ('item_name_only', 'item_name_and_specs')),
    created_at          TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    last_seen_at        TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    hit_count           INTEGER         NOT NULL DEFAULT 0,

    CONSTRAINT uq_bpp_catalog_item_per_bpp UNIQUE (item_name, bpp_id)
);

COMMENT ON TABLE bpp_catalog_semantic_cache IS
    'Stage 3 semantic validation cache. '
    'Populated by CatalogCacheWriter (Path A) and MCPResultAdapter (Path B). '
    'Architecture: BPP_Item_Validation/09_bpp_catalog_semantic_cache_Schema.md';

COMMENT ON COLUMN bpp_catalog_semantic_cache.item_embedding IS
    'vector(1536) from text-embedding-3-small. '
    'Path A: embed(item_name). Path B: embed(item_name + " | " + join(descriptions)).';

COMMENT ON COLUMN bpp_catalog_semantic_cache.embedding_strategy IS
    'item_name_only (Path A, weaker) or item_name_and_specs (Path B, richer).';

COMMENT ON COLUMN bpp_catalog_semantic_cache.source IS
    'bpp_publish = originated from on_discover callback (Path A). '
    'mcp_feedback = originated from a successful MCP probe (Path B).';

-- HNSW index for cosine ANN search
-- Parameters per architecture doc (10_HNSW_Index_Strategy.md):
--   m=16              bi-directional links per node
--   ef_construction=64  dynamic candidate list size during index build
-- At query time, set: SET hnsw.ef_search = 100;
CREATE INDEX IF NOT EXISTS hnsw_bpp_catalog_embedding_cosine
    ON bpp_catalog_semantic_cache
    USING hnsw (item_embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

COMMENT ON INDEX hnsw_bpp_catalog_embedding_cosine IS
    'HNSW cosine-distance index. '
    'Set ef_search per session: SET hnsw.ef_search = 100;';
