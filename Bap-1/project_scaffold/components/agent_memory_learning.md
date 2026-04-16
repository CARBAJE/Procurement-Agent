---
tags: [component, ai, memory, vector-db, rag, qdrant, embeddings, learning, procurement-patterns]
cssclasses: [procurement-doc, component-doc]
status: "#processed"
related: ["[[vector_db_qdrant_pinecone]]", "[[embedding_models]]", "[[databases_postgresql_redis]]", "[[event_streaming_kafka]]", "[[phase3_advanced_intelligence_enterprise_features]]", "[[memory_retrieval_model]]", "[[comparison_scoring_engine]]"]
---

# Component: Agent Memory & Learning

> [!architecture] Role in the System
> The Agent Memory layer gives the [[agent_framework_langchain_langgraph|LangChain agent]] access to **historical context** at decision time. When a new procurement request arrives, the agent retrieves semantically similar past transactions from [[vector_db_qdrant_pinecone|Qdrant]] and incorporates them into the [[comparison_scoring_engine|scoring context]] and recommendation text. This is what makes the agent progressively smarter — not just for individual users, but across the entire enterprise procurement function.

## Architecture

| Layer | Technology |
|---|---|
| Storage | [[vector_db_qdrant_pinecone\|Qdrant]] (self-hosted, HNSW indexing) |
| Encoding | [[embedding_models\|text-embedding-3-large]] (primary) / `e5-large-v2` (open-source fallback) |
| Similarity measure | Cosine similarity |
| Metadata filtering | Category, date range, supplier — applied before vector search to narrow corpus |
| Integration | [[databases_postgresql_redis\|PostgreSQL]] → nightly ETL → embedding → Qdrant |

## Data Stored in Vector DB

- Past procurement transactions (item, quantity, seller, price, delivery performance)
- [[negotiation_engine|Negotiation outcomes]] (counter-offer acceptance rates, final agreed prices)
- Seasonal price patterns
- Supplier reliability trends
- User interaction logs (selections, overrides with reasons)

## Memory Sources (Data Pipeline)

| Source | Volume | Freshness | Processing |
|---|---|---|---|
| Enterprise Procurement History (ERP exports) | 50K–500K records | Daily batch sync | ETL → [[databases_postgresql_redis\|PostgreSQL]] → Embed → [[vector_db_qdrant_pinecone\|Qdrant]] |
| User Interaction Logs | 1K–10K events/day | Real-time streaming | [[event_streaming_kafka\|Kafka]] → PostgreSQL (audit) + Qdrant (learning) |
| Supplier Performance Data | Aggregated ONDC + internal | Weekly aggregation | Batch → Supplier scoring model update |

## Example Retrieval-Augmented Recommendation

> *"Last quarter, you ordered similar items from Seller X at ₹1.8/unit with 98% on-time delivery. They are currently active on the ONDC network."*

> [!milestone] Phase 3 Acceptance (Weeks 9–12)
> From [[phase3_advanced_intelligence_enterprise_features|Phase 3 Agent Memory milestone]]:
> - Agent references past orders in live recommendations.
> - Similarity search returns relevant results (validated against ground truth).
> - Retrieval latency confirmed `< 100ms` under representative load.
> Technical spec: [[memory_retrieval_model]].

> [!insight] Cross-Enterprise Learning Effect
> Memory improves recommendations not just per user, but across the **entire enterprise** — supplier reliability data, seasonal pricing trends, and negotiation outcomes accumulate into a shared procurement intelligence layer. The more the system is used, the better its recommendations become. This creates a compounding competitive advantage that grows over time. See [[business_impact_metrics]] for quantified targets.
