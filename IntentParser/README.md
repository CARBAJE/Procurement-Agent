# IntentParser — Beckn Procurement Intent Microservice

Parses natural-language procurement requests into validated, Beckn-protocol-ready structured intents through a three-stage async pipeline: LLM classification, structured extraction, and semantic BPP catalog validation.

---

## Architecture — Three-Stage Pipeline

```
Buyer Query (NL text)
        │
        ▼
┌───────────────────────────────────────┐
│  Stage 1 — Intent Classification      │  Ollama qwen3:8b  │ mode=JSON
│  "50 SS flanged ball valves PN16..."   │
│  → ParsedIntent { intent, confidence} │
│  Gate: non-procurement → early return  │
└───────────────────────┬───────────────┘
                        │ procurement intent only
                        ▼
┌───────────────────────────────────────┐
│  Stage 2 — BecknIntent Extraction     │  Ollama qwen3:8b / qwen3:1.7b (routed)
│  → BecknIntent { item, descriptions,  │
│    quantity, location, budget, TTL }  │
└───────────────────────┬───────────────┘
                        │
                        ▼
┌───────────────────────────────────────┐
│  Stage 3 — Hybrid BPP Validation      │
│                                        │
│  1. all-MiniLM-L6-v2 embedding (384d)  │
│  2. HNSW ANN query on pgvector cache   │  PostgreSQL 16 + pgvector
│                                        │
│  ┌──────────────────────────────────┐  │
│  │ similarity ≥ 0.85  → VALIDATED   │  │  P1 path (cache hit)
│  │ 0.45 ≤ sim < 0.85 → AMBIGUOUS   │  │
│  │ similarity < 0.45  → CACHE_MISS  │  │
│  └──────────────┬───────────────────┘  │
│                 │ CACHE_MISS            │
│                 ▼                       │
│  3. MCP sidecar probe (SSE :3000)       │  P2 path (MCP fallback)
│     search_bpp_catalog → ONIX → BPPs   │  probe_ttl = 3 s
│                 │                       │
│  ┌──────────────▼───────────────────┐  │
│  │ found=True  → MCP_VALIDATED      │  │  + Path B cache write (async)
│  │ found=False → not_found=True     │  │  P3 path → recovery flow
│  └──────────────────────────────────┘  │
└───────────────────────────────────────┘
                        │ not_found
                        ▼
┌───────────────────────────────────────┐
│  Recovery Flow                         │
│  1. broaden_procurement_query()        │  Regex strip + Claude fallback
│  2. Retry Stage 3 with broader intent  │
│  3. log_unmet_demand()                 │
│  4. notify_buyer_no_stock()            │
│  5. trigger_open_rfq_flow()            │
└───────────────────────────────────────┘
```

### Validation Zones

| Zone | Condition | P-path |
|---|---|---|
| `VALIDATED` | ANN cosine similarity ≥ 0.85 | P1 — cache hit |
| `AMBIGUOUS` | 0.45 ≤ similarity < 0.85 | P1 — low confidence |
| `CACHE_MISS` + `mcp_validated=True` | ANN miss, MCP probe finds item | P2 — MCP fallback |
| `CACHE_MISS` + `not_found=True` | ANN miss, MCP probe empty | P3 — recovery |

---

## Module Directory

```
IntentParser/
├── config.py         All environment-driven constants (thresholds, models, DB params)
├── models.py         Pydantic / dataclass DTOs: ParsedIntent, ValidationResult, ParseResponse
├── db.py             asyncpg connection pool — init, acquire, close; ef_search=100 via init callback
├── embeddings.py     all-MiniLM-L6-v2 singleton; async embed() runs in ThreadPoolExecutor
├── llm_clients.py    instructor-patched AsyncOpenAI clients (mode=JSON and mode=TOOLS)
├── mcp_client.py     Lightweight MCP SSE transport client for the search_bpp_catalog tool
├── validation.py     Stage 3: ANN cache query, three-zone threshold, MCPResultAdapter (Path B)
├── recovery.py       broaden_procurement_query, log/notify/RFQ stubs, Claude broadening fallback
├── orchestrator.py   Full async pipeline: classify → extract → validate → recover
├── core.py           Sync wrapper (parse_request / parse_batch) for backward compatibility
├── schemas.py        ParseResult re-export — backward-compatible public schema
├── api.py            FastAPI app: /parse (sync), /parse/batch (sync), /parse/full (async)
└── tests/
    └── test_milestone.py   Full test suite (Section A: integration, B+C: unit / mocked)
```

> **Shared models** — `BecknIntent`, `BudgetConstraints`, and `DiscoverOffering` are defined in
> `../shared/models.py` (single source of truth for all microservices) and re-exported from
> `IntentParser.models`.

---

## Prerequisites

### 1. Ollama (LLM inference)

```bash
# Install from https://ollama.com, then pull models:
ollama pull qwen3:8b
ollama pull qwen3:1.7b   # optional — used for simple queries
```

### 2. PostgreSQL 16 + pgvector (semantic cache)

```bash
# Ubuntu / Debian
sudo apt install postgresql-16 postgresql-16-pgvector

# macOS (Homebrew)
brew install postgresql@16
brew install pgvector

# Create the database and enable the extension
createdb procurement_agent
psql -d procurement_agent -c "CREATE EXTENSION IF NOT EXISTS vector;"

# Apply the schema migration
psql -d procurement_agent -f database/sql/18_bpp_catalog_semantic_cache.sql
```

### 3. MCP Sidecar (optional — required for Stage 3 P2 path)

The MCP sidecar exposes the `search_bpp_catalog` tool over SSE transport and routes to the
BAP Client (`beckn-bap-client`, Lambda 2). Run it as a co-located container or process
before starting IntentParser. See the `services/mcp-sidecar/` service for the server
implementation.

---

## Setup

```bash
# From the project root
pip install -r IntentParser/requirements.txt

# Or inside conda:
conda activate infosys_project
pip install -r IntentParser/requirements.txt
```

---

## Configuration

All settings are read from environment variables at startup. Sensitive credentials (DB
password, Anthropic API key) must **never** appear in source files or Docker images — load
them from a secrets manager or `.env` file that is excluded from version control.

| Variable | Default | Description |
|---|---|---|
| `OLLAMA_URL` | `http://localhost:11434/v1` | Ollama OpenAI-compatible base URL |
| `COMPLEX_MODEL` | `qwen3:8b` | Model for complex / multi-spec queries |
| `SIMPLE_MODEL` | `qwen3:1.7b` | Model for short, single-field queries |
| `EMBEDDING_MODEL` | `all-MiniLM-L6-v2` | sentence-transformers model name |
| `VALIDATED_THRESHOLD` | `0.85` | Minimum cosine similarity for VALIDATED |
| `AMBIGUOUS_THRESHOLD` | `0.45` | Minimum cosine similarity for AMBIGUOUS |
| `MCP_SSE_URL` | `http://localhost:3000/sse` | MCP sidecar SSE endpoint |
| `MCP_PROBE_TIMEOUT` | `8` | Seconds to wait for MCP probe response |
| `DB_HOST` | `localhost` | PostgreSQL host |
| `DB_PORT` | `5432` | PostgreSQL port |
| `DB_NAME` | `procurement_agent` | Database name |
| `DB_USER` | `carbaje` | Database user |
| `DB_PASSWORD` | *(empty)* | Database password — load from secrets manager |
| `DB_MIN_POOL` | `5` | asyncpg pool minimum size |
| `DB_MAX_POOL` | `20` | asyncpg pool maximum size |
| `ANTHROPIC_API_KEY` | *(empty)* | Enables Claude broadening fallback when set |
| `CLAUDE_MODEL` | `claude-sonnet-4-6` | Claude model for query broadening |

---

## Running the Service

```bash
uvicorn IntentParser.api:app --reload --port 8001
```

The `--reload` flag triggers a pool re-initialization on code changes. In production, omit
`--reload` and manage the pool lifecycle via the FastAPI `lifespan` context (already wired
in `api.py`).

---

## API Endpoints

| Method | Path | Description | Infrastructure |
|---|---|---|---|
| `POST` | `/parse` | Stage 1+2 only (sync, backward compat) | Ollama |
| `POST` | `/parse/batch` | Stage 1+2 batch (sync, threaded) | Ollama |
| `POST` | `/parse/full` | Stage 1+2+3 + recovery (async, production) | Ollama + PostgreSQL + MCP |

### `POST /parse/full` — production endpoint

**Request**

```bash
curl -X POST http://localhost:8001/parse/full \
  -H "Content-Type: application/json" \
  -d '{
    "query": "50 SS flanged ball valves PN16 2 inch SS316 for Bangalore, deliver in 1 week, max 5000 INR each"
  }'
```

**Response — cache hit (P1)**

```json
{
  "intent": "RequestQuote",
  "confidence": 0.97,
  "beckn_intent": {
    "item": "Stainless Steel Flanged Ball Valve",
    "descriptions": ["PN16", "2 inch", "SS316"],
    "quantity": 50,
    "location_coordinates": "12.9716,77.5946",
    "delivery_timeline": 168,
    "budget_constraints": { "max": 5000.0, "min": 0.0 }
  },
  "validation": {
    "status": "VALIDATED",
    "matched": "Stainless Steel Flanged Ball Valve 2 inch",
    "bpp_id": "bpp_industrial_001",
    "similarity": 0.91
  },
  "recovery_log": [],
  "routed_to": "qwen3:8b"
}
```

**Response — MCP fallback (P2)**

```json
{
  "validation": {
    "status": "MCP_VALIDATED",
    "matched": "SS Flanged Ball Valve PN16",
    "bpp_id": "bpp_industrial_007",
    "bpp_uri": "http://bpp-industrial.example.com"
  }
}
```

**Response — not found + recovery (P3)**

```json
{
  "validation": { "status": "CACHE_MISS", "not_found": true },
  "recovery_log": [
    "Broadened query to: Stainless Steel Ball Valve",
    "No BPP catalog match. Logging unmet demand and triggering RFQ."
  ]
}
```

### `POST /parse` — backward-compatible endpoint (Stage 1+2 only)

```bash
curl -X POST http://localhost:8001/parse \
  -H "Content-Type: application/json" \
  -d '{"query": "200 A4 paper 80gsm Bangalore 5 days under 2 INR per sheet"}'
```

---

## Python Usage

### Async (production)

```python
import asyncio
from IntentParser.orchestrator import parse_procurement_request

async def main():
    result = await parse_procurement_request(
        "50 SS flanged ball valves PN16 2 inch for Bangalore, 1 week, max 5000 INR each"
    )
    print(result.intent)              # "RequestQuote"
    print(result.beckn_intent.item)   # "Stainless Steel Flanged Ball Valve"
    print(result.validation)          # {"status": "VALIDATED", "similarity": 0.91, ...}
    print(result.recovery_log)        # [] (empty on success)

asyncio.run(main())
```

### Synchronous (Stage 1+2 only — for legacy callers and tests)

```python
from IntentParser import parse_request

result = parse_request(
    "200 meters UTP Cat6 cable Mumbai 3 days max 15 INR per meter"
)
print(result.beckn_intent.item)            # "UTP Cat6 Cable"
print(result.beckn_intent.delivery_timeline)  # 72 (hours)
print(result.beckn_intent.budget_constraints.max)  # 15.0
```

---

## Testing

### Quick reference

| Command | What runs | Infrastructure |
|---|---|---|
| `pytest IntentParser/ -m "not integration" -v` | 15 unit tests (all mocked) | None |
| `pytest IntentParser/ -v` | All 33 tests | Ollama with qwen3:8b |
| `pytest IntentParser/ -m integration -v -s` | 18 legacy milestone tests | Ollama with qwen3:8b |
| `pytest IntentParser/tests/test_async_pipeline.py -v` | 4 pipeline tests (mock mode) | None |
| `INTENT_PARSER_TEST_MODE=live pytest IntentParser/tests/test_async_pipeline.py -v -s` | 4 pipeline tests (live mode) | PostgreSQL + Ollama + MCP sidecar |

---

### `test_async_pipeline.py` — dual-mode HTTP integration tests

This suite tests the full HTTP stack (`POST /parse/full`) in two configurable modes
controlled by the `INTENT_PARSER_TEST_MODE` environment variable.

#### Mock mode (default — no infrastructure required)

All backend I/O is stubbed: LLM calls via `AsyncMock`, cache queries return
hardcoded `CacheMatch` objects, and the MCP client is a `MagicMock`.  The FastAPI
app and aiohttp routing layers run for real.  Completes in under 1 second.

```bash
pytest IntentParser/tests/test_async_pipeline.py -v
```

#### Live mode

All layers run end-to-end against real services.  `_live_seed` seeds two test
items into `bpp_catalog_semantic_cache` before each relevant test and deletes them
(plus any Path B writes) after, using `bpp_id = 'bpp_test_async_pipeline'` as the
tombstone key.  A 2-second sleep before the DELETE allows async Path B writes to
complete.

```bash
INTENT_PARSER_TEST_MODE=live pytest IntentParser/tests/test_async_pipeline.py -v -s
```

**Live prerequisites:**

| Service | Default address | Purpose |
|---|---|---|
| PostgreSQL 16 + pgvector | `localhost:5432` | Semantic cache ANN queries |
| Ollama | `localhost:11434` | Stage 1+2 LLM calls |
| MCP sidecar | `localhost:3000` | Stage 3 MCP probe (tests 3 + 4) |

#### Test cases

| # | Name | Mock score | Live behaviour | Expected status |
|---|---|---|---|---|
| 1 | `test_1_cache_hit_returns_validated` | 0.95 | seeded item, high-sim match | `VALIDATED` |
| 2 | `test_2_ambiguous_zone_includes_suggestion` | 0.60 | seeded item, partial match | `AMBIGUOUS` |
| 3 | `test_3_mcp_success_returns_mcp_validated` | 0.10 + MCP found | cache miss → real MCP probe | `MCP_VALIDATED` |
| 4 | `test_4_dead_end_triggers_recovery_and_not_found` | 0.00 + MCP empty | niche query, no DB or MCP match | `CACHE_MISS` + `not_found` |

#### Path B write handling

Test 3 triggers an async Path B cache write via `asyncio.create_task()`.

- **Mock mode:** `MCPResultAdapter.write_path_b_row` is patched to `AsyncMock`; an
  `await asyncio.sleep(0)` after the POST flushes the task coroutine before assertions.
- **Live mode:** `await asyncio.sleep(3)` after the POST allows the real write to land;
  the `_live_seed` teardown `await asyncio.sleep(2)` adds further buffer before cleanup.

---

### `test_milestone.py` — unit and integration tests

**Section A — Legacy milestone (18 tests, `@pytest.mark.integration`)**  
Calls the sync `parse_request()` wrapper end-to-end through Ollama. Validates 16
diverse procurement queries produce a valid `BecknIntent` and 2 non-procurement
queries return no `BecknIntent`. Requires Ollama; deselect with `-m "not integration"`.

**Section B — Orchestrator unit tests (6 tests)**  
Tests routing logic inside `orchestrator.parse_procurement_request` with all LLM,
DB, and MCP calls replaced by `AsyncMock`. Covers: non-procurement gate, Stage 3
bypass, VALIDATED, MCP_VALIDATED, full not-found recovery, and broadening retry.

**Section C — Stage 3 validation unit tests (5 tests)**  
Tests `run_stage3_hybrid_validation` directly with mocked `embed()`,
`query_semantic_cache()`, and `MCPSidecarClient`. Covers: VALIDATED, AMBIGUOUS,
MCP-validated on cache miss, not-found on empty MCP, and graceful DB error degradation.

### Running unit tests in CI/CD (no infrastructure required)

```bash
pytest IntentParser/ -m "not integration" -v --tb=short
```

All 15 unit tests complete in under 1 second.
