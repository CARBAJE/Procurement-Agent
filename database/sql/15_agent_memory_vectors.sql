-- 15_agent_memory_vectors.sql
-- Entity 15: AgentMemoryVector
-- PRIMARY store: Qdrant (self-hosted, data sovereignty), HNSW index, target latency < 100ms.
-- This table is a PostgreSQL mirror/metadata index for referential integrity.
-- The embedding_vector uses pgvector extension (vector(3072) = text-embedding-3-large).
-- Store: PostgreSQL 16 (mirror) + Qdrant (primary)
-- FK: procurement_requests(request_id) — NULLABLE (external data may have no source request)

CREATE TABLE IF NOT EXISTS agent_memory_vectors (
    vector_id           UUID                    PRIMARY KEY DEFAULT uuid_generate_v4(),
    source_request_id   UUID
                                                REFERENCES procurement_requests(request_id) ON DELETE SET NULL,
    entity_type         memory_entity_type      NOT NULL,
    embedding_vector    vector(3072)            NOT NULL,
    metadata            JSONB                   NOT NULL DEFAULT '{}',
    embedding_model     embedding_model_type    NOT NULL DEFAULT 'text-embedding-3-large',
    indexed_at          TIMESTAMP               NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE agent_memory_vectors IS
    'PostgreSQL pgvector mirror of Qdrant store. Primary store: Qdrant (HNSW, < 100ms latency target).';
COMMENT ON COLUMN agent_memory_vectors.embedding_vector IS
    'High-dimensional vector(3072) for text-embedding-3-large; vector(1024) for e5-large-v2.';
COMMENT ON COLUMN agent_memory_vectors.metadata IS
    'Typed payload for retrieval: transaction|negotiation|seasonal|supplier|override schemas.';
COMMENT ON COLUMN agent_memory_vectors.source_request_id IS
    'NULL for externally sourced embeddings (seasonal trends, supplier catalogs).';
