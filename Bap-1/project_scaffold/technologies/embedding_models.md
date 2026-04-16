---
tags: [technology, ai, embeddings, ml-model, openai, e5, vector-search, rag]
cssclasses: [procurement-doc, tech-doc]
status: "#processed"
related: ["[[vector_db_qdrant_pinecone]]", "[[agent_memory_learning]]", "[[memory_retrieval_model]]", "[[llm_providers]]", "[[security_compliance]]"]
---

# Embedding Models

> [!architecture] Role in the System
> Embedding models convert procurement records (past transactions, supplier data, negotiation outcomes) into dense vector representations stored in [[vector_db_qdrant_pinecone|Qdrant]]. These vectors enable the [[agent_memory_learning|Agent Memory]] component to perform **semantic similarity search** — finding past procurement records that are contextually similar to a new request, even when the exact words differ. This is the RAG (Retrieval-Augmented Generation) layer of the agent.

## Models

| Model | Type | Use |
|---|---|---|
| `text-embedding-3-large` | Managed (OpenAI API) | Primary embedding model for procurement records |
| `e5-large-v2` | Open-source (self-hosted) | Fallback for data sovereignty use cases |

> [!tech-stack] Why No Fine-Tuning
> Pre-trained general-purpose embeddings perform well for procurement text because procurement language (item descriptions, specifications, supplier names, categories) is covered by standard training corpora. Custom fine-tuning would require labeled procurement datasets, significant training compute, and ongoing maintenance — none of which is justified when pre-trained models achieve sufficient retrieval quality. **Custom metadata filtering** (category, date range, supplier) applied before vector search eliminates the need for domain-specific fine-tuning.

## Technical Details

| Attribute | Detail |
|---|---|
| Similarity measure | Cosine similarity |
| No custom training needed | Pre-trained embeddings generalize well for procurement text |
| Metadata filtering | Category, date range, supplier — narrows retrieval corpus before semantic search |
| Vector DB | [[vector_db_qdrant_pinecone\|Qdrant]] with HNSW indexing |
| Corpus size | 50K–500K procurement records |
| Retrieval latency target | `< 100ms` |

## Data Encoded as Vectors

- Past procurement transactions (item descriptors, quantities, prices, delivery outcomes)
- [[negotiation_engine|Negotiation outcomes]] (strategy used, counter-offer result, final price)
- Supplier reliability profiles (from ONDC + internal data)
- User interaction events (selections, override reasons)

> [!guardrail] Data Sovereignty for Embeddings
> When `text-embedding-3-large` (OpenAI API) is used, procurement data is transmitted to OpenAI's API endpoint. This requires an enterprise API agreement with data processing addendum per [[security_compliance|data residency requirements]].
> For deployments where **no external API calls are permitted**, `e5-large-v2` is deployed self-hosted within the enterprise cloud boundary — ensuring zero procurement data leaves the enterprise's jurisdiction. This fallback is built into the [[memory_retrieval_model|Memory & Retrieval Model]] configuration.
