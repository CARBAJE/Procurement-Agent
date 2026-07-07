# Repository Structure

## 1. Top-Level Layout

| Directory / File | Purpose | Key contents |
|---|---|---|
| `IntentParser/` | NL-to-BecknIntent pipeline — Stages 1, 2, 3. Runs locally as FastAPI :8001 OR is volume-mounted into the `intention-parser` Docker container | `api.py`, `orchestrator.py`, `config.py`, `core/`, `tests/` |
| `Bap-1/` | Phase-1 BAP monolith (reference/legacy). Not wired into docker-compose.yml; treated as standalone documentation and test suite | `src/`, `tests/`, `docs/ARCHITECTURE.md`, `CLAUDE.md` |
| `services/` | All dockerised microservices (Python, Node.js) plus the local `mcp-sidecar` and `claude_openai_proxy` helper processes | One subdirectory per service; see section 2 |
| `shared/` | Anti-corruption layer: `BecknIntent`, `BudgetConstraints`, `DiscoverOffering` Pydantic v2 models shared across services | `models.py`, `__init__.py` |
| `DataNormalizer/` | Library package volume-mounted into the `data-normalizer` container; owns all PostgreSQL write logic | `normalizer.py`, `repositories/` |
| `CatalogNormalizer/` | Library package volume-mounted into the `catalog-normalizer` container; owns all catalog-format detection and mapping | `normalizer.py`, `llm_fallback.py`, `format_detector.py` |
| `database/` | PostgreSQL schema automation: 24 numbered SQL migration files, setup script, integration test suite | `sql/` (24 files), `setup_database.py`, `test_database.py` |
| `config/` | ONIX adapter routing YAMLs for `onix-bap` (Go) and `onix-bpp` (Go) | `generic-routing-BAPCaller.yaml`, `generic-routing-BAPReceiver.yaml`, `generic-routing-BPPCaller.yaml`, `generic-routing-BPPReceiver.yaml`, `README.md` |
| `docs/` | Architecture decision records | `architecture/decisions/0001-use-redis-pubsub-for-async-beckn-responses.md` |
| `frontend/` | Next.js 13.5 buyer-facing web app | `src/app/`, `src/components/`, `src/lib/`, `CLAUDE.md` |
| `KnowledgeBase/` | Obsidian vault — project context, milestones, user stories, design specs | `project_scaffold/` subtree with milestones, components, AI models, integrations docs |
| `ComparativeScoring/` | Shared library used by `comparative-scoring` container (volume-mounted) | Scoring helpers |
| `docker-compose.yml` | 18-service stack on the `beckn_network` bridge | Service definitions, env overrides, healthchecks |
| `CLAUDE.md` | Authoritative conventions, what-not-to-do list, service port map, frequent commands | Architecture overview, stack, coding conventions |
| `.env.example` | Root environment template consumed by Docker Compose | DB connection vars, `CLAUDE_PROXY_BINARY_PATH`, `CLAUDE_PROXY_KEY` |
| `requirements.txt` | Minimal root-level Python deps (service-specific deps in `services/*/requirements.txt`) | `openai`, `langchain`, `langgraph`, `instructor`, `pydantic`, `pandas` |

(Source: CLAUDE.md -- Confidence: High; docker-compose.yml -- Confidence: High)

---

## 2. services/ Subdirectory Map

| Service directory | Container port | Host port(s) | In docker-compose.yml? | Language | Role |
|---|---|---|---|---|---|
| `intention-parser` | 8001 | 8001 | Yes | Python | Docker wrapper around the `IntentParser/` package; Stage 1+2 only inside Docker |
| `beckn-bap-client` | 8002 | 8002 | Yes | Python | Beckn Protocol BAP client; drives discover/select/init/confirm/status via ONIX |
| `comparative-scoring` | 8003 | 8003 | Yes | Python | Thin ML adapter; calls `prediction-api` (RankNet) and falls back to min-price heuristic |
| `orchestrator` | 8004 | 8000, 8004 | Yes | Python | Pipeline state machine; the only service that calls all other services |
| `catalog-normalizer` | 8005 | 8005 | Yes | Python | Translates raw Beckn `on_discover` catalogs to `DiscoverOffering[]` |
| `data-normalizer` | 8006 | 8006 | Yes | Python | Sole write path into PostgreSQL; also hosts pgvector memory and audit endpoints |
| `erp-adapter` | 8007 | 8007 | Yes | Python | Vendor-neutral ERP integration; budget gate, PO outbox, HMAC webhooks |
| `erp-mock` | 8008 | 8008 | Yes | Python | Local ERP stub with 6 configurable scenarios |
| `analytics` | 8009 | 8009 | Yes | Python | Procurement reporting queries; returns HTTP 503 (not mock data) when DB unavailable |
| `notification-dispatcher` | internal | none published | Yes | Python | Kafka consumer → Slack/Teams/Email fan-out for order status changes |
| `negotiation_engine` | 8004 | 18004 | Yes | Python | LangGraph automated price negotiation; host port 18004 avoids conflict with orchestrator |
| `frontend_demo_gateway` (demo-gateway) | 8015 | 8015 | Yes | Python | Demo BFF bridging Next.js to real Phase 2 scorer and LangGraph negotiation engine |
| `sim-bpp` | 3002 | 3002 | Yes | Node.js | Local BPP simulator; 9 providers, 31 items, AND-token matching, auto-advance lifecycle |
| `ComparativeAndScoreing/` | 8004 (prediction-api) | 8004 | Separate MLOps compose | Python | MLflow + RankNet training/validation/prediction stack; started with `docker-compose.mlops.yaml` |
| `mcp-sidecar` | 3000 | 3000 | **No** — runs locally | Python | MCP SSE bridge exposing `search_bpp_catalog` tool to IntentParser Stage 3 |
| `claude_openai_proxy` | 8012 | 8012 | **No** — runs locally | Python | Wraps local Claude Code CLI as an OpenAI-compatible `/v1/chat/completions` endpoint |
| `discovery_engine` | 8006 (configured) | none | **No** — orphaned | Python | Multi-network Beckn discovery fan-out; full implementation, no callers, not deployed |

Infrastructure services (images only, no build):

| Service | Image | Host port | Role |
|---|---|---|---|
| `onix-bap` | `fidedocker/onix-adapter` (linux/amd64) | 8081 | Beckn BAP ONIX adapter (Go); ED25519 signing, schema validation |
| `onix-bpp` | `fidedocker/onix-adapter` (linux/amd64) | 8082 | Beckn BPP ONIX adapter (Go) |
| `redis` | `redis:alpine` | 6379 | Pub/Sub broker (ADR-0001) + ONIX cache |
| `kafka` | `apache/kafka:latest` | 9092 | KRaft-mode single broker; used by erp-adapter, sim-bpp, notification-dispatcher, orchestrator |
| `postgres` | `pgvector/pgvector:pg16` | 55432 | **Negotiation DB only** (`negotiation` database); NOT the main `procurement_agent` DB |

> The main `procurement_agent` PostgreSQL instance runs natively on the host (or in a separately started `procurement-postgres` container). It is reached by Docker services via `host.docker.internal:5432`. The `postgres` service in docker-compose.yml serves only the `negotiation` database for the `negotiation_engine` service.
>
> (Source: docker-compose.yml -- Confidence: High; code_findings topic "Phase Test Guides, Database, …" -- Confidence: High)

---

## 3. What Runs Outside Docker

Three processes must run on the host, outside the Docker Compose stack:

### 3.1 IntentParser (FastAPI :8001)

```bash
conda activate infosys_project
cd IntentParser
uvicorn api:app --port 8001 --reload
```

Why local: The full Stage 3 pipeline (pgvector ANN + MCP sidecar fallback) requires direct access to the conda environment's `sentence-transformers` model cache and a live Ollama instance at `localhost:11434`. Docker image `intention-parser` volume-mounts `IntentParser/` and can run Stages 1+2, but CLAUDE.md treats the local process as the primary development path for Stage 3.

(Source: CLAUDE.md -- Confidence: High; IntentParser/README.md -- Confidence: High)

### 3.2 MCP Sidecar (FastAPI :3000)

```bash
conda activate infosys_project
cd services/mcp-sidecar
BAP_API_KEY="any-value-in-dev" uvicorn server:app --port 3000
```

Why local: The MCP SSE transport requires `BAP_API_KEY` to be set as a real environment variable (not just `.env`); `REDIS_URL` and `REDIS_RESULT_TIMEOUT` similarly must be real env vars, not dotenv-loaded. The service is not Dockerized because it is a developer-facing MCP tool bridge — IntentParser's Stage 3 connects to it over SSE from the same host Python process.

Startup note: BAP_API_KEY must not be empty; the service refuses to start without it. Any non-empty string works in dev.

(Source: services/mcp-sidecar/README.md -- Confidence: High; CLAUDE.md -- Confidence: High)

### 3.3 claude_openai_proxy (:8012)

```bash
export CLAUDE_PROXY_KEY=your-local-proxy-key
uvicorn services.claude_openai_proxy.main:app --host 0.0.0.0 --port 8012
```

Why local: The proxy wraps the locally installed `claude` CLI binary using host-level credentials (`~/.claude/.credentials.json`). It cannot be containerized without risking glibc incompatibility and root-owned writes to `~/.claude`. For persistence across reboots use the provided `services/claude_openai_proxy/claude-proxy.service` systemd unit file.

Two Dockerized services depend on this proxy at `host.docker.internal:8012`: `negotiation-engine` (env var `NEGOTIATION_OPENAI_BASE_URL`) and `demo-gateway` (env var `OLLAMA_BASE_URL`). Without this proxy running, autonomous negotiation and SupplierAgent demo flows will fail.

(Source: services/claude_openai_proxy/README.md, claude-proxy.service -- Confidence: High; code_findings gap 5 -- Confidence: High)

---

## 4. Bap-1/ Clarification

`Bap-1/` is a **standalone Phase-1 BAP monolith** that is NOT part of the live microservices stack. It is absent from `docker-compose.yml` and is not called by any service in `services/`.

| Question | Answer |
|---|---|
| Is it live? | No. Service code lives in `services/`; `Bap-1/` is treated as a reference implementation and test fixture. (Source: memory/project_structure.md -- Confidence: High) |
| Is it in Docker? | No entry in `docker-compose.yml`. It binds to port 8000 when run manually via `python -m src.server`. |
| What is it used for today? | (1) Reference for Beckn v2 wire-shape gotchas documented in `Bap-1/CLAUDE.md`. (2) 129 automated tests covering the Beckn protocol adapter, callbacks, sessions, and LangGraph graph — these tests are the only documented end-to-end flow coverage for the protocol layer. (3) `Bap-1/docs/ARCHITECTURE.md §7` documents the 14 known production blockers, referenced by `Bap-1/CLAUDE.md`. |
| Is the code importable? | `Bap-1/src/nlp/intent_parser_facade.py` wraps `IntentParser/` and is used by the Bap-1 server. The `IntentParser/` module is the canonical NL pipeline; the facade in Bap-1 is a thin caller. |
| When to read it? | Before modifying the Beckn protocol adapter, ONIX URL construction, or `Contract` wire shape — `Bap-1/CLAUDE.md` contains 8 hard-won wire-shape gotchas that apply to all Beckn traffic in the repo. |

(Source: Bap-1/CLAUDE.md -- Confidence: High; Bap-1/README.md -- Confidence: High; code_findings gap 20 -- Confidence: High)

---

## 5. Key Files for Each Service

### IntentParser/ (NL Pipeline)

| File | Role |
|---|---|
| `api.py` | FastAPI app; three endpoints: `/parse`, `/parse/batch`, `/parse/full` |
| `orchestrator.py` | Three-stage driver; complexity routing (`_is_complex()` selects `COMPLEX_MODEL` vs `SIMPLE_MODEL`); recovery flow on `not_found` |
| `config.py` | All env vars with defaults; `COMPLEX_MODEL` defaults to `qwen3:8b` locally but is overridden to `qwen3:1.7b` in the Docker container via `docker-compose.yml` |
| `recovery.py` | Stub functions: `log_unmet_demand`, `notify_buyer_no_stock`, `trigger_open_rfq_flow` — all log-only, no real integrations |

### services/orchestrator/

| File | Role |
|---|---|
| `src/workflow.py` | All pipeline logic: `run_pipeline`, `_compare_phase`, `run_procurement`, `_persist_audit` (13 call sites), `_persist_memory`, `_fetch_memory_context`, `_run_autonomous_negotiation` |
| `src/main.py` | FastAPI app; route definitions, lifespan, env loading |

### services/beckn-bap-client/

| File | Role |
|---|---|
| `src/main.py` | Route handlers; `/on_discover` publishes to Redis `beckn_results:{txn_id}` (ADR-0001 implementation) |
| `src/bap_client.py` | `discover_async()`, `select()`, `init()`, `confirm()`, `status()`; `CallbackCollector` per `(transaction_id, action)` |

### services/data-normalizer/

| File | Role |
|---|---|
| `src/handler.py` | HTTP routes for all normalize endpoints; delegates to `DataNormalizer/` library |
| `DataNormalizer/normalizer.py` | Facade; `normalize_request`, `normalize_intent`, `normalize_discovery`, `normalize_scoring`, `normalize_order`, `normalize_audit`, `write_memory`, `search_memory` |
| `DataNormalizer/repositories/` | Per-entity asyncpg repository classes (`request_repo.py`, `audit_repo.py`, `memory_repo.py`, etc.) |

### services/erp-adapter/

| File | Role |
|---|---|
| `src/routes/budget.py` | `POST /api/v1/budget/check`; synchronous, ≤800ms hard timeout; fail-closed by default |
| `src/routes/webhooks.py` | HMAC-SHA256 dual-secret rotation verification; per-vendor `pybreaker` circuit breakers |
| `src/adapters/` | `mock.py`, `sap.py`, `oracle.py` each implement the `ERPAdapter` Protocol |

### services/negotiation_engine/

| File | Role |
|---|---|
| `src/graph.py` | LangGraph `StateGraph` definition; all nodes (`analyze_target`, `compute_counter_offer`, `policy_guardrail_check`, `wait_for_async_callback`, `finalize`, etc.) |
| `src/guardrails.py` | `validate_counter_offer()` Layer 2 policy shield; enforces G1–G6 discount/lead-time/quantity limits |
| `src/broker.py` | `OnSelectListener`; subscribes to Redis `beckn_on_select_results` and resumes parked graph via `Command(resume=...)` |

### services/mcp-sidecar/

| File | Role |
|---|---|
| `server.py` | FastMCP server; `search_bpp_catalog` tool registration; never-throw contract — all failures return `{"found": false, ...}` |
| `bap_client.py` | Redis Pub/Sub subscriber + `asyncio.create_task` fire-and-forget POST to BAP client; REDIS_URL and REDIS_RESULT_TIMEOUT read via `os.getenv()` not pydantic-settings |
| `ranking.py` | Semantic ranking with `all-MiniLM-L6-v2` via `ThreadPoolExecutor`; filters items below `RANKING_MIN_SIMILARITY=0.30` |

### services/sim-bpp/

| File | Role |
|---|---|
| `server.js` | Express app; `/api/webhook/{action}` handler; AND-token catalog matching; auto-advance lifecycle scheduler |
| `catalog.json` | Bind-mounted at runtime; 9 providers, 31 items, 5 categories; edit without container rebuild |

### services/claude_openai_proxy/

| File | Role |
|---|---|
| `main.py` | FastAPI app; `BearerAuthMiddleware`; `/v1/chat/completions` → CLI subprocess |
| `adapter.py` | Stateless; invokes `claude -p --no-session-persistence --output-format stream-json`; maps OpenAI request to CLI args |
| `config.py` | Pydantic Settings v2; all `CLAUDE_PROXY_*` env vars; model-name mapping table (GPT names → Claude aliases) |
| `claude-proxy.service` | systemd user-unit for persistent host deployment; binds `0.0.0.0:8012` so Docker bridge can reach it |

### CatalogNormalizer/ (library, not a runnable service)

| File | Role |
|---|---|
| `normalizer.py` | `CatalogNormalizer` class; calls `FormatDetector` then `SchemaMapper` or `LLMFallbackNormalizer` |
| `llm_fallback.py` | Uses `instructor.from_openai(OpenAI(base_url=OLLAMA_URL, api_key="ollama"))` — Ollama backend, not OpenAI; OPENAI_API_KEY is never read |
| `format_detector.py` | Detects one of 5 variants: `BECKN_V2_FLAT_RESOURCES`, `ONDC_CATALOG`, `LEGACY_PROVIDERS_ITEMS`, `BPP_CATALOG_V1`, `UNKNOWN` |

### database/

| File | Role |
|---|---|
| `sql/00_extensions_and_types.sql` | `uuid-ossp`, `pgcrypto`, `vector` extensions; 20 ENUM types. Note: `embedding_model_type` ENUM contains only `text-embedding-3-large` and `e5-large-v2` — the actual deployed models are added by migration `22_agent_memory_vector_dim.sql` |
| `sql/22_agent_memory_vector_dim.sql` | Adds `all-MiniLM-L6-v2` to the ENUM via `ALTER TYPE … ADD VALUE`; changes `embedding_vector` column from `vector(3072)` to `vector(384)` |
| `setup_database.py` | Automation: lexicographic execution of all `sql/*.sql` files; flags `--create-db`, `--drop-all`, `--continue-on-exists` |
| `test_database.py` | 67 integration tests across 8 classes; confirms extensions, 16 tables, 22 indexes, 20 ENUM types, FK constraints |

### frontend/

| File | Role |
|---|---|
| `src/lib/auth.ts` | NextAuth configuration; `KeycloakProvider` only — no stub credentials; requires a live Phase Two / Keycloak OIDC instance at `euc1.auth.ac` |
| `src/lib/api.ts` | Axios wrappers for all backend calls |
| `src/app/` | Next.js App Router pages; 11 user-facing routes including `/request/[id]/audit` (audit trail SSR page) |
| `.env.example` | Identity provider config template for Phase Two (phasetwo.io); lists required Keycloak client setup steps |

(Source: All service README files in services/ -- Confidence: High; code_findings for each gap topic -- Confidence: High)

---

## 6. Naming Conventions

### SQL Migration Files

All files in `database/sql/` use a two-digit numeric prefix for FK-ordered lexicographic execution:

```
NN_description.sql
```

Example: `08_seller_offerings.sql` depends on `06_discovery_queries.sql` and `02_bpp.sql`, which have lower prefixes.

Rules:
- Never reorder or renumber existing files — the FK chain depends on lexicographic sort order.
- New migrations go at the next free prefix only.
- Use `IF NOT EXISTS` / `DO $$BEGIN … EXCEPTION WHEN duplicate_* THEN NULL; END$$` for idempotency.
- Known issue: two files share the `22_` prefix on disk (`22_agent_memory_vector_dim.sql` and `22_pending_approval_columns.sql`). The setup script's sort order between these two is filesytem-locale-dependent; they are independent of each other and either execution order is safe, but the naming ambiguity should be resolved in a future migration.

(Source: database/README.md -- Confidence: High; CLAUDE.md -- Confidence: High)

### Test File Locations

| Scope | Location | Runner | Notes |
|---|---|---|---|
| IntentParser unit | `IntentParser/tests/test_*.py` | `pytest IntentParser/ -m "not integration"` | No infrastructure required |
| IntentParser integration | `IntentParser/tests/test_async_pipeline.py`, `test_milestone.py` | `INTENT_PARSER_TEST_MODE=live pytest …` | Requires Ollama + PostgreSQL + MCP sidecar |
| Bap-1 unit | `Bap-1/tests/test_*.py` | `cd Bap-1 && pytest tests/ -v` | All HTTP mocked with `aioresponses`; no Docker required |
| DataNormalizer unit | `DataNormalizer/tests/test_*_repo.py` | `pytest DataNormalizer/tests/` | asyncpg mocked with `AsyncMock` |
| data-normalizer integration | `services/data-normalizer/tests/test_endpoints.py`, `test_full_pipeline.py` | `pytest services/data-normalizer/tests/` | Requires real PostgreSQL (`procurement_agent_test` DB) |
| erp-adapter smoke | `services/erp-adapter/tests/smoke_m3*.py` | `pytest services/erp-adapter/tests/` | Requires Docker stack |
| erp-adapter contracts | `services/erp-adapter/tests/test_contracts.py` | `python services/erp-adapter/tests/test_contracts.py` | **Not pytest-discoverable**; standalone script with `sys.exit(main())` |
| negotiation_engine unit | `services/negotiation_engine/tests/test_guardrails.py` | `pytest services/negotiation_engine/tests/` | No infrastructure; synchronous tests |
| negotiation_engine async | `services/negotiation_engine/tests/test_async_flow.py` | `pytest services/negotiation_engine/tests/` | Requires `langgraph` with `MemorySaver`; no external infra |
| memory performance | `services/data-normalizer/tests/test_memory_performance.py` | `pytest … -m integration` | Requires live PostgreSQL + pgvector |
| Database schema | `database/test_database.py` | `pytest database/test_database.py` | Requires PostgreSQL 16 + pgvector |

Services with zero test directories: `catalog-normalizer`, `analytics`, `beckn-bap-client`, `mcp-sidecar`, `intention-parser` (Docker wrapper), `erp-mock`.

(Source: code_findings gap 15 -- Confidence: High; KnowledgeBase phase test guides -- Confidence: High)

### config.py Pattern

Every Python service or package has a module-level `config.py` that is the single source of truth for environment variables. Inline `os.getenv()` calls elsewhere are a convention violation (CLAUDE.md).

```
IntentParser/config.py         — LLM model names, Ollama URL, DB connection, MCP sidecar URL
Bap-1/src/config.py            — ONIX URL, BAP credentials, callback timeout
services/mcp-sidecar/config.py — BAP client URL, port, MCP timeout, ranking min similarity
services/*/src/config.py       — Per-service env vars with Pydantic Settings v2
```

Exception: `services/mcp-sidecar/bap_client.py` reads `REDIS_URL` and `REDIS_RESULT_TIMEOUT` via `os.getenv()` directly (not pydantic-settings), because these must be real shell env vars — dotenv loading does not work for them.

(Source: CLAUDE.md -- Confidence: High; services/mcp-sidecar/README.md -- Confidence: High)

### Component/Library Mount Pattern

Large Python packages are not copied into service images at build time. They are bind-mounted at runtime via `docker-compose.yml` volumes:

| Volume mount | Consumer service |
|---|---|
| `./IntentParser:/app/IntentParser` | `intention-parser` |
| `./shared:/app/shared` | `intention-parser`, `beckn-bap-client`, `catalog-normalizer`, `data-normalizer` |
| `./CatalogNormalizer:/app/CatalogNormalizer` | `catalog-normalizer` |
| `./DataNormalizer:/app/DataNormalizer` | `data-normalizer` |

This means changes to shared library code take effect immediately in the running containers without a rebuild.

(Source: docker-compose.yml -- Confidence: High)

### Port Assignment Convention

Ports follow a service-tier grouping:

| Range | Tier |
|---|---|
| :8001–:8003 | Core pipeline lambdas (intent, BAP client, scoring) |
| :8004 | Orchestration (orchestrator and negotiation-engine share the container port; host ports differ: 8004 vs 18004) |
| :8005–:8009 | Support services (normalizers, ERP, analytics) |
| :8010 | Async fan-out (notification-dispatcher; no host port published) |
| :8015 | Demo gateway |
| :8081–:8082 | ONIX Go adapters |
| :3000 | MCP sidecar (local) |
| :3002 | sim-bpp (Node.js) |
| :6379 | Redis |
| :8012 | claude_openai_proxy (local, loopback) |
| :9092 | Kafka |
| :5432 | Main procurement_agent PostgreSQL (native host) |
| :55432 | Negotiation-only PostgreSQL (Docker) |

(Source: docker-compose.yml -- Confidence: High; CLAUDE.md -- Confidence: High; code_findings topic "Architecture — component map completeness" -- Confidence: High)
