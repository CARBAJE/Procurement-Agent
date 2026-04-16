---
tags: [technology, database, vector-db, qdrant, pinecone, rag, embeddings, memory]
cssclasses: [procurement-doc, tech-doc]
status: "#processed"
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
