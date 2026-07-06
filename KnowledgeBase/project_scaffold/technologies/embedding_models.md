---
tags: [technology, ai, embeddings, ml-model, sentence-transformers, fastembed, local-inference, vector-search, rag]
cssclasses: [procurement-doc, tech-doc]
status: "#implemented"
related: ["[[vector_db_qdrant_pinecone]]", "[[agent_memory_learning]]", "[[memory_retrieval_model]]", "[[llm_providers]]", "[[databases_postgresql_redis]]"]
---

# Embedding Models

> [!architecture] Role in the System
> Embedding models convert procurement text (catalog item descriptions, past transaction summaries, procurement queries) into 384-dimensional dense vectors stored in [[databases_postgresql_redis|PostgreSQL via pgvector]]. These vectors power two features: (1) **Stage 3 BPP catalog semantic cache** — finding previously validated catalog items similar to a new query; (2) **Agent Memory** — retrieving past transactions similar to a new procurement request to inject supplier loyalty context into scoring.

> [!implementation] Implementation Note (updated Phase 3)
> The original spec described `text-embedding-3-large` (OpenAI, 3072 dims) as the primary model and `e5-large-v2` as a self-hosted fallback. The implemented system uses **only local models at 384 dimensions** — no external embedding API calls. This was chosen for data sovereignty, zero API cost, and offline operation.

## Implemented Models

| Model | Library | Use case | Dims | Runtime |
|---|---|---|---|---|
| `sentence-transformers/all-MiniLM-L6-v2` | sentence-transformers | Stage 3 BPP catalog semantic cache (IntentParser ANN search) | 384 | Local CPU/GPU |
| `BAAI/bge-small-en-v1.5` | fastembed (ONNX) | Agent memory write/search (data-normalizer) | 384 | Local CPU (no PyTorch required) |

Both models produce cosine-compatible 384-dim vectors and share the same pgvector HNSW index structure.

## Why No Fine-Tuning

Pre-trained general-purpose embeddings perform well for procurement text. Procurement item descriptions (cable specs, stationery, IT equipment) are well-covered by standard training corpora. The structured metadata filters (category, date range, supplier) applied before vector search compensate for any domain gap without requiring a custom training pipeline.

## Vector Store

Both models write into [[databases_postgresql_redis|PostgreSQL 16 + pgvector]]:

| Table | Model | Index |
|---|---|---|
| `bpp_catalog_semantic_cache` | `all-MiniLM-L6-v2` | HNSW cosine, `vector(384)` |
| `agent_memory_vectors` | `BAAI/bge-small-en-v1.5` | HNSW cosine, `vector(384)` (migration `22_agent_memory_vector_dim.sql`) |

## fastembed vs. sentence-transformers

`fastembed` (ONNX Runtime) is used for agent memory because the data-normalizer container needs to run embeddings without pulling in the full PyTorch dependency chain (~1.5 GB). The ONNX model (~65 MB) is downloaded from HuggingFace on first use and cached in memory.

`sentence-transformers` is used in the IntentParser where PyTorch is already a dependency for the qwen3 inference pipeline.

## Original Design vs. Implementation

| Original spec | Implemented |
|---|---|
| `text-embedding-3-large` (OpenAI, 3072 dims) | Not used — local models only |
| `e5-large-v2` (self-hosted fallback) | Not used — replaced by `all-MiniLM-L6-v2` and `BAAI/bge-small-en-v1.5` |
| Qdrant vector store | pgvector in existing PostgreSQL 16 instance |
| Vector dimension: 3072 | Vector dimension: 384 |

> [!guardrail] No External Embedding Calls
> All embedding operations are fully local — no procurement text (item descriptions, quantities, supplier names, prices) leaves the development environment. This satisfies data sovereignty requirements without needing a data processing agreement with any external API provider.
