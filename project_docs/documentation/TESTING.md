# Testing Guide

This document is the single reference for running, writing, and understanding tests across the Procurement Agent monorepo. It covers every test suite in the repository, their infrastructure requirements, and known coverage gaps.

Related: [Architecture](ARCHITECTURE.md) | [Installation](INSTALLATION.md) | [Development Guide](DEVELOPMENT_GUIDE.md)

---

## 1. Test Framework

The project uses **pytest** with **pytest-asyncio** throughout. All async test configuration lives in `pytest.ini` (or `pyproject.toml` / `setup.cfg`) at the root of each tested package.

### asyncio_mode = auto — Critical Rule

Every `pytest.ini` that governs async tests sets:

```ini
[pytest]
asyncio_mode = auto
```

This means:

- `async def test_*` functions are collected and run automatically — **no decorator needed**.
- `async def` fixtures are recognised automatically.
- **Do NOT add `@pytest.mark.asyncio` to any `async def test_*` function.** Under pytest-asyncio 0.21+, adding the decorator when `asyncio_mode = auto` is already active produces a deprecation warning or causes test collection failures.

This setting is active in `IntentParser/`, `Bap-1/`, and `services/data-normalizer/`.

### HTTP Mocking

All Bap-1 tests mock outbound HTTP with `aioresponses`. Fixtures in `Bap-1/tests/conftest.py` set `onix_url="http://mock-onix.test"` — a non-routable sentinel hostname that only resolves inside an `aioresponses` context manager. Do not run Bap-1 tests against a real ONIX stack; use `python run.py` for that.

### asyncpg Mocking (DataNormalizer unit layer)

The `DataNormalizer/tests/` unit layer mocks `asyncpg` entirely with `AsyncMock`. No database connection is made. Only `services/data-normalizer/tests/` (integration tests) hits a real PostgreSQL instance.

---

## 2. Test Organization

| Test file path | Service / Package | What it covers | Requires Ollama | Requires DB / Redis |
|---|---|---|---|---|
| `IntentParser/tests/test_async_pipeline.py` | IntentParser | Full Stage 1+2+3 pipeline in mock mode and live mode. 4 cases: VALIDATED, AMBIGUOUS, CACHE_MISS+MCP_VALIDATED, CACHE_MISS+not_found+recovery | No (mock) / Yes (live) | No (mock) / Yes (live) |
| `IntentParser/tests/test_milestone.py` | IntentParser | Section A: 18 integration tests (Ollama); Section B: 6 orchestrator unit tests; Section C: 5 Stage 3 validation unit tests | Partial | Partial |
| `Bap-1/tests/test_agent.py` | Bap-1 BAP | LangGraph ReAct state transitions: `parse_intent`, `discover`, `rank_and_select`, `send_select`, `present_results` (14 tests) | No | No |
| `Bap-1/tests/test_callbacks.py` | Bap-1 BAP | `CallbackCollector`: payload parsing, ACK response, ignores unregistered transactions, `collect` timeout, concurrent callbacks (10 tests) | No | No |
| `Bap-1/tests/test_discover.py` | Bap-1 BAP | `BecknIntent` validation, discover URL must contain `localhost:8081/bap/caller/discover`, numeric `price_value` (17 tests) | No | No |
| `Bap-1/tests/test_select.py` | Bap-1 BAP | `/select` wire format, select URL must contain `/bap/caller/select`, HTTP 500 raises exception (9 tests) | No | No |
| `Bap-1/tests/test_intent_parser.py` | Bap-1 BAP | NL facade unit tests (7) + integration tests (3 — require Ollama qwen3:8b). Integration asserts: "3 days" → `delivery_timeline=72`, "Bangalore" → `"12.9716,77.5946"`, descriptions as `list[str]` | Partial | No |
| `Bap-1/tests/` (7 other files) | Bap-1 BAP | Adapter URL construction, session store TTL, graph build helpers, mock ONIX responses (69 tests) | No | No |
| `database/test_database.py` | PostgreSQL schema | `TestConnection`, `TestExtensions`, `TestEnumTypes` (20 types), `TestTables` (16 tables), `TestIndexes` (22 indexes), `TestWorkflowRows`, `TestEndToEndQuery`, `TestConstraints` (67 tests) | No | Yes (PostgreSQL only) |
| `DataNormalizer/tests/test_request_repo.py` | DataNormalizer | INSERT, `channel` coercion to `'web'`, `SYSTEM_USER_ID` fallback, UPDATE status (4 tests) | No | No |
| `DataNormalizer/tests/test_intent_repo.py` | DataNormalizer | INSERT, confidence clamping `[0,1]`, invalid `intent_class` → `'out_of_scope'`, `BecknIntent` defaults (6 tests) | No | No |
| `DataNormalizer/tests/test_discovery_repo.py` | DataNormalizer | BPP upsert, negative `fulfillment_hours` clamped to 1, non-numeric price → 0.0 (5 tests) | No | No |
| `DataNormalizer/tests/test_scoring_repo.py` | DataNormalizer | `composite_score × 100` scaling, clamping `> 1` to 100, entries without `offering_id` skipped (4 tests) | No | No |
| `DataNormalizer/tests/test_order_repo.py` | DataNormalizer | Full FK chain `negotiation_outcomes → approval_decisions → purchase_orders`, quantity 0 → 1 (6 tests) | No | No |
| `DataNormalizer/tests/test_audit_repo.py` | DataNormalizer | INSERT with JSON `reasoning_payload`, invalid `event_type` → `ValueError`, empty `agent_action` → `ValueError` (5 tests) | No | No |
| `DataNormalizer/tests/test_normalizer_facade.py` | DataNormalizer | Delegation for all 5 normalize methods (5 tests) | No | No |
| `services/data-normalizer/tests/test_endpoints.py` | data-normalizer | Happy path for all 8 HTTP endpoints, validation 400 responses, DB errors → 409, defaults verified in DB (23 tests) | No | Yes (PostgreSQL) |
| `services/data-normalizer/tests/test_full_pipeline.py` | data-normalizer | 9-step E2E pipeline from request creation → confirmed order → delivered PO with 3 audit events (1 test) | No | Yes (PostgreSQL) |
| `services/data-normalizer/tests/test_memory_performance.py` | data-normalizer | P99 search latency < 100 ms (20 seeds, 20 iterations); ground-truth similarity for 4 known provider queries (2 tests, `@pytest.mark.integration`) | No | Yes (PostgreSQL + pgvector) |
| `services/sim-bpp/tests/test_auto_advance.py` | sim-bpp | Lifecycle ACCEPTED → PACKED → SHIPPED → OUT_FOR_DELIVERY → DELIVERED, cancel mid-advance, idempotency, `SIM_BPP_AUTO_ADVANCE=false` | No | Yes (data-normalizer running) |
| `services/negotiation_engine/tests/test_guardrails.py` | negotiation_engine | Layer 2 policy shield: G1 (absolute 20% cap), G2 (category cap), G3 (supplier cap), G5 (lead time), G6 (quantity) (16 tests) | No | No |
| `services/negotiation_engine/tests/test_async_flow.py` | negotiation_engine | LangGraph interrupt/resume mechanics, HITL accept/reject, gap 25% → `human_escalation`, `transaction_id` extraction from 6 Redis channel patterns (7 tests) | No | No |
| `services/erp-adapter/tests/smoke_m31.py` | erp-adapter | Budget gate smoke | No | Yes (erp-mock running) |
| `services/erp-adapter/tests/smoke_m32.py` | erp-adapter | Outbox + DLQ | No | Yes (PostgreSQL + erp-mock) |
| `services/erp-adapter/tests/smoke_m33.py` | erp-adapter | Bidirectional webhooks (HMAC secrets) | No | Yes (erp-mock) |
| `services/erp-adapter/tests/smoke_m34.py` | erp-adapter | SAP/Oracle real + circuit breaker | No | Yes (erp-mock) |
| `services/erp-adapter/tests/smoke_m35.py` | erp-adapter | `readyz` + DLQ replay | No | Yes (PostgreSQL) |
| `services/erp-adapter/tests/test_contracts.py` | erp-adapter | `NormalizedPO` Pydantic model + byte-equal JSON against pinned SAP/Oracle snapshots (**standalone script, not pytest-discoverable**) | No | No |
| `services/orchestrator/tests/` | orchestrator | Real-time tracking WebSocket flow only | No | Yes (Redis + Kafka) |
| `services/notification-dispatcher/tests/` | notification-dispatcher | Kafka consumer routing, channel fan-out | No | Yes (Kafka mock) |
| `services/frontend_demo_gateway/tests/` | demo-gateway | Scoring pipeline, negotiation mock | No | No |
| `services/discovery_engine/tests/` | discovery_engine | Multi-network fan-out, circuit breaker, deduplication | No | No (aiohttp mock) |

**Services with zero tests:** `services/catalog-normalizer/`, `services/analytics/`, `services/beckn-bap-client/`, `services/mcp-sidecar/`, `services/intention-parser/` (Docker wrapper only — the underlying `IntentParser/` package has tests), `services/erp-mock/`, `frontend/`.

---

## 3. Test Markers

| Marker | Meaning | Infrastructure required | How to skip |
|---|---|---|---|
| `@pytest.mark.integration` | Requires live PostgreSQL + pgvector (IntentParser, data-normalizer) or live Ollama qwen3:8b (Bap-1) | Yes | `-m "not integration"` |
| _(no marker)_ | Pure unit / in-process | None | Always runs |

Use the integration marker for any test that opens a network connection to PostgreSQL, Redis, Ollama, or any external service. Do not mark tests that use `AsyncMock` or `aioresponses` as integration — they require no live infrastructure.

---

## 4. Running Tests

All commands assume the conda environment is activated (`conda activate infosys_project`) and you are in the repo root (`Procurement-Agent/`).

### IntentParser — unit only (no infrastructure)

```bash
pytest IntentParser/ -m "not integration" -v
```

### IntentParser — full suite (requires Ollama at localhost:11434)

```bash
pytest IntentParser/ -v
```

### IntentParser Stage 3 async pipeline — live mode (requires PostgreSQL + pgvector + Ollama + MCP sidecar)

```bash
INTENT_PARSER_TEST_MODE=live pytest IntentParser/tests/test_async_pipeline.py -v -s
```

### Bap-1 — unit only (no infrastructure; all HTTP mocked with aioresponses)

```bash
pytest Bap-1/tests/ -v -k "not integration"
```

### Bap-1 — Ollama integration tests only (requires qwen3:8b pulled)

```bash
# Prerequisite: ollama serve is running and qwen3:8b has been pulled
ollama pull qwen3:8b
pytest Bap-1/tests/test_intent_parser.py -v -m integration
```

### Database schema (requires PostgreSQL 16 + pgvector with procurement_agent DB applied)

```bash
cd database && export $(grep -v '^#' .env | xargs)
pytest test_database.py -v --tb=short -q
```

### DataNormalizer unit layer (no infrastructure; asyncpg mocked)

```bash
python -m pytest DataNormalizer/tests/ -v
```

### data-normalizer integration tests (requires procurement_agent_test DB or Docker)

```bash
# Auto-detects testcontainers (Docker) or falls back to local Postgres
python -m pytest services/data-normalizer/tests/ -v

# Force local Postgres instead of testcontainers
USE_LOCAL_PG=1 TEST_DB_HOST=localhost python -m pytest services/data-normalizer/tests/ -v
```

### Phase 3 memory performance tests only

```bash
pytest services/data-normalizer/tests/test_memory_performance.py -v -m integration
```

### Phase 3 audit trail tests only

```bash
PYTHONPATH=$(pwd) .venv-test/bin/python -m pytest \
  services/data-normalizer/tests/test_endpoints.py -k "audit" -v
```

### negotiation_engine (no infrastructure; uses MemorySaver)

```bash
pytest services/negotiation_engine/tests/ -v
```

### erp-adapter contract test (standalone script — not pytest-discoverable)

```bash
python services/erp-adapter/tests/test_contracts.py
# Exit code 0 = all snapshots match
# Exit code 1 = wire shape drift detected (diff printed to stdout)
```

### erp-adapter smoke tests (requires Docker stack with erp-mock and PostgreSQL)

```bash
pytest services/erp-adapter/tests/smoke_m31.py \
       services/erp-adapter/tests/smoke_m32.py \
       services/erp-adapter/tests/smoke_m33.py \
       services/erp-adapter/tests/smoke_m34.py \
       services/erp-adapter/tests/smoke_m35.py -v
```

### MLOps stack (requires docker-compose.mlops.yaml)

```bash
# Start the MLOps stack
docker compose -f services/ComparativeAndScoreing/docker-compose.mlops.yaml \
  up -d mlflow-db mlflow-server prediction-api

# Train a model (auto-promotes to Staging if NDCG@5 >= 0.85)
docker compose -f services/ComparativeAndScoreing/docker-compose.mlops.yaml \
  --profile training up training-pipeline

# Weekly drift validation (exit code 1 = drift; writes /tmp/model_drift_detected.flag)
docker compose -f services/ComparativeAndScoreing/docker-compose.mlops.yaml \
  --profile validation up validation-service
```

### Bap-1 smoke test (end-to-end with ONIX Docker stack)

```bash
# Prerequisites: docker compose up -d onix-bap onix-bpp sim-bpp redis && ollama serve
cd Bap-1
python run.py "500 reams A4 paper 80gsm Bangalore 3 days max 200 INR"
```

Expected console output shows five labelled steps in sequence: `[parse_intent]` → `[discover]` → `[rank_and_select]` → `[send_select]` → `[present_results]`.

---

## 5. Writing New Tests

### Async test functions — no decorator

```python
# CORRECT
async def test_parse_intent_returns_beckn_intent(mock_pool):
    result = await parse_intent("300 meters Cat6 cable Mumbai")
    assert result.item_description is not None

# WRONG — do not do this
@pytest.mark.asyncio          # <-- causes failures under asyncio_mode=auto
async def test_parse_intent_returns_beckn_intent(mock_pool):
    ...
```

### Async fixtures

```python
import pytest_asyncio

@pytest_asyncio.fixture
async def db_pool():
    pool = await asyncpg.create_pool(dsn=settings.DATABASE_URL)
    yield pool
    await pool.close()
```

### Integration marker for infra-dependent tests

```python
import pytest

@pytest.mark.integration
async def test_vector_search_returns_similar_results(db_pool):
    # This test requires live PostgreSQL + pgvector
    results = await search_memory("A4 paper reams", limit=3)
    assert len(results) > 0
    assert all(r["similarity"] >= 0.75 for r in results)
```

Run only fast tests (no marker): `pytest -m "not integration" -v`

### Config via environment variables

Read all configuration from the module-level `config.py` in your service or package. Never call `os.getenv()` inline in test files. Override values in tests by setting environment variables before importing:

```python
import os
os.environ["INTENT_PARSER_TEST_MODE"] = "mock"

from IntentParser.orchestrator import run_pipeline
```

### asyncpg mock pattern (DataNormalizer unit tests)

```python
from unittest.mock import AsyncMock, MagicMock
import pytest

@pytest.fixture
def mock_pool():
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value={"request_id": "uuid-test-1234"})
    pool = MagicMock()
    pool.acquire = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
    return pool

async def test_insert_request_returns_id(mock_pool):
    repo = RequestRepo(pool=mock_pool)
    result = await repo.insert(item_text="100 units USB-C cable", channel="api")
    assert result["request_id"] == "uuid-test-1234"
```

### aioresponses pattern (Bap-1 tests)

```python
from aioresponses import aioresponses

async def test_discover_posts_to_onix(bap_client):
    with aioresponses() as m:
        m.post(
            "http://mock-onix.test/bap/caller/discover",
            payload={"context": {}, "message": {"ack": {"status": "ACK"}}}
        )
        result = await bap_client.discover_async(intent)
    assert result["message"]["ack"]["status"] == "ACK"
```

All Bap-1 fixtures configure `BecknConfig` with `onix_url="http://mock-onix.test"`.

### LangGraph in-memory checkpointing (negotiation_engine tests)

```python
from langgraph.checkpoint.memory import MemorySaver
import pytest

@pytest.fixture
def graph():
    return build_negotiation_graph(checkpointer=MemorySaver())
```

`MemorySaver` replaces `AsyncPostgresSaver` in tests. Leave `NEGOTIATION_POSTGRES_DSN` unset — the service falls back to `MemorySaver` automatically when the DSN is empty.

---

## 6. Phase 3 Acceptance Test Suites

Two acceptance test suites in `KnowledgeBase/tests/phase3/` validate Phase 3 features. They combine automated pytest assertions with manual observation steps.

### 6.1 Agent Memory and Learning (`phase3_agent_memory_learning.md`)

**Test 1 — Write path**

Complete a full order via the frontend (`/compare` → `/commit`), then verify:

```sql
SELECT COUNT(*) FROM agent_memory_vectors;
-- Row count must increase by exactly 1
```

The new row must have:
- `text_summary` matching `"{item} ordered from {provider} at {price} {currency} delivery in {hours}h"`
- `entity_type = 'transaction'`
- `embedding_model` consistent with the deployed `all-MiniLM-L6-v2` model

**Test 2 — Read path (API assertion)**

Submit a second request for a similar item, then verify the similarity search endpoint:

```bash
curl -X POST http://localhost:8006/normalize/memory/search \
  -H "Content-Type: application/json" \
  -d '{"item_text": "A4 paper reams", "limit": 3}'
# Expected: {"results": [...], "count": N} with similarity scores >= 0.75
```

The orchestrator's Agent Reasoning panel must also display a `memory_context` node.

**Test 3 — Isolation (unrelated item must not surface)**

```bash
curl -X POST http://localhost:8006/normalize/memory/search \
  -H "Content-Type: application/json" \
  -d '{"item_text": "Dell laptops 16GB RAM", "limit": 3}'
# Expected: {"results": [], "count": 0}
```

The 0.75 cosine similarity threshold must prevent unrelated items from appearing.

**Test 4 — DB integrity**

All rows in `agent_memory_vectors` must have `entity_type = 'transaction'`.

**Phase 3 memory acceptance checklist:**

- `agent_memory_vectors` has `vector(384)` column with HNSW cosine index (set by migration `22_agent_memory_vector_dim.sql`)
- `POST /normalize/memory/write` returns `{"stored": true}` in under 2 seconds (fastembed ONNX cold-start is 10–30 s on first call)
- `POST /normalize/memory/search` returns results with similarity scores
- After confirming order: orchestrator logs `[memory] stored transaction for <item>`
- Next similar request: reasoning panel shows `memory_context` node
- Memory enrichment latency under 5 seconds total

### 6.2 Audit Trail System (`phase3_audit_trail_system.md`)

Run the 10 automated pytest tests with:

```bash
PYTHONPATH=$(pwd) .venv-test/bin/python -m pytest \
  services/data-normalizer/tests/test_endpoints.py -k "audit" -v
```

| Test name | What it asserts |
|---|---|
| `test_post_audit_appends_event` | `POST /normalize/audit` returns `{"event_id": "..."}` with status 201 |
| `test_validation_errors_return_400` (×2) | Invalid `event_type` → 400; missing `agent_action` → 400 |
| `test_audit_get_by_request_id_returns_events` | `GET /normalize/audit?request_id=X` returns events in chronological order |
| `test_audit_get_by_request_id_empty_when_no_events` | Unknown `request_id` returns empty list, not 404 |
| `test_audit_get_by_po_id_returns_events` | `GET /normalize/audit?po_id=X` returns events scoped to that PO |
| `test_audit_get_missing_param_returns_400` | `GET /normalize/audit` with no params → 400 |
| `test_audit_get_event_by_id` | `GET /normalize/audit/{event_id}` returns full event including `reasoning_payload` |
| `test_audit_get_event_by_id_not_found_404` | Non-existent `event_id` → 404 |
| `test_audit_get_limit_respected` | Response respects the maximum 500-event limit |

**4 manual test cases (run after a full procurement flow):**

1. At least 4 events exist for the request: `request_created`, `intent_persisted`, `discovery_executed`, `order_confirmed` (minimum set)
2. `retention_until = event_timestamp + interval '7 years'` is set on all events
3. The frontend `/request/{id}/audit` page renders a vertical timeline with per-type icons and collapsible `reasoning_payload`
4. Decision chain is fully reconstructable from events alone — no external business context required (SOX 404 compliance check)

---

## 7. Coverage Assessment

### Well-tested areas

| Area | Approximate coverage | Notes |
|---|---|---|
| IntentParser pipeline (Stages 1–3) | Good | 2 test files; mock + live modes; all three stages exercised |
| Bap-1 BAP layer | Good | 12 files, 129 tests; full HTTP mocking with `aioresponses`; all LangGraph state transitions |
| PostgreSQL schema | Good | 67 tests across 8 classes; all 16 tables, 22 indexes, 20 ENUM types, FK constraints |
| DataNormalizer unit layer | Good | 35 tests; 7 files; all repository classes; `asyncpg` fully mocked |
| data-normalizer integration | Good | 26 tests; real PostgreSQL; 9-step E2E pipeline with FK chain |
| negotiation_engine | Good | Guardrail policy (16 tests) + LangGraph interrupt/resume mechanics (7 tests); no infrastructure required |
| sim-bpp lifecycle | Good | Auto-advance, cancel, idempotency, `SIM_BPP_AUTO_ADVANCE=false` toggle |
| erp-adapter contracts | Partial | Wire-shape snapshots are pinned but the runner is not pytest-discoverable; smoke tests require a live Docker stack |

### Known coverage gaps

| Area | Gap | Severity |
|---|---|---|
| `frontend/` | Zero tests of any kind — no Jest, no Vitest, no Playwright | High |
| `services/beckn-bap-client/` | No tests; the Beckn protocol HTTP client that publishes to Redis on `on_discover` has no automated verification | High |
| `services/catalog-normalizer/` | No tests; the `CatalogNormalizer/` library has no unit coverage despite format detection and LLM fallback logic | High |
| Orchestrator pipeline (`/run`, `/compare`, `/commit`) | Only real-time tracking WebSocket is tested; the main pipeline state machine has no automated test | High |
| E2E automated test | No test drives the full NL → Beckn → PostgreSQL → audit trail path automatically; all E2E verification is manual curl | High |
| CI/CD | No CI pipeline runs tests automatically; all test execution is manual | High |
| `services/analytics/` | No tests; SQL queries returning dashboard KPIs are untested | Medium |
| `services/mcp-sidecar/` | No tests; the never-throw contract (`{"found": false, ...}` on all failures) is enforced by convention only | Medium |
| `services/erp-mock/` | No tests; mock server responses are not contract-pinned except through erp-adapter smoke tests | Medium |
| Memory performance | `test_memory_performance.py` is `@pytest.mark.integration`; skipped in most contexts without a live pgvector instance | Low |

### Infrastructure requirements matrix

| Test suite | PostgreSQL | Ollama | Redis | Docker stack | MLflow |
|---|---|---|---|---|---|
| IntentParser (unit, `-m "not integration"`) | No | No | No | No | No |
| IntentParser (live, `INTENT_PARSER_TEST_MODE=live`) | Yes | Yes | Yes | No | No |
| Bap-1 (unit, `-k "not integration"`) | No | No | No | No | No |
| Bap-1 (integration, qwen3:8b) | No | Yes | No | No | No |
| Database tests | Yes | No | No | No | No |
| DataNormalizer unit | No | No | No | No | No |
| data-normalizer integration | Yes | No | No | No | No |
| negotiation_engine | No | No | No | No | No |
| erp-adapter smoke tests | Yes | No | No | Yes | No |
| ComparativeAndScoreing MLOps | No | No | No | Yes (mlops compose) | Yes |

---

## 8. End-to-End Smoke Test

This is a manual verification procedure to confirm the full IntentParser → Beckn pipeline is healthy.

### Prerequisites

```bash
# 1. Start core Docker services
docker compose up -d redis onix-bap onix-bpp sim-bpp

# 2. Start IntentParser locally
conda activate infosys_project
cd IntentParser
uvicorn api:app --port 8001 --reload &

# 3. Start MCP sidecar locally (BAP_API_KEY can be any non-empty string in dev)
cd services/mcp-sidecar
BAP_API_KEY="dev-key" uvicorn server:app --port 3000 &

# 4. Confirm Ollama is running with the required model
ollama serve &
ollama pull qwen3:8b
```

### Smoke request

```bash
curl -s -X POST http://localhost:8001/parse/full \
  -H "Content-Type: application/json" \
  -d '{"query": "300 meters Cat6 UTP cable Mumbai 5 days"}' \
  | python -m json.tool
```

### Expected healthy response shape

A healthy response includes all three stages and has `status: "success"`:

```json
{
  "status": "success",
  "intent": {
    "item_description": ["Cat6 UTP cable"],
    "quantity": 300,
    "unit": "meters",
    "delivery_timeline": 120,
    "location_coordinates": "19.0760,72.8777",
    "budget_constraints": { "max": null, "min": null }
  },
  "validation": {
    "stage": "VALIDATED",
    "source": "pgvector_cache"
  },
  "transaction_id": "txn-..."
}
```

Key fields to check:

| Field | What to look for | Common failure |
|---|---|---|
| `status` | Must be `"success"` — not `"error"` or absent | IntentParser not started or Ollama not running |
| `intent.delivery_timeline` | Integer hours (120 for "5 days") — never an ISO 8601 string | BecknIntent field validator failed |
| `intent.location_coordinates` | Decimal `"lat,lon"` string — never a city name | Stage 2 extraction regression |
| `validation.stage` | `VALIDATED`, `AMBIGUOUS`, or `not_found` | Stage 3 unavailable if `mcp-sidecar` is not running |
| `transaction_id` | Non-null UUID | DB write or Redis connection failure |

### Distinguishing partial failure

| Symptom | Likely cause |
|---|---|
| `status: "error"`, no `intent` field | Ollama is not running or `qwen3:8b` is not pulled |
| `intent` present but `validation` absent | MCP sidecar (:3000) is not running; Stage 3 was skipped |
| `validation.stage: "not_found"` with `recovery_triggered: true` | No catalog match found; recovery flow attempted query broadening |
| `transaction_id` is null | PostgreSQL or data-normalizer (:8006) unreachable |
| Response takes > 30 s | Ollama cold-starting the qwen3:8b model; subsequent calls will be faster |
