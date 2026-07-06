---
tags: [technology, database, vector-db, qdrant, pinecone, pgvector, rag, embeddings, memory]
cssclasses: [procurement-doc, tech-doc]
status: "#implemented"
related: ["[[embedding_models]]", "[[agent_memory_learning]]", "[[databases_postgresql_redis]]", "[[phase3_advanced_intelligence_enterprise_features]]", "[[security_compliance]]", "[[memory_retrieval_model]]"]
---

# Vector Database — Qdrant / Pinecone

> [!architecture] Role in the System
> The vector database powers the **[[agent_memory_learning|Agent Memory & Learning]]** component. It stores dense vector representations of past procurement transactions, enabling the [[agent_framework_langchain_langgraph|LangChain agent]] to retrieve semantically similar historical records when making new recommendations (RAG pattern). This is what allows the agent to say: *"Last quarter, you ordered similar items from Seller X at ₹1.8/unit with 98% on-time delivery."*

## Options

| Option | Preference | Notes |
|---|---|---|
| Qdrant (self-hosted) | **Preferred** | Data sovereignty; no third-party SaaS dependency |
| Pinecone (managed) | Alternative | Faster setup; suitable when data residency is not a constraint |

> [!tech-stack] Why Qdrant is Preferred
> Procurement transaction data contains commercially sensitive pricing, supplier relationships, and spend patterns. [[security_compliance|Data residency requirements]] mandate that this data stays within the enterprise's jurisdiction. Qdrant runs self-hosted within the enterprise cloud boundary ([[cloud_providers|AWS Mumbai / Azure India]]), whereas Pinecone is a managed SaaS service. Qdrant's **HNSW indexing** achieves < 100ms retrieval on corpora up to 500K procurement records — meeting the latency SLA.

## Technical Specs

| Attribute | Detail |
|---|---|
| Indexing | HNSW (Hierarchical Navigable Small World) |
| Expected corpus | 50K–500K procurement records |
| Retrieval latency target | `< 100ms` |
| Embedding model | [[embedding_models\|OpenAI text-embedding-3-large]] (primary) / `e5-large-v2` (open-source fallback) |
| Similarity measure | Cosine similarity |

## Data Stored

- Past procurement transactions (item, quantity, seller, price, delivery performance)
- [[negotiation_engine|Negotiation outcomes]] (counter-offer acceptance rates, final agreed prices)
- Seasonal price patterns
- Supplier reliability trends
- User interaction logs (selections, overrides, feedback) — from [[event_streaming_kafka|Kafka consumer]]

## Retrieval Use Case

When a new request arrives, the [[agent_framework_langchain_langgraph|agent]] queries Qdrant with a semantic embedding of the request + metadata filters (category, date range, supplier). Returns top-k similar past transactions for the [[comparison_scoring_engine]] to incorporate.

> [!milestone] Phase 3 Delivery (Weeks 9–12)
> Acceptance criteria for [[phase3_advanced_intelligence_enterprise_features|Phase 3]]:
> - Vector DB storing past procurement patterns from at least one full transaction cycle.
> - Similarity search validated — agent references past orders in live recommendations.
> - Retrieval latency confirmed `< 100ms` under load.
> Governed by [[model_governance_monitoring|model evaluation pipeline]].

> [!guardrail] Data Sovereignty
> Self-hosted Qdrant is a **hard requirement** when the enterprise's data residency policy prohibits third-party SaaS processing. No vector embeddings of procurement records are sent to Pinecone or any external service unless explicitly permitted by enterprise data processing agreements. The [[security_compliance|security compliance framework]] governs this.

---

## Implementation Decision: pgvector (Phases 1–3)

> [!implementation] Qdrant replaced by pgvector for the pilot deployment
>
> **Decision:** For Phases 1–3 (pilot, corpus < 100K records), **pgvector** running inside the existing PostgreSQL 16 container replaces the standalone Qdrant instance.
>
> **Rationale:**
> 1. Zero additional infrastructure — pgvector is a PostgreSQL extension, no new container or service required.
> 2. The pilot procurement corpus is well below 100K records, where Qdrant's HNSW performance advantage over pgvector becomes significant.
> 3. `asyncpg` connection pool already exists — no new client library or connection management needed.
> 4. Single database means simpler backup, restore, and schema migration story.
>
> **Technical specs as implemented:**
>
> | Table | Dim | Index | Migration |
> |---|---|---|---|
> | `bpp_catalog_semantic_cache` | 384 | HNSW cosine | `18_bpp_catalog_semantic_cache.sql` |
> | `agent_memory_vectors` | 384 | HNSW cosine | `22_agent_memory_vector_dim.sql` |
>
> Both tables use `vector(384)` (not 3072). See [[embedding_models]] for the actual models used.
>
> **When to reconsider Qdrant:** if the corpus grows beyond 100K records, if multi-tenancy or horizontal scaling of vector search is required, or if Phase 4 moves to a managed cloud deployment where a dedicated vector DB is operationally easier to manage than a PostgreSQL extension.
