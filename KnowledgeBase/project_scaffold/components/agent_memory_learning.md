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

---

## Implementación Real — Scoring con VectorDB

> [!implementation] Estado actual (Phase 3 — feature/agent-memory-learning)
> El flujo completo está implementado en `services/orchestrator/src/workflow.py` y `DataNormalizer/repositories/memory_repo.py`.

### Stack real vs. diseño original

| Aspecto | Diseño (arriba) | Implementación actual |
|---|---|---|
| Vector DB | Qdrant (self-hosted) | **PostgreSQL 16 + pgvector** (`agent_memory_vectors`) |
| Modelo de embeddings | `text-embedding-3-large` / `e5-large-v2` | **`BAAI/bge-small-en-v1.5`** (384 dims, ONNX via fastembed) |
| Similaridad | Cosine | Cosine (`<=>` operator pgvector) |
| Threshold mínimo | — | `similarity >= 0.75` |
| Integración | ETL nightly | Fire-and-forget tras cada PO confirmada |

> La decisión de usar pgvector en lugar de Qdrant está motivada por simplicidad operacional — el cluster PostgreSQL ya existía para el audit trail, evitando un contenedor adicional. Puede migrarse a Qdrant sin cambiar la interfaz pública (`/normalize/memory/write` y `/normalize/memory/search`).

---

### Write Path — Guardar transacción confirmada

```
POST /commit (orchestrator)
  └─ _persist_memory(item_text, provider_name, price, currency, delivery_hours, request_id)
       └─ fire-and-forget POST /normalize/memory/write (DataNormalizer)
            └─ write_transaction_memory()   [memory_repo.py]
                 ├─ text = "{item} ordered from {provider} at {price} {currency} delivery in {hours}h"
                 ├─ vector = BAAI/bge-small-en-v1.5.embed(text)   # 384 floats
                 └─ INSERT INTO agent_memory_vectors (embedding_vector, metadata, ...)
```

El texto concatenado maximiza la semántica almacenada: ítem + proveedor + precio + tiempo de entrega en una sola frase para que la similaridad coseno capture todos los ejes relevantes.

---

### Read Path — ANN Search en `/compare`

```
POST /compare (orchestrator)
  └─ _fetch_memory_context(raw_query or item, limit=10)
       └─ POST /normalize/memory/search (DataNormalizer)
            └─ search_similar_transactions()   [memory_repo.py]
                 ├─ vector = embed(item_text)
                 ├─ SELECT metadata, indexed_at,
                 │         1 - (embedding_vector <=> $1::vector) AS similarity
                 │  FROM   agent_memory_vectors
                 │  WHERE  entity_type = 'transaction'
                 │  ORDER  BY embedding_vector <=> $1::vector
                 │  LIMIT  limit * 3   -- over-fetch, luego filtrar
                 └─ filtra similarity >= 0.75, devuelve top-k con campo "similarity"
```

> **Nota de diseño:** Se usa `raw_query` (texto NL completo, p.ej. `"500 sheets A4 recycled paper Bangalore"`) en lugar del nombre de ítem extraído. Produce embeddings más ricos porque conserva contexto de cantidad, ubicación y especificaciones, lo que mejora la similaridad coseno contra los vectores almacenados.

---

### Scoring Adjustment — `_apply_memory_adjustments()`

Esta función post-procesa el `ranking[]` devuelto por el motor de scoring (ML RankNet o fallback precio) aplicando un bonus de lealtad basado en historial.

**Fórmula del delta por proveedor:**

```
memory_delta(provider) = Σ [ 0.03 × exp( -days_old × ln(2) / 90 ) ]
                         por cada PO pasada (máx. 5)

adjusted_score = composite_score + memory_delta
```

**Garantías anti-sesgo:**

| Garantía | Valor | Propósito |
|---|---|---|
| Proveedores sin historial | `delta = 0` | Nunca penalizar proveedores nuevos |
| Tope máximo | `±0.10` | El historial no puede superar al score ML |
| Time decay (half-life) | 90 días | Órdenes antiguas pesan menos |
| Volume cap | 5 órdenes por proveedor | Evitar monopolio por volumen |

**Resultado en `reasoning_steps`:**

- `memory_context` (rol `observe`) — siempre presente cuando hay hits; muestra los top-3 órdenes pasadas con precio, proveedor y horas de entrega.
- `memory_adjustment` (rol `reason`) — aparece **solo si el proveedor recomendado cambia** tras el ajuste; documenta el proveedor original (ML), el nuevo recomendado (memoria), y el detalle de `ml_score`, `memory_delta` y `adjusted_score` por ítem.

---

### Flujo completo integrado

```
POST /compare
 │
 ├── Step 2: Beckn discover  ──────────────────────── offerings[]
 ├── Step 3: comparative-scoring ─────────────────── ranking[] (ML RankNet o precio)
 │
 ├── _fetch_memory_context()          ← pgvector ANN cosine similarity
 │       returns: [{ provider_name, price, delivery_hours, similarity, indexed_at }]
 │
 ├── _apply_memory_adjustments()
 │       adjusted_score = composite_score + Σ(0.03 × decay)
 │       re-ordena ranking por adjusted_score
 │
 └── reasoning_steps:
       ├─ "memory_context"   (observe) — top-3 órdenes similares pasadas
       └─ "memory_adjustment" (reason) — solo si cambia el #1 recomendado
```

---

### Archivos clave

| Archivo | Responsabilidad |
|---|---|
| `services/orchestrator/src/workflow.py` | `_fetch_memory_context()`, `_persist_memory()`, `_apply_memory_adjustments()` — orquestación del flujo |
| `DataNormalizer/repositories/memory_repo.py` | `write_transaction_memory()`, `search_similar_transactions()` — embed + pgvector |
| `database/sql/` | Tabla `agent_memory_vectors` con columna `embedding_vector vector(384)` |
