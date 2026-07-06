# Phase 3 — Agent Memory & Learning: Test & Verification Guide

> Component: [[agent_memory_learning]]
> Branch: `feature/agent-memory-learning`
> Spec: `components/agent_memory_learning.md`

---

## What is implemented

### Deployed architecture

```
Confirmed order (commit)
        ↓
orchestrator: asyncio.create_task(_persist_memory(...))   ← fire-and-forget
        ↓
POST /normalize/memory/write   (data-normalizer :8006)
        ↓
fastembed BAAI/bge-small-en-v1.5 → vector(384)  ONNX, no PyTorch required
        ↓
INSERT INTO agent_memory_vectors  (pgvector HNSW cosine)

─────────────────────────────────────────────────────────

New request (compare)
        ↓
orchestrator: _fetch_memory_context(item_text, limit=3)   ← 5 s timeout
        ↓
POST /normalize/memory/search   (data-normalizer :8006)
        ↓
ANN cosine search (HNSW, sim ≥ 0.75) → top-3 similar past transactions
        ↓
reasoning_steps += { node: "memory_context", role: "observe", ... }
        ↓
Frontend: node visible in the agent reasoning panel
```

### Key files

| File | Role |
|---|---|
| `database/sql/22_agent_memory_vector_dim.sql` | Migration: `vector(384)` + HNSW cosine index |
| `DataNormalizer/repositories/memory_repo.py` | fastembed embedding + pgvector write/search |
| `DataNormalizer/normalizer.py` | `write_memory()` and `search_memory()` methods |
| `services/data-normalizer/src/handler.py` | `POST /normalize/memory/write` and `POST /normalize/memory/search` |
| `services/orchestrator/src/workflow.py` | `_persist_memory()` (write) + `_fetch_memory_context()` (read) |

### Implementation vs. spec

| Aspect | Spec | Implemented |
|---|---|---|
| Vector store | Qdrant (HNSW) + pgvector mirror | pgvector only (sufficient for < 100K records) |
| Embedding model | text-embedding-3-large (3072 dims) | BAAI/bge-small-en-v1.5 (384 dims, ONNX, local) |
| Nightly ETL | PostgreSQL → Qdrant batch sync | Not applicable — pgvector is the sole store |
| Model governance | Weekly pipeline with LangSmith | Schema created; pipeline deferred to Phase 4 |
| Training data | ERP exports, user logs, supplier data | Confirmed Beckn transactions only |

---

## Prerequisites

```bash
# 1. Ensure the full stack is running
docker compose up -d
docker compose ps   # data-normalizer and orchestrator must show Up

# 2. Verify migration 22 is applied
psql -U postgres -d procurement_agent -c "\d agent_memory_vectors"
# Expected: embedding_vector | vector(384)
# Expected index: idx_agent_memory_hnsw | hnsw (embedding_vector vector_cosine_ops)

# 3. Verify the service responds
curl -s http://localhost:8006/health
# → {"status": "ok", "service": "data-normalizer"}
```

---

## Test 1 — Write Path: confirm memory is written after an order

### Step 1 — Check initial row count

```bash
psql -U postgres -d procurement_agent -c \
  "SELECT COUNT(*) FROM agent_memory_vectors;"
# → 0  (or the count of previously confirmed orders)
```

### Step 2 — Complete a full order in the frontend

1. Open the frontend: `http://localhost:3000`
2. Log in with Keycloak credentials
3. Enter a procurement request, e.g.: **"500 reams A4 paper Bangalore 3 days"**
4. Wait for suppliers to appear in the comparison panel
5. Select a supplier and click **Commit / Confirm Order**
6. Wait for the status to advance to `confirmed`

### Step 3 — Verify the memory record was written

```bash
psql -U postgres -d procurement_agent -c \
  "SELECT metadata->>'text_summary', metadata->>'provider_name', indexed_at
   FROM agent_memory_vectors
   ORDER BY indexed_at DESC LIMIT 5;"
```

**Expected result:**

| text_summary | provider_name | indexed_at |
|---|---|---|
| `A4 paper ordered from OfficeZone India at 480.00 INR delivery in 72h` | `OfficeZone India` | `2026-07-03 ...` |

Also in the orchestrator logs:

```bash
docker compose logs orchestrator | grep memory
# → INFO:__main__:[memory] stored transaction for A4 paper
```

---

## Test 2 — Read Path: verify the `memory_context` node in the frontend

> Requires Test 1 to have been completed first (at least 1 order in memory).

### Step 1 — Submit a second request for the same item type

1. Start a **new request** in the frontend for an item similar to the previous order: **"300 reams A4 paper Mumbai"**
2. Wait for the agent to process and display suppliers

### Step 2 — Find the `memory_context` node in the reasoning panel

The **Agent Reasoning** panel should show a new node:

```
📋 memory_context  [observe]
Found 1 similar past order(s):
  OfficeZone India ₹480.0 INR (72h)
```

### Step 3 — Verify via direct API call

```bash
curl -s -X POST http://localhost:8006/normalize/memory/search \
  -H "Content-Type: application/json" \
  -d '{"item_text": "A4 paper reams", "limit": 3}' | python3 -m json.tool
```

**Expected result:**

```json
{
  "results": [
    {
      "item_text": "A4 paper",
      "provider_name": "OfficeZone India",
      "price": 480.0,
      "currency": "INR",
      "delivery_hours": 72,
      "text_summary": "A4 paper ordered from OfficeZone India at 480.00 INR delivery in 72h",
      "similarity": 0.87
    }
  ],
  "count": 1
}
```

If `similarity < 0.75`, the result is filtered and will not appear in the reasoning panel — this is correct behavior.

---

## Test 3 — Isolation and similarity threshold

Verify that memory does **not** contaminate requests for completely unrelated items.

```bash
curl -s -X POST http://localhost:8006/normalize/memory/search \
  -H "Content-Type: application/json" \
  -d '{"item_text": "Dell laptops 16GB RAM", "limit": 3}'
# → {"results": [], "count": 0}
```

---

## Test 4 — Database verification after multiple orders

After 3+ orders of different items:

```bash
psql -U postgres -d procurement_agent -c "
SELECT
  entity_type,
  metadata->>'item_text'     AS item,
  metadata->>'provider_name' AS provider,
  (metadata->>'price')::numeric AS price,
  indexed_at::date            AS date
FROM agent_memory_vectors
ORDER BY indexed_at DESC;"
```

All rows must have `entity_type = 'transaction'`.

---

## Troubleshooting

### `memory_context` node does not appear in the frontend

1. Check orchestrator logs:
   ```bash
   docker compose logs orchestrator | grep -E "memory|fetch"
   ```
2. Verify `agent_memory_vectors` has rows:
   ```bash
   psql -U postgres -d procurement_agent -c "SELECT COUNT(*) FROM agent_memory_vectors;"
   ```
3. Test the search endpoint directly to see the raw similarity score.
4. The similarity threshold is 0.75 — items with text very different from stored records will be filtered out.

### Write fails silently

```bash
docker compose logs data-normalizer | grep -E "memory|error|warn"
```

On first use, the ONNX model (~65 MB) is downloaded from HuggingFace — this can take 10–30 s on the first call. Subsequent calls use the in-memory cache and are instant.

### `vector(384)` column does not exist in the table

Migration 22 was not applied. Run:

```bash
psql -U postgres -d procurement_agent \
  -f database/sql/22_agent_memory_vector_dim.sql
```

---

## Phase 3 Acceptance Checklist

- [ ] `agent_memory_vectors` has `vector(384)` with HNSW cosine index
- [ ] `POST /normalize/memory/write` returns `{"stored": true}` in < 2 s (after initial model download)
- [ ] `POST /normalize/memory/search` returns results with `similarity` scores for similar items
- [ ] After confirming an order in the frontend, `[memory] stored transaction` appears in orchestrator logs
- [ ] On the next request for a similar item, the reasoning panel shows the `memory_context` node
- [ ] Requests for unrelated items do **not** show `memory_context` (0.75 threshold filters correctly)
- [ ] Memory enrichment latency < 5 s (timeout configured in orchestrator)
