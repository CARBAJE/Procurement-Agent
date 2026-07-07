# Development Guide

This guide covers every coding convention, workflow pattern, and pitfall that a developer needs to know when contributing to the Procurement Agent. It is written for someone who has already read [Architecture](ARCHITECTURE.md) and [Installation](INSTALLATION.md) but is about to write their first line of production code.

---

## Table of Contents

1. [Code Conventions](#1-code-conventions)
2. [Things NOT to Do](#2-things-not-to-do)
3. [Repository Layout Quick-Reference](#3-repository-layout-quick-reference)
4. [Local Development Workflow](#4-local-development-workflow)
5. [Adding a New Service](#5-adding-a-new-service)
6. [Adding a New Database Table](#6-adding-a-new-database-table)
7. [Working with the IntentParser Pipeline](#7-working-with-the-intentparser-pipeline)
8. [Working with LangGraph (Negotiation Engine)](#8-working-with-langgraph-negotiation-engine)
9. [Error Handling Patterns](#9-error-handling-patterns)
10. [Known Problems and Workarounds](#10-known-problems-and-workarounds)

---

## 1. Code Conventions

### 1.1 Async-First

Every new feature in `IntentParser/`, `services/`, and `Bap-1/` ships as a coroutine.

```python
# correct
async def fetch_offerings(intent: BecknIntent) -> list[DiscoverOffering]:
    ...

# wrong — do not write sync functions for new service code
def fetch_offerings(intent: BecknIntent) -> list[DiscoverOffering]:
    ...
```

The only exception is `IntentParser.core.parse_request`, a sync wrapper that exists solely for legacy callers. It explicitly disables Stage 3 and must not be extended.

### 1.2 Module-Level Config

Every service and package has exactly one `config.py` at module level. That file is the single source of truth for environment variables. Never call `os.getenv()` inline in business logic.

```
IntentParser/config.py                  # LLM model names, Ollama URL, DB DSN, MCP sidecar URL
services/orchestrator/src/config.py     # orchestrator env vars (Pydantic Settings v2)
services/erp-adapter/src/config.py      # ERP vendor selection, budget-check flags
services/mcp-sidecar/config.py          # BAP client URL, port, timeouts, ranking threshold
```

When you add a new env var:

1. Add it to the relevant `config.py` with a type annotation and a safe default.
2. Add it to the service's `.env.example` (or the root `.env.example` if it is a cross-service concern).
3. Document it in [Environment](ENVIRONMENT.md).

**Known exception:** `services/mcp-sidecar/bap_client.py` reads `REDIS_URL` and `REDIS_RESULT_TIMEOUT` via `os.getenv()` because they must be real shell environment variables — dotenv loading does not work for these at MCP sidecar startup.

### 1.3 Pydantic v2

Use `field_validator` decorators. The deprecated `@validator` is not acceptable.

```python
# correct (Pydantic v2)
from pydantic import BaseModel, field_validator

class BecknIntent(BaseModel):
    delivery_timeline: int  # hours, not ISO 8601

    @field_validator("delivery_timeline")
    @classmethod
    def must_be_positive(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("delivery_timeline must be positive hours")
        return v
```

Follow `shared/models.BecknIntent` as the canonical reference. The anti-corruption layer fields have precise semantics:

| Field | Type | Unit / format |
|---|---|---|
| `delivery_timeline` | `int` | Hours (not ISO 8601) |
| `location_coordinates` | `str` | `"lat,lon"` decimal string |
| `budget_constraints` | `BudgetConstraints` | Typed `{max, min}` (not raw strings) |

### 1.4 Numbered SQL Migrations

All schema changes live in `database/sql/` with a two-digit numeric prefix.

```
NN_description.sql
```

Rules:

- **Never reorder or renumber** existing files. The setup script executes them in lexicographic order; FK dependencies rely on that order.
- New migrations go at the **next free prefix only**. If the last file is `23_foo.sql`, the next is `24_bar.sql`.
- All migrations must be **idempotent** using `IF NOT EXISTS` or `DO $$ BEGIN ... EXCEPTION WHEN duplicate_* THEN NULL; END $$`.
- Known naming issue: two files share the `22_` prefix on disk (`22_agent_memory_vector_dim.sql` and `22_pending_approval_columns.sql`). They are independent and safe in either order, but the ambiguity should be resolved by renaming one to `22b_` or moving it to `23_` in a future clean-up migration.

See [Database](DATABASE.md) for the full schema overview.

### 1.5 Bind-Mounted Libraries

Large Python packages are not copied into Docker images at build time; they are bind-mounted at runtime.

| Root package | Consumer container | Mount path |
|---|---|---|
| `IntentParser/` | `intention-parser` | `/app/IntentParser` |
| `shared/` | `intention-parser`, `beckn-bap-client`, `catalog-normalizer`, `data-normalizer` | `/app/shared` |
| `CatalogNormalizer/` | `catalog-normalizer` | `/app/CatalogNormalizer` |
| `DataNormalizer/` | `data-normalizer` | `/app/DataNormalizer` |

**Consequence for development:** changes to these packages take effect in running containers immediately without a rebuild. Changes to a service's own `src/` code require `docker compose up -d --build <service>`.

### 1.6 Library vs Service Boundary

When adding logic to the persistence layer, write it in `DataNormalizer/` (the library package), not in `services/data-normalizer/src/handler.py` (the HTTP adapter). The same split applies to `CatalogNormalizer/` versus `services/catalog-normalizer/`. This keeps business logic unit-testable independently of the HTTP layer.

### 1.7 Test Conventions

- Use `pytest-asyncio` with `asyncio_mode = auto`. Never decorate `async def test_*` with `@pytest.mark.asyncio`.
- Tests that require live PostgreSQL, Ollama, or the Docker stack must be tagged `@pytest.mark.integration` so they can be excluded in CI with `-m "not integration"`.
- Unit tests in `IntentParser/` and `DataNormalizer/` must not require any running infrastructure.

Test locations by scope:

| Scope | Directory | Infrastructure required |
|---|---|---|
| IntentParser unit | `IntentParser/tests/` | None |
| DataNormalizer unit | `DataNormalizer/tests/` | None |
| Negotiation guardrails | `services/negotiation_engine/tests/test_guardrails.py` | None |
| Bap-1 unit | `Bap-1/tests/` | None (HTTP mocked with `aioresponses`) |
| data-normalizer integration | `services/data-normalizer/tests/` | PostgreSQL (`procurement_agent_test` DB) |
| Database schema | `database/test_database.py` | PostgreSQL 16 + pgvector |
| IntentParser live pipeline | `IntentParser/tests/test_async_pipeline.py` | Ollama + PostgreSQL + MCP sidecar |

---

## 2. Things NOT to Do

These rules appear in `CLAUDE.md` and are reproduced here because violating them silently breaks the system — the error often appears in a completely different service, making the root cause hard to trace.

### 2.1 Never POST Directly to a BPP

All Beckn traffic must flow through `onix-bap:8081`. The ONIX Go adapter handles ED25519 signing and Beckn schema validation. Direct posts bypass both and produce unsigned, unvalidated messages that real BPPs will reject.

```
# correct flow
orchestrator -> beckn-bap-client:8002 -> onix-bap:8081 -> sim-bpp:3002

# wrong — never do this
orchestrator -> sim-bpp:3002 (direct)
```

### 2.2 Never Include the Action Name in ONIX Routing URLs

ONIX appends the Beckn action name automatically to the target URL. Including it duplicates the path and produces a 404.

```yaml
# correct — ONIX will append /on_discover
target: http://beckn-bap-client:8002

# wrong — resolves to http://beckn-bap-client:8002/on_discover/on_discover
target: http://beckn-bap-client:8002/on_discover
```

### 2.3 Never Use Contract.status.code = "CONFIRMED"

The ONIX schema validator rejects this value. Valid `Contract.status.code` values are: `DRAFT`, `ACTIVE`, `CANCELLED`, `COMPLETE`.

### 2.4 Never Await the /discover POST in the MCP Sidecar

The discovery flow in `services/mcp-sidecar/bap_client.py` must fire-and-forget the POST to the BAP client using `asyncio.create_task`, not `await`. Awaiting reintroduces the deadlock that [ADR-0001](../docs/architecture/decisions/0001-use-redis-pubsub-for-async-beckn-responses.md) was written to fix: the sidecar would block waiting for a response that can only arrive after the event loop processes the `/on_discover` callback — which cannot run while the event loop is blocked.

```python
# correct
asyncio.create_task(_post_discover(url, payload))

# wrong — deadlock
await _post_discover(url, payload)
```

### 2.5 Never Use time.sleep() to Flush asyncio.create_task Side Effects

`time.sleep()` blocks the thread, preventing the event loop from scheduling the task that was just created. Use `await asyncio.sleep(0)` to yield control.

```python
# correct — yields to the event loop, allowing the task to run
await asyncio.sleep(0)
assert await db.get_audit_record(txn_id) is not None

# wrong — the task never executes; the assertion will always fail
time.sleep(0.1)
assert await db.get_audit_record(txn_id) is not None
```

### 2.6 Never Reuse a transaction_id

Beckn Redis Pub/Sub channels are named `beckn_results:{transaction_id}`. Reusing a `transaction_id` delivers one transaction's catalog payload to a stale subscriber waiting on a different transaction.

### 2.7 Never Put Billing or Fulfillment Inline in Contract

`Contract` is `additionalProperties: false`. The ONIX schema validator will reject any extra fields. Correct placement:

| Data | Location in wire shape |
|---|---|
| Buyer billing address | `participants[role=buyer]` |
| Fulfillment details | `performance[]` |
| Payment | `settlements[]` |

See `Bap-1/CLAUDE.md` wire-shape gotchas for the full list of Contract pitfalls.

---

## 3. Repository Layout Quick-Reference

For a full service map see [Components](COMPONENTS.md). Key directories a developer touches frequently:

```
IntentParser/           NL-to-BecknIntent pipeline — Stage 1 + 2 + 3
  api.py                FastAPI app; /parse, /parse/batch, /parse/full
  orchestrator.py       Three-stage driver; complexity routing
  config.py             All env vars for the pipeline
  core/                 Stage 3 ANN validator, recovery flow
  recovery.py           log_unmet_demand, notify_buyer_no_stock, trigger_open_rfq_flow
                        (currently log-only stubs — see §10)

shared/models.py        Canonical BecknIntent, BudgetConstraints, DiscoverOffering

services/
  orchestrator/src/workflow.py        Pipeline state machine — primary integration point
  beckn-bap-client/src/bap_client.py  discover/select/init/confirm/status + CallbackCollector
  data-normalizer/src/handler.py      HTTP adapter (logic lives in DataNormalizer/)
  erp-adapter/src/routes/budget.py    Synchronous budget gate
  negotiation_engine/src/graph.py     LangGraph StateGraph definition
  mcp-sidecar/server.py               FastMCP; never-throw search_bpp_catalog tool
  sim-bpp/catalog.json                Bind-mounted catalog; edit without container restart

DataNormalizer/normalizer.py          All PostgreSQL write logic
CatalogNormalizer/normalizer.py       on_discover catalog format detection + mapping

database/sql/                         24 numbered SQL migration files
config/                               ONIX routing YAMLs (4 files)
docs/architecture/decisions/          ADR-0001 (Redis Pub/Sub)
frontend/src/app/                     Next.js 13 App Router pages
```

### Port Map

| Range | Services |
|---|---|
| :8001 | IntentParser (local) / intention-parser (Docker) |
| :8002 | beckn-bap-client |
| :8003 | comparative-scoring |
| :8004 / :18004 | orchestrator (8004) / negotiation-engine (host 18004) |
| :8005 | catalog-normalizer |
| :8006 | data-normalizer |
| :8007 | erp-adapter |
| :8008 | erp-mock |
| :8009 | analytics |
| :8015 | frontend_demo_gateway (demo-gateway) |
| :8081 / :8082 | onix-bap / onix-bpp (Go adapters) |
| :3000 | mcp-sidecar (local only — not in Docker) |
| :3002 | sim-bpp (Node.js) |
| :6379 | Redis |
| :8012 | claude_openai_proxy (local only — not in Docker) |
| :9092 | Kafka |
| :5432 | Main procurement_agent PostgreSQL (native host) |
| :55432 | Negotiation-only PostgreSQL (Docker) |

---

## 4. Local Development Workflow

### 4.1 Prerequisites

```bash
conda activate infosys_project
docker compose up -d                     # full stack (or subset — see below)
```

### 4.2 The Three-Terminal Pattern

Three processes must run on the host outside Docker:

**Terminal 1 — IntentParser**

```bash
conda activate infosys_project
cd IntentParser
uvicorn api:app --port 8001 --reload
```

Hot-reload is active. Any change to `IntentParser/` or `shared/` takes effect immediately on the next request.

**Terminal 2 — MCP Sidecar**

```bash
conda activate infosys_project
cd services/mcp-sidecar
BAP_API_KEY="dev-key" uvicorn server:app --port 3000
```

`BAP_API_KEY` must be non-empty; any value works in development. The sidecar is required for IntentParser Stage 3 (pgvector ANN + live catalog probe). Without it, Stage 3 degrades to `found=false` for every query.

**Terminal 3 — claude_openai_proxy (only needed for negotiation and demo flows)**

```bash
export CLAUDE_PROXY_KEY=your-local-key
uvicorn services.claude_openai_proxy.main:app --host 0.0.0.0 --port 8012
```

The proxy wraps the locally installed `claude` CLI. It is required by `negotiation-engine` (env var `NEGOTIATION_OPENAI_BASE_URL`) and `demo-gateway` (env var `OLLAMA_BASE_URL`). For persistent operation across reboots use the provided systemd unit: `services/claude_openai_proxy/claude-proxy.service`.

### 4.3 Starting a Subset of the Docker Stack

```bash
# Discovery infrastructure only
docker compose up -d redis onix-bap onix-bpp sim-bpp

# Full pipeline without the ML scoring stack
docker compose up -d redis onix-bap onix-bpp sim-bpp \
  beckn-bap-client catalog-normalizer data-normalizer \
  orchestrator comparative-scoring erp-adapter erp-mock

# MLOps stack (RankNet prediction-api + training)
docker compose -f docker-compose.mlops.yaml up -d
```

### 4.4 Tailing Logs

```bash
docker compose logs -f beckn-bap-client          # single service
docker compose logs -f orchestrator data-normalizer  # multiple services
```

### 4.5 Hot-Reloading sim-bpp Catalog

Edit `services/sim-bpp/catalog.json` directly. The file is bind-mounted into the container; the next HTTP request reads the updated catalog with no restart required.

### 4.6 Running Tests

```bash
# IntentParser — unit only (no infrastructure)
pytest IntentParser/ -m "not integration" -v

# IntentParser — full suite (requires Ollama + PostgreSQL + MCP sidecar)
INTENT_PARSER_TEST_MODE=live pytest IntentParser/ -v

# IntentParser — live async pipeline specifically
INTENT_PARSER_TEST_MODE=live pytest IntentParser/tests/test_async_pipeline.py -v -s

# Bap-1 — unit (HTTP mocked; no Docker required)
pytest Bap-1/tests/ -v -k "not integration"

# Database schema
cd database && export $(grep -v '^#' .env | xargs)
pytest test_database.py -v --tb=short

# Negotiation guardrails (no infrastructure)
pytest services/negotiation_engine/tests/test_guardrails.py -v

# data-normalizer integration (requires PostgreSQL)
pytest services/data-normalizer/tests/ -v
```

### 4.7 End-to-End Smoke Test

```bash
curl -X POST http://localhost:8001/parse/full \
  -H "Content-Type: application/json" \
  -d '{"query": "300 meters Cat6 UTP cable Mumbai 5 days"}'
```

A successful response includes `validation_status`, `mcp_validated`, and a populated `BecknIntent`.

---

## 5. Adding a New Service

Follow these steps to add a new Dockerised Python microservice.

### Step 1: Create the service directory

```
services/new-service/
  src/
    main.py        # FastAPI app, lifespan, routes
    config.py      # Pydantic Settings v2 — ALL env vars here
  requirements.txt
  Dockerfile
  README.md
```

### Step 2: Write the Dockerfile

Follow the pattern used by existing Python services (e.g. `services/erp-adapter/Dockerfile`):

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY src/ ./src/
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8XXX"]
```

### Step 3: Add to docker-compose.yml

```yaml
new-service:
  build: ./services/new-service
  container_name: new-service
  ports:
    - "8XXX:8XXX"
  environment:
    - DATABASE_URL=postgresql+asyncpg://procurement_user:${DB_PASSWORD}@host.docker.internal:5432/procurement_agent
  networks:
    - beckn_network
  healthcheck:
    test: ["CMD", "curl", "-f", "http://localhost:8XXX/health"]
    interval: 30s
    timeout: 5s
    retries: 3
```

Use the next available port in the `:8001–:8015` range. Check the port map in [Components](COMPONENTS.md) before claiming a port.

### Step 4: Add /health endpoint

Every service must expose a `/health` endpoint that returns `{"status": "ok"}` when the service is ready. This is used by Docker healthchecks and the readiness probe pattern.

### Step 5: Update documentation

- Add the service to [Components](COMPONENTS.md) with its port, role, and key files.
- Add any new env vars to [Environment](ENVIRONMENT.md).
- Add any new endpoints to [API Reference](API_REFERENCE.md).

---

## 6. Adding a New Database Table

### Step 1: Create the migration file

Create `database/sql/NN_description.sql` where `NN` is the next free two-digit prefix.

```sql
-- NN_new_table.sql
-- Idempotent — safe to re-run

CREATE TABLE IF NOT EXISTS new_table (
    id          UUID        DEFAULT gen_random_uuid() PRIMARY KEY,
    created_at  TIMESTAMPTZ DEFAULT NOW() NOT NULL,
    -- your columns here
);

CREATE INDEX IF NOT EXISTS idx_new_table_created_at
    ON new_table (created_at DESC);
```

Rules:
- Use `IF NOT EXISTS` everywhere — the setup script may be re-run on an existing schema.
- Use `gen_random_uuid()` (not `uuid_generate_v4()`) for UUID primary keys.
- Follow existing naming conventions: `snake_case` for tables and columns, `idx_{table}_{column}` for indexes.

### Step 2: Apply the migration

```bash
cd database
export $(grep -v '^#' .env | xargs)
python setup_database.py          # idempotent re-run
```

### Step 3: Add repository class

If the table is owned by the data-normalizer persistence layer, add a `DataNormalizer/repositories/new_table_repo.py` that follows the asyncpg repository pattern used by `request_repo.py`, `audit_repo.py`, and `memory_repo.py`.

### Step 4: Add integration test

Add a test class to `database/test_database.py` that confirms the table exists, has the expected columns, and that FK constraints hold. Run `pytest database/test_database.py` to verify.

### ENUM types — important gotcha

If your table needs a new ENUM type, define it in `database/sql/00_extensions_and_types.sql` AND create a migration that adds it via `ALTER TYPE ... ADD VALUE`. Do not just add the value to the migration file; the base definition must also be updated so a fresh install from scratch works correctly.

Existing ENUM types `embedding_model_type` and `ai_provider_type` contain spec-era values that do not match the as-built system. If you write code that stores an embedding model name in a column typed as `embedding_model_type`, verify first that your model name is present in the ENUM. See [Known Problems §10.1](#101-database-enum-types-contain-spec-era-values) for details.

---

## 7. Working with the IntentParser Pipeline

### 7.1 Pipeline Stages

```mermaid
flowchart TD
    A[HTTP POST /parse/full\nquery string] --> S1
    S1[Stage 1: LLM Intent Classification\nqwen3:8b or qwen3:1.7b\nClassifies intent type] --> S2
    S2[Stage 2: BecknIntent Extraction\nstructured JSON extraction via instructor\nproduces BecknIntent] --> S3
    S3[Stage 3: Validation\n1. pgvector ANN search\n2. MCP sidecar probe fallback\n3. Recovery flow if not_found]
    S3 -->|VALIDATED >= 0.85| OUT[Return BecknIntent with validation_status]
    S3 -->|AMBIGUOUS 0.45-0.85| OUT
    S3 -->|CACHE_MISS + mcp_validated| OUT
    S3 -->|not_found| REC[Recovery: broaden query → retry → RFQ stubs]
    REC --> OUT
```

Stage 3 is only active when IntentParser is run **locally** (not via the Docker `intention-parser` container). The container's `docker-compose.yml` env block sets `COMPLEX_MODEL=qwen3:1.7b` and `SIMPLE_MODEL=qwen3:1.7b`, collapsing the two-tier model routing.

### 7.2 Complexity Routing

`IntentParser/orchestrator.py::_is_complex()` routes to `COMPLEX_MODEL` (default `qwen3:8b`) when any of the following are true:

- Query length exceeds 120 characters
- Query contains two or more numeric tokens
- Query contains procurement-domain keywords

All other queries use `SIMPLE_MODEL` (default `qwen3:1.7b`). This routing is active only when running locally; the Docker container overrides both to `qwen3:1.7b`.

### 7.3 Adding a New Intent Type

1. Add the new intent type to the intent classification prompt in `IntentParser/core/classifier.py`.
2. Add a corresponding branch in `IntentParser/orchestrator.py` if the new intent requires different Stage 2 extraction behaviour.
3. Update `shared/models.BecknIntent` if the new intent needs new fields.
4. Update all downstream consumers of `BecknIntent` in `services/orchestrator/src/workflow.py`, `services/beckn-bap-client/src/bap_client.py`, and any other service that reads BecknIntent fields.
5. Add a unit test in `IntentParser/tests/`.

### 7.4 Modifying BecknIntent Fields

`shared/models.BecknIntent` is the anti-corruption layer boundary. When you change it:

1. Update `shared/models.py` (Pydantic v2 — use `field_validator`, not `@validator`).
2. Search for all usages across services:
   ```bash
   grep -r "BecknIntent" services/ IntentParser/ Bap-1/ --include="*.py" -l
   ```
3. Update each consumer. The primary consumers are `services/orchestrator/src/workflow.py` and `services/beckn-bap-client/src/bap_client.py`.
4. Update [API Reference](API_REFERENCE.md) if the change affects the `/parse/full` response shape.

### 7.5 Stage 3 Validation Thresholds

The similarity thresholds for Stage 3 ANN search are currently **hardcoded constants** in `IntentParser/core/validator.py`, not environment variables, despite appearing in the IntentParser README configuration table. Setting env vars for these thresholds has no effect. To change them, edit the constants directly:

| Constant | Value | Meaning |
|---|---|---|
| `VALIDATED_THRESHOLD` | 0.85 | ANN cosine similarity above which an item is accepted |
| `AMBIGUOUS_THRESHOLD` | 0.45 | Below VALIDATED_THRESHOLD but above this → ambiguous |

Items below `AMBIGUOUS_THRESHOLD` trigger the MCP sidecar probe. If the probe also returns `found=false`, the recovery flow runs.

### 7.6 Recovery Flow

The recovery stubs in `IntentParser/recovery.py` (`log_unmet_demand`, `notify_buyer_no_stock`, `trigger_open_rfq_flow`) are **logger-only** — they write to the application log but do not write to the database, call any external service, or send notifications. The module docstring marks them for replacement when infrastructure is provisioned. If you are implementing these integrations, replace the stub body rather than calling the stub from a wrapper.

---

## 8. Working with LangGraph (Negotiation Engine)

### 8.1 Graph Overview

The negotiation engine (`services/negotiation_engine/src/graph.py`) is a `StateGraph` where each node is an async function that reads and writes a shared `NegotiationState` dict.

```mermaid
flowchart TD
    START --> analyze_target
    analyze_target --> compute_counter_offer
    compute_counter_offer --> policy_guardrail_check
    policy_guardrail_check -->|G1-G6 pass| send_counter_offer
    policy_guardrail_check -->|violation| human_escalation
    send_counter_offer --> wait_for_async_callback
    wait_for_async_callback -->|on_select received| evaluate_response
    wait_for_async_callback -->|timeout| timeout_handler
    evaluate_response -->|accepted| finalize
    evaluate_response -->|counter-received| compute_counter_offer
    evaluate_response -->|max_rounds| finalize
    human_escalation -->|HITL resume| compute_counter_offer
    human_escalation -->|HITL reject| finalize
    finalize --> END
```

### 8.2 Adding a New Node

1. Write an `async def my_node(state: NegotiationState) -> dict` function in `services/negotiation_engine/src/graph.py`. Return only the keys of `NegotiationState` that the node changes.
2. Add the node to the `StateGraph` with `graph.add_node("my_node", my_node)`.
3. Add edges with `graph.add_edge(...)` or `graph.add_conditional_edges(...)`.
4. Add a unit test in `services/negotiation_engine/tests/test_guardrails.py` (no infrastructure) or `test_async_flow.py` (uses `MemorySaver`).

### 8.3 Guardrail Layers

Every counter-offer passes three independent validation layers before being sent to a BPP:

| Layer | Mechanism | On failure |
|---|---|---|
| L1 | Pydantic `discount_pct` field constraint (0.0–0.20) | `ValidationError` returned to the calling node |
| L2 | `validate_counter_offer()` in `src/guardrails.py` (G1–G6 rules) | Routes to `human_escalation` HITL interrupt |
| L3 | ONIX schema validation on the outbound Beckn message | Routes to error terminal state |

G2 (category cap) and G3 (supplier cap) violations escalate to human review. The operator can either approve the counter-offer (resuming the graph) or reject the transaction (routing to `finalize` with `status=REJECTED`).

### 8.4 HITL Interrupt and Resume

The graph is interrupted at `human_escalation` using LangGraph's `Command(interrupt=...)` pattern. The orchestrator polls for escalated negotiations and surfaces them in the approval queue. An operator response resumes the graph with `Command(resume=operator_decision)`.

The graph checkpoint is stored in `AsyncPostgresSaver` (configured via `NEGOTIATION_POSTGRES_DSN`). A restarted service can resume an interrupted graph from the last checkpoint. Without `NEGOTIATION_POSTGRES_DSN`, the engine falls back to `MemorySaver` (in-memory, state lost on restart).

### 8.5 Orchestrator Routes Negotiation via demo-gateway

The orchestrator does not call `negotiation-engine` directly. `workflow.py::_run_autonomous_negotiation` calls `DEMO_GATEWAY_URL` (default: `http://localhost:8015`), which is the `frontend_demo_gateway` service. The demo-gateway then calls `negotiation-engine:8004`. This extra hop exists for demo-flow reasons and is the production routing path in the current codebase. Keep `DEMO_GATEWAY_URL` in the orchestrator environment block when modifying negotiation flows.

---

## 9. Error Handling Patterns

See [System Design](SYSTEM_DESIGN.md) for architecture rationale. This section is the implementation reference.

### 9.1 Never-Throw Contract — MCP Tool Handlers

MCP tool handlers in `services/mcp-sidecar/server.py` must never raise a JSON-RPC error. All failure paths return a valid JSON object with `found: false`.

```python
# correct — top-level try/except in search_bpp_catalog
async def search_bpp_catalog(item_name: str, ...) -> dict:
    try:
        # ...
        return {"found": True, "items": [...], "probe_latency_ms": elapsed}
    except Exception:
        return {"found": False, "items": [], "probe_latency_ms": elapsed}
```

This applies to any new MCP tool you add to the sidecar.

### 9.2 Fire-and-Forget for Non-Critical Writes

Audit trail, agent memory, and ERP sync writes must not block the user-facing pipeline response.

```python
# correct — orchestrator pattern for non-critical writes
asyncio.create_task(_persist_audit(txn_id, event_type, payload))
asyncio.create_task(_persist_memory(intent, result))

# wrong — blocks the pipeline for DB write latency
await _persist_audit(txn_id, event_type, payload)
```

Fire-and-forget helpers must catch all exceptions internally and log them; they must never propagate an exception to the caller.

Note: audit writes are not retried. If data-normalizer is unavailable when a task runs, the audit event is permanently lost. The `kafka_offset` placeholder in every `_persist_audit` call (`kafka_offset=0`) is reserved for Phase 4 Kafka integration, which will provide durable delivery.

### 9.3 asyncio.gather with return_exceptions=True for Fan-Out

When dispatching to multiple independent targets (notification channels, network probes), use `asyncio.gather` with `return_exceptions=True` so a failure in one target does not cancel the others.

```python
results = await asyncio.gather(
    send_slack(message),
    send_teams(message),
    send_email(message),
    return_exceptions=True,
)
for r in results:
    if isinstance(r, Exception):
        logger.warning("notification channel failed: %s", r)
```

### 9.4 ERP Budget Gate — Fail-Closed vs Fail-Open

The budget gate is configurable per environment:

| Variable | docker-compose.yml default | Behaviour |
|---|---|---|
| `ERP_BUDGET_CHECK_ENABLED` | `true` | Whether the gate is called at all |
| `ERP_BUDGET_CHECK_REQUIRED` | `false` | `true` = fail-closed (deny on error), `false` = fail-open (allow on error) |

The `docker-compose.yml` default is **fail-open** (`false`) for developer convenience. Production deployments that handle real purchase orders must explicitly set `ERP_BUDGET_CHECK_REQUIRED=true`.

### 9.5 Database Error Middleware

The data-normalizer maps asyncpg exceptions to structured HTTP responses via `db_error_middleware`. Callers must handle 409 as an idempotency signal (duplicate write is not fatal):

| asyncpg exception | HTTP status | Body |
|---|---|---|
| `UniqueViolationError` | 409 | `{"error": "duplicate"}` |
| `ForeignKeyViolationError` | 409 | `{"error": "fk_violation"}` |
| `CheckViolationError` | 422 | `{"error": "check_violation"}` |
| `NotNullViolationError` | 422 | `{"error": "not_null_violation"}` |
| Any other `PostgresError` | 500 | `{"error": "db_error"}` |

---

## 10. Known Problems and Workarounds

These are confirmed bugs or gaps. Each entry describes the symptom, the root cause, and the correct workaround until a fix is applied.

### 10.1 Database ENUM Types Contain Spec-Era Values

**Symptom:** Inserting an agent memory record fails with `invalid input value for enum embedding_model_type`.

**Root cause:** `database/sql/00_extensions_and_types.sql` defines `embedding_model_type` with only `text-embedding-3-large` and `e5-large-v2`. The actual deployed models (`all-MiniLM-L6-v2`, `BAAI/bge-small-en-v1.5`) are absent. Migration `22_agent_memory_vector_dim.sql` adds `all-MiniLM-L6-v2` but never adds `BAAI/bge-small-en-v1.5`. Similarly, `ai_provider_type` is missing `ollama`.

**Workaround:** After running `python setup_database.py`, run:
```sql
ALTER TYPE embedding_model_type ADD VALUE IF NOT EXISTS 'BAAI/bge-small-en-v1.5';
ALTER TYPE ai_provider_type     ADD VALUE IF NOT EXISTS 'ollama';
```

**Fix required:** Add the missing values to `00_extensions_and_types.sql` (base definition) and update the `DEFAULT` in `15_agent_memory_vectors.sql` from `text-embedding-3-large` to `all-MiniLM-L6-v2`.

### 10.2 Docker Container Collapses Complexity Routing to qwen3:1.7b

**Symptom:** Complex procurement queries (multi-constraint, long descriptions) return lower-quality BecknIntent extractions when running via Docker.

**Root cause:** `docker-compose.yml` sets `COMPLEX_MODEL=qwen3:1.7b` and `SIMPLE_MODEL=qwen3:1.7b` for the `intention-parser` container. The complexity routing in `IntentParser/orchestrator.py` always resolves to `qwen3:1.7b` regardless of query complexity. The code default of `qwen3:8b` for `COMPLEX_MODEL` is only active when running IntentParser locally.

**Workaround:** Run IntentParser locally (not via Docker) for Stage 3 development and for testing complex query extraction quality.

### 10.3 catalog-normalizer LLM Fallback Uses Ollama, Not OpenAI

**Symptom:** Setting `OPENAI_API_KEY` has no effect on the catalog normalizer's UNKNOWN-format fallback.

**Root cause:** `CatalogNormalizer/llm_fallback.py` uses `instructor.from_openai(OpenAI(base_url=OLLAMA_URL, api_key="ollama"))` — the OpenAI SDK is used as an Ollama shim. The correct env vars are `OLLAMA_URL` (default `http://localhost:11434/v1`) and `NORMALIZER_MODEL` (default `qwen3:1.7b`).

### 10.4 demo-gateway Port Mismatch

**Symptom:** Running `frontend_demo_gateway` per its README on port 8005 causes connection refused errors from the orchestrator.

**Root cause:** The service README documents `--port 8005`, but `docker-compose.yml` runs it on port 8015, and `services/orchestrator/src/workflow.py` defaults `DEMO_GATEWAY_URL` to `http://localhost:8015`.

**Workaround:** Always start demo-gateway on port 8015: `uvicorn src.main:app --port 8015`.

### 10.5 Frontend Requires Live Keycloak — No Stub Credentials

**Symptom:** The Next.js frontend throws at runtime: `KEYCLOAK_CLIENT_ID must not be null`.

**Root cause:** `frontend/src/lib/auth.ts` configures only `KeycloakProvider`. There is no `CredentialsProvider` and no stub login. The credentials in `frontend/.env.local` connect to the Phase Two (phasetwo.io) hosted Keycloak tenant at `euc1.auth.ac/auth/realms/procurement-agent`.

**Workaround:** Obtain the Phase Two tenant credentials from the project lead. Add them to `frontend/.env.local` (git-ignored). Do not commit this file.

### 10.6 negotiate Audit Events Are Never Written

**Symptom:** The audit trail for a confirmed negotiated order contains no `negotiate` event type entries.

**Root cause:** `services/orchestrator/src/workflow.py::_run_autonomous_negotiation` contains zero calls to `_persist_audit`. Negotiation outcomes are written only to `result['messages']` in memory.

**Fix required:** Add `_persist_audit` calls at negotiation start, at each round's counter-offer generation, and at negotiation finalization. This is needed for SOX 404 compliance.

### 10.7 discovery_engine Is Orphaned

The `services/discovery_engine/` directory contains a complete `MultiNetworkCoordinator` implementation with per-network circuit breakers and deduplication. It has no entry in `docker-compose.yml` and is not called by any service. If you need multi-network Beckn discovery, this service must be wired into the stack — it is not currently reachable. Do not start extending the single-gateway path in `beckn-bap-client` for multi-network use without first evaluating whether `discovery_engine` can be plugged in directly.

### 10.8 recovery.py Stubs Never Notify or Write to DB

The functions `log_unmet_demand`, `notify_buyer_no_stock`, and `trigger_open_rfq_flow` in `IntentParser/recovery.py` are logger-only. When a procurement item cannot be found in the catalog after query broadening, the buyer receives no notification and no RFQ is created. The recovery flow completes silently with a `not_found` result.

---

## See Also

- [Architecture](ARCHITECTURE.md) — system context, Beckn lifecycle, async discovery model
- [System Design](SYSTEM_DESIGN.md) — ADR-0001 Redis Pub/Sub, design decision rationale
- [Components](COMPONENTS.md) — full service map with ports and responsibilities
- [API Reference](API_REFERENCE.md) — endpoint contracts for all services
- [Database](DATABASE.md) — schema overview, migration history
- [Environment](ENVIRONMENT.md) — all environment variables with defaults
- [Security](SECURITY.md) — HMAC rotation, ERP budget gate, ONIX signing
- [Configuration](CONFIGURATION.md) — ONIX routing YAMLs, Docker Compose overrides
- `Bap-1/CLAUDE.md` — Beckn v2 wire-shape gotchas (read before modifying the Beckn adapter)
- `docs/architecture/decisions/0001-use-redis-pubsub-for-async-beckn-responses.md` — ADR-0001
