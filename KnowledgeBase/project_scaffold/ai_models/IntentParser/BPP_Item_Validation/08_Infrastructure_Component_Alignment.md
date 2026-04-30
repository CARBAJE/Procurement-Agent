---
tags: [bpp-validation, architecture, pgvector, postgresql, embedding, mcp]
cssclasses: [procurement-doc, ai-doc]
status: "#approved"
related: ["[[09_bpp_catalog_semantic_cache_Schema]]", "[[10_HNSW_Index_Strategy]]", "[[11_Embedding_Input_Strategy]]", "[[19_search_bpp_catalog_Tool_Spec]]"]
---

# Infrastructure Component Alignment

## Component Table

| Component | Role | Decision Rationale |
|---|---|---|
| **PostgreSQL 16 + pgvector** | Hosts `bpp_catalog_semantic_cache` table | Already deployed; ACID guarantees for feedback-loop writes; bounded catalog corpus doesn't justify Qdrant overhead |
| **text-embedding-3-small** (1536 dims) | Produces query and stored vectors | Item names are short (< 15 tokens); `large` model is unnecessary; ~20× cost reduction vs. `text-embedding-3-large` |
| **e5-large-v2** | Self-hosted fallback embedding | Data sovereignty deployments where OpenAI API calls are prohibited |
| **MCP Server** (sidecar in `intention-parser`) | Exposes `search_bpp_catalog` tool to the LLM | Embeds validation in the LLM reasoning loop; enables self-correction; consistent with ReAct framework |
| **BecknBAP Client** (:8002) | Target of the MCP probe | Existing service; `CatalogNormalizer` runs internally, returning already-normalized `DiscoverOffering[]` |
| **Qdrant** | **NOT used for this cache** | Reserved for the unbounded agent memory RAG corpus (50K–500K procurement records); wrong scale for catalog validation |

## Critical Note on Qdrant

**Qdrant is NOT used for this cache — reserved for the unbounded agent memory RAG corpus.**

The `bpp_catalog_semantic_cache` is a bounded corpus (hundreds to tens of thousands of items). PostgreSQL 16 + pgvector with HNSW indexing is the correct store at this scale. It also provides ACID guarantees for the feedback loop writes, colocation with procurement transactional data, and zero additional infrastructure overhead (PostgreSQL is already deployed).

Qdrant is reserved exclusively for the 50K–500K procurement records in the agent memory RAG corpus, where its vector-native architecture provides a genuine advantage over pgvector.

---

## Related Notes

- [[09_bpp_catalog_semantic_cache_Schema]] — Full table schema for the pgvector cache
- [[10_HNSW_Index_Strategy]] — HNSW index configuration and rationale
- [[11_Embedding_Input_Strategy]] — What gets embedded and how
- [[19_search_bpp_catalog_Tool_Spec]] — The MCP tool specification
