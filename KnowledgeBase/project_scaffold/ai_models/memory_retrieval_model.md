---
tags: [ai-model, memory, rag, vector-db, qdrant, embeddings, cosine-similarity, procurement-patterns, hnsw]
cssclasses: [procurement-doc, ai-doc]
status: "#processed"
related: ["[[agent_memory_learning]]", "[[embedding_models]]", "[[vector_db_qdrant_pinecone]]", "[[comparison_scoring_engine]]", "[[model_governance_monitoring]]", "[[phase3_advanced_intelligence_enterprise_features]]"]
---

# AI Model: Memory & Retrieval

> [!architecture] Role in the AI Stack
> The Memory & Retrieval Model gives the [[agent_framework_langchain_langgraph|LangChain agent]] **persistent institutional knowledge**. When a new procurement request arrives, this model retrieves the most semantically similar past transactions from [[vector_db_qdrant_pinecone|Qdrant]] and injects them as context into the [[comparison_scoring_engine|scoring]] and recommendation generation steps (RAG pattern). This is what enables the agent to say: *"Last quarter you ordered similar items from Seller X at ₹1.8/unit with 98% on-time delivery."*

## Architecture

| Layer | Technology |
|---|---|
| Embedding model (primary) | [[embedding_models\|OpenAI text-embedding-3-large]] |
| Embedding model (fallback / open-source) | [[embedding_models\|e5-large-v2]] |
| Vector database | [[vector_db_qdrant_pinecone\|Qdrant]] (self-hosted, HNSW indexing) |
| Similarity measure | Cosine similarity |
| Metadata filtering | Category, date range, supplier — applied before vector search |

## Technical Specs

| Attribute | Value |
|---|---|
| Expected corpus | 50K–500K procurement records |
| Retrieval latency target | `< 100ms` |
| Training approach | None — pre-trained embeddings generalize well for procurement text |

## What Gets Stored

- Past procurement transactions (item, quantity, seller, price, delivery performance)
- [[negotiation_engine|Negotiation outcomes]] (acceptance rates, final prices)
- Seasonal price patterns
- Supplier reliability trends (ratings, delivery fulfillment rates over time)
- User overrides and feedback (from [[audit_trail_system|Kafka consumer]])

## Retrieval Flow

1. New procurement request received.
2. Request text embedded using `text-embedding-3-large`.
3. Metadata filter applied (category, date range).
4. HNSW cosine similarity search in [[vector_db_qdrant_pinecone|Qdrant]] → top-k past transactions returned.
5. Retrieved context injected into [[comparison_scoring_engine|scoring prompt]] and recommendation text.

> [!milestone] Phase 3 Acceptance
> From [[phase3_advanced_intelligence_enterprise_features|Phase 3 Agent Memory milestone]]:
> - Vector DB stores past procurement patterns from at least one full transaction cycle.
> - Similarity search returns relevant results validated against ground truth.
> - Retrieval latency `< 100ms` confirmed under representative load.

> [!insight] Cross-Enterprise Learning Flywheel
> Unlike traditional procurement software where value is static, this model creates a **learning flywheel**: more usage → richer memory → better recommendations → more usage. After 6 months of enterprise operation, the agent's recommendations should be measurably better than on day 1. After 12 months, the memory corpus becomes a significant competitive moat — it cannot be replicated without equivalent procurement history. See [[business_impact_metrics]].
