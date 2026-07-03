-- 22_agent_memory_vector_dim.sql
-- Adapts agent_memory_vectors to the embedding model actually deployed:
-- all-MiniLM-L6-v2 (sentence-transformers, local, no API key required)
-- produces 384-dimensional vectors, not the 3072 specified for text-embedding-3-large.
-- The table is empty at this point (nothing has ever written to it), so
-- dropping and re-adding the column is safe and idempotent via IF NOT EXISTS.
--
-- Also registers all-MiniLM-L6-v2 in the embedding_model_type enum (additive only).
-- Depends on: 15_agent_memory_vectors.sql, 00_extensions_and_types.sql

-- 1. Add the open-source model to the enum (ADD VALUE is idempotent on pg 14+)
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_enum
        WHERE enumtypid = 'embedding_model_type'::regtype
          AND enumlabel = 'all-MiniLM-L6-v2'
    ) THEN
        ALTER TYPE embedding_model_type ADD VALUE 'all-MiniLM-L6-v2';
    END IF;
END;
$$;

-- 2. Swap the vector column from 3072 → 384 dims.
--    pgvector does not allow ALTER COLUMN to change vector dimensions,
--    so we drop and re-add. Safe: table is empty at migration time.
ALTER TABLE agent_memory_vectors DROP COLUMN IF EXISTS embedding_vector;
ALTER TABLE agent_memory_vectors
    ADD COLUMN embedding_vector vector(384) NOT NULL;

-- 3. HNSW index for sub-linear cosine ANN search (< 100 ms target per spec).
CREATE INDEX IF NOT EXISTS idx_agent_memory_hnsw
    ON agent_memory_vectors
    USING hnsw (embedding_vector vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

-- 4. Covering index on entity_type for pre-filter (future: seasonal, supplier).
CREATE INDEX IF NOT EXISTS idx_agent_memory_entity
    ON agent_memory_vectors (entity_type);
