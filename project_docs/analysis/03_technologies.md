# Technology Stack

Covers every language, framework, library, LLM, datastore, protocol, and tool used across the monorepo. Sections draw primarily from source-verified code (`requirements.txt`, `package.json`, `config.py`, `docker-compose.yml`) with KnowledgeBase spec context where noted.

---

## 1. Full Technology Matrix

| Technology | Category | Version / Detail | Services / Files |
|---|---|---|---|
| Python | Language | 3.11+ required | IntentParser, all `services/` except sim-bpp and Go adapters |
| TypeScript | Language | strict mode, v5 | `frontend/` |
| Node.js | Language | 18+ | `services/sim-bpp/` |
| Go | Language | — (compiled image) | `onix-bap`, `onix-bpp` via `fidedocker/onix-adapter` image |
| FastAPI | Web framework | >=0.110 | intention-parser, data-normalizer, erp-adapter, ComparativeAndScoreing prediction-api, discovery_engine, frontend_demo_gateway, claude_openai_proxy, negotiation_engine |
| aiohttp | Async HTTP client/server | >=3.9 | beckn-bap-client, orchestrator, comparative-scoring, analytics, catalog-normalizer, erp-mock, sim-bpp (server) |
| uvicorn | ASGI server | >=0.27 (standard extras) | All FastAPI services |
| Pydantic | Data validation | v2 (`field_validator`, no `@validator`) | All Python services and IntentParser |
| pydantic-settings | Env-driven config | >=2.0 | beckn-bap-client, data-normalizer, discovery_engine, erp-adapter, frontend_demo_gateway, negotiation_engine, mcp-sidecar, claude_openai_proxy |
| asyncpg | PostgreSQL async driver | >=0.29 | data-normalizer, erp-adapter, analytics, intention-parser, IntentParser |
| pgvector | PostgreSQL vector extension | 0.7.0 (`vector(384)`) | agent_memory_vectors, bpp_catalog_semantic_cache tables |
| psycopg2-binary | PostgreSQL sync driver | >=2.9 | database/setup_database.py, database/test_database.py |
| psycopg (v3) | PostgreSQL async driver | >=3.2 (binary+pool extras) | negotiation_engine (LangGraph checkpoint) |
| Redis | Pub/Sub broker + cache | 7 (redis:alpine Docker) | beckn-bap-client (ADR-0001), orchestrator, mcp-sidecar, erp-adapter, negotiation_engine, frontend_demo_gateway |
| redis-py | Python Redis client | >=5.0 | beckn-bap-client, orchestrator, erp-adapter, mcp-sidecar, negotiation_engine |
| aiokafka | Async Kafka client | >=0.10 | orchestrator, erp-adapter, notification-dispatcher, sim-bpp, negotiation_engine |
| Apache Kafka | Event streaming | KRaft mode, single broker | po.status.changed topic; docker-compose.yml `kafka` service |
| PostgreSQL | Transactional DB | 16 + pgvector | Primary datastore; native host in dev |
| LangGraph | Agent state machine | >=0.2 | negotiation_engine (buyer graph), frontend_demo_gateway (routes to engine) |
| langgraph-checkpoint-postgres | Durable graph checkpointing | >=2.0 | negotiation_engine |
| langchain-core | LangChain primitives | >=0.3 | negotiation_engine, frontend_demo_gateway |
| langchain-openai | OpenAI/Ollama LangChain wrapper | >=0.2 | negotiation_engine |
| instructor | Structured LLM extraction | >=1.0 (IntentParser), >=1.15 (IntentParser/requirements) | IntentParser (Stage 1+2), CatalogNormalizer LLM fallback |
| openai (SDK) | OpenAI-compatible HTTP client | >=1.0 | IntentParser (Ollama target), CatalogNormalizer (Ollama target), intention-parser service, claude_openai_proxy tests |
| anthropic (SDK) | Anthropic API client | >=0.20 | IntentParser Stage 3 broadening fallback, Bap-1 |
| sentence-transformers | Embedding inference (PyTorch) | >=2.6 | IntentParser Stage 3 BPP semantic cache (`all-MiniLM-L6-v2`), mcp-sidecar semantic ranking |
| fastembed | Embedding inference (ONNX, no PyTorch) | >=0.3 | data-normalizer agent memory (`BAAI/bge-small-en-v1.5`) |
| numpy | Numerical arrays | >=1.24 | IntentParser, ComparativeAndScoreing, frontend_demo_gateway |
| torch (PyTorch) | Deep learning | >=2.0 | ComparativeAndScoreing (`nn.Linear` LTR model), frontend_demo_gateway |
| mlflow | Model registry + experiment tracking | >=2.10 | ComparativeAndScoreing (training-pipeline, prediction-api) |
| pybreaker | Circuit breaker | >=1.0 | erp-adapter (per-vendor circuit breakers) |
| tenacity | Retry logic | >=8.2 | erp-adapter |
| prometheus-client | Metrics exposition | >=0.20 | erp-adapter (`/metrics` endpoint, 9 series) |
| mcp | MCP SSE protocol | >=1.1 | mcp-sidecar (server), IntentParser (Stage 3 client) |
| Next.js | React framework | 13.5.6 (App Router) | `frontend/` |
| React | UI library | 18 | `frontend/` |
| Tailwind CSS | Utility CSS | 3.4.1 | `frontend/` |
| shadcn/ui | Component library (Radix + CVA) | — | `frontend/` |
| Radix UI | Headless primitives | @radix-ui/* | `frontend/` |
| recharts | Charting | 3.8.1 | `frontend/` (dynamically imported, ssr:false) |
| next-auth | Auth (Keycloak OIDC) | 4.24.14 | `frontend/` |
| axios | HTTP client | 1.15.0 | `frontend/` |
| lucide-react | Icons | 1.8.0 | `frontend/` |
| date-fns | Date formatting | 4.1.0 | `frontend/` |
| Jinja2 | Email HTML templates | >=3.1 | notification-dispatcher |
| aiosmtplib | Async SMTP | >=3.0 | notification-dispatcher |
| aioresponses | HTTP mock for tests | >=0.7.6 | Bap-1 tests (all 129 tests) |
| pytest / pytest-asyncio | Test runner | >=7/8; asyncio_mode=auto | All Python services and modules |
| ED25519 | ONIX request signing | via `signer.so` plugin | onix-bap Go adapter |
| HMAC-SHA256 | Webhook verification | dual-secret rotation | erp-adapter, orchestrator seller webhooks |

(Source: `services/*/requirements.txt`, `IntentParser/requirements.txt`, `Bap-1/requirements.txt`, `frontend/package.json`, `docker-compose.yml` -- Confidence: High)

---

## 2. Language Distribution

| Service / Module | Language | Key Frameworks / Libraries |
|---|---|---|
| IntentParser/ | Python 3.11+ | FastAPI, instructor, openai SDK (Ollama), anthropic, sentence-transformers, asyncpg, pgvector, mcp |
| Bap-1/ | Python 3.11+ | aiohttp, LangGraph, instructor, openai SDK (Ollama), pydantic-settings |
| services/intention-parser | Python 3.11+ | aiohttp, mounts IntentParser/ as volume |
| services/beckn-bap-client | Python 3.11+ | aiohttp, pydantic v2, redis-py |
| services/catalog-normalizer | Python 3.11+ | aiohttp, instructor, openai SDK, mounts CatalogNormalizer/ as volume |
| services/comparative-scoring | Python 3.11+ | aiohttp |
| services/data-normalizer | Python 3.11+ | aiohttp, asyncpg, fastembed, pydantic v2, mounts DataNormalizer/ as volume |
| services/orchestrator | Python 3.11+ | aiohttp, redis-py, aiokafka |
| services/erp-adapter | Python 3.11+ | FastAPI, asyncpg, pybreaker, tenacity, prometheus-client, redis-py, aiokafka |
| services/erp-mock | Python 3.11+ | aiohttp |
| services/analytics | Python 3.11+ | aiohttp, asyncpg |
| services/negotiation_engine | Python 3.11+ | FastAPI, LangGraph, langchain-openai, redis-py, aiokafka, langgraph-checkpoint-postgres |
| services/notification-dispatcher | Python 3.11+ | aiokafka, asyncpg, aiosmtplib, Jinja2 |
| services/discovery_engine | Python 3.11+ | FastAPI, aiohttp, pydantic v2 _(orphaned — no callers, not in docker-compose.yml)_ |
| services/frontend_demo_gateway | Python 3.11+ | FastAPI, PyTorch (nn.Linear), LangGraph, openai SDK, redis-py |
| services/claude_openai_proxy | Python 3.11+ | FastAPI, pydantic-settings _(loopback only, wraps Claude Code CLI)_ |
| services/mcp-sidecar | Python 3.11+ | mcp[cli], sentence-transformers, redis-py, pydantic-settings |
| services/sim-bpp | Node.js 18+ | aiohttp (HTTP server, custom), catalog.json hot-reload |
| services/ComparativeAndScoreing | Python 3.11+ | FastAPI, PyTorch, mlflow, psycopg2 |
| onix-bap, onix-bpp | Go | fidedocker/onix-adapter (linux/amd64), ONIX framework, ED25519 signer |
| frontend/ | TypeScript 5 | Next.js 13.5.6, React 18, next-auth 4, axios, recharts, Tailwind 3.4.1, shadcn/ui |
| database/ | Python 3.10+ | psycopg2-binary, pytest |

(Source: verified `requirements.txt` per service, `docker-compose.yml` image/build fields -- Confidence: High)

---

## 3. LLM Stack

### 3.1 Models in Use

| Model | Provider | Purpose | Invocation path | Opt-in required |
|---|---|---|---|---|
| qwen3:8b | Local Ollama | Stage 1 intent classification (all queries); Stage 2 BecknIntent extraction (complex queries) | `instructor.from_openai(OpenAI(base_url=OLLAMA_URL))` | No |
| qwen3:1.7b | Local Ollama | Stage 2 BecknIntent extraction (simple queries); CatalogNormalizer LLM fallback (UNKNOWN format) | Same pattern | No |
| claude-sonnet-4-6 | Anthropic API | Stage 3 query broadening fallback only (last resort when ANN cache miss) | `anthropic` SDK, `ANTHROPIC_API_KEY` | Yes — `ANTHROPIC_API_KEY` must be set |
| claude-3-5-sonnet (via proxy) | claude_openai_proxy :8012 | SupplierAgent in frontend_demo_gateway; HITL LLM calls in negotiation_engine | OpenAI SDK pointed at localhost:8012 | Yes — claude_openai_proxy must be running |

(Source: `IntentParser/config.py` lines 9-25, `CLAUDE.md`, `services/claude_openai_proxy/config.py` -- Confidence: High)

### 3.2 Complexity Routing

Stage 2 dispatches to `COMPLEX_MODEL` or `SIMPLE_MODEL` via `_is_complex(query)` in `IntentParser/orchestrator.py`:

```
_is_complex(query) = True  if  len(query) > 120
                           OR  count(numeric tokens) >= 2
                           OR  any procurement keyword present
```

When `True` → `COMPLEX_MODEL` (default `qwen3:8b`). When `False` → `SIMPLE_MODEL` (default `qwen3:1.7b`).

**Critical Docker override:** `docker-compose.yml` sets `COMPLEX_MODEL=qwen3:1.7b` for the `intention-parser` container, collapsing both routing branches to the smaller model. The complexity-routing logic is functional only when IntentParser is run locally outside Docker. No comment in `docker-compose.yml` explains this downgrade; it is most likely a memory/resource constraint for the containerised Ollama host. (Source: `IntentParser/config.py` line 9, `docker-compose.yml` lines 14–15 -- Confidence: High)

### 3.3 Claude Fallback Scope

`CLAUDE_FALLBACK_ENABLED = bool(ANTHROPIC_API_KEY)` in `IntentParser/config.py` line 24. When disabled (default), Stage 3 broadening falls back to regex-only query simplification. Claude is not a general fallback for intent parsing — its scope is strictly the `broaden_procurement_query()` recovery path triggered only on `CACHE_MISS + not_found`. (Source: `IntentParser/config.py` -- Confidence: High)

### 3.4 Claude OpenAI Proxy

`services/claude_openai_proxy/` provides a loopback FastAPI service exposing the locally installed Claude Code CLI as an OpenAI-compatible `/v1/chat/completions` endpoint. It is not a Docker container — it runs on the host and listens on port 8012. Two Docker services depend on it at runtime via `host.docker.internal:8012`:

- `negotiation-engine`: `NEGOTIATION_OPENAI_BASE_URL=http://host.docker.internal:8012/v1`
- `demo-gateway`: `OLLAMA_BASE_URL=http://host.docker.internal:8012/v1`

The proxy maps OpenAI model names to Claude aliases: `gpt-4o → sonnet`, `gpt-4o-mini → haiku`, `gpt-4 → opus`; `claude-*` names pass through unchanged.

**Limitations:** temperature, top_p, and max_tokens are accepted but silently ignored (the CLI exposes no sampling knobs). Each request bills the host's Claude account and incurs approximately 1–3 s cold-start latency per invocation. Concurrency is capped at `CLAUDE_PROXY_MAX_CONCURRENCY` (default 2). (Source: `services/claude_openai_proxy/config.py`, `services/claude_openai_proxy/README.md` -- Confidence: High)

---

## 4. Embedding Models

| Model | Library | Dimensions | Use case | Inference method | Service |
|---|---|---|---|---|---|
| all-MiniLM-L6-v2 | sentence-transformers | 384 | BPP catalog semantic cache (Stage 3 ANN); MCP sidecar similarity ranking | PyTorch (ThreadPoolExecutor) | IntentParser, mcp-sidecar |
| BAAI/bge-small-en-v1.5 | fastembed (ONNX Runtime) | 384 | Agent memory vectors (write + search) | ONNX (no PyTorch, ~130 MB model) | data-normalizer (DataNormalizer/repositories/memory_repo.py) |

Both models produce 384-dimensional cosine vectors. Both are downloaded from Hugging Face Hub on first use and cached locally. Both are stored in pgvector `vector(384)` columns with HNSW cosine indexes. (Source: `DataNormalizer/repositories/memory_repo.py` lines 6–14, `IntentParser/config.py` line 14, `services/mcp-sidecar/requirements.txt` -- Confidence: High)

### 4.1 Known Schema Mismatch

`DataNormalizer/repositories/memory_repo.py` line 22 sets `_EMBEDDING_MODEL_ENUM = "all-MiniLM-L6-v2"` — this is the value written into the `embedding_model` column of `agent_memory_vectors`. The actual inference model is `BAAI/bge-small-en-v1.5` (line 14). The workaround is intentional: `database/sql/00_extensions_and_types.sql` defines `embedding_model_type` as `ENUM('text-embedding-3-large', 'e5-large-v2')`, which contains neither real model name. Migration `22_agent_memory_vector_dim.sql` adds `'all-MiniLM-L6-v2'` to the ENUM but not `'BAAI/bge-small-en-v1.5'`. The result: the DB column stores `'all-MiniLM-L6-v2'` as a proxy label for what is actually BAAI/bge-small-en-v1.5 inference. Any tooling that reads `embedding_model` to reconstruct embeddings will use the wrong model. (Source: `DataNormalizer/repositories/memory_repo.py` lines 14+22, `database/sql/00_extensions_and_types.sql`, `database/sql/22_agent_memory_vector_dim.sql` -- Confidence: High)

### 4.2 Similarity Thresholds

| Context | Threshold | Effect |
|---|---|---|
| IntentParser Stage 3 ANN hit | >= 0.85 | VALIDATED — skips MCP sidecar |
| IntentParser Stage 3 ANN partial | 0.45–0.85 | AMBIGUOUS — proceeds to MCP sidecar |
| IntentParser Stage 3 ANN miss | < 0.45 | CACHE_MISS — triggers recovery/broadening |
| Agent memory retrieval (data-normalizer) | >= 0.75 | Included in reasoning panel; below threshold filtered out |
| MCP sidecar ONIX ranking | >= 0.30 (`RANKING_MIN_SIMILARITY`) | Items below threshold dropped from results |

(Source: `IntentParser/config.py` lines 18–19, `CLAUDE.md`, `services/mcp-sidecar/README.md` -- Confidence: High)

---

## 5. Key Dependency Versions

### 5.1 Python Package Minimums by Service

| Package | IntentParser | Bap-1 | data-normalizer | erp-adapter | negotiation_engine | orchestrator |
|---|---|---|---|---|---|---|
| aiohttp | >=3.9 | >=3.9 | >=3.9 | >=3.9 | >=3.9 | >=3.9 |
| pydantic | >=2.0 | >=2.5 | >=2.0 | >=2.6 | >=2.11 | — |
| asyncpg | >=0.29 | — | >=0.29 | >=0.29 | — | — |
| redis | — | — | — | >=5.0 | >=5.0 | >=5.0 |
| aiokafka | — | — | — | >=0.12 | >=0.10 | >=0.12 |
| instructor | >=1.15 | — | — | — | — | — |
| openai SDK | >=1.0 | — | — | — | — | — |
| anthropic SDK | >=0.20 | >=0.40 | — | — | — | — |
| langgraph | — | >=0.2 | — | — | >=0.2 | — |
| langchain-core | — | >=0.3 | — | — | >=0.3 | — |
| sentence-transformers | >=2.6 | — | — | — | — | — |
| fastembed | — | — | >=0.3 | — | — | — |
| pgvector | >=0.3 | — | — | — | — | — |
| mcp | >=1.1 | — | — | — | — | — |

(Source: `services/*/requirements.txt`, `IntentParser/requirements.txt`, `Bap-1/requirements.txt` -- Confidence: High)

### 5.2 Frontend Package Versions (exact)

| Package | Version |
|---|---|
| next | ^13.5.6 |
| react / react-dom | ^18 |
| tailwindcss | ^3.4.1 |
| next-auth | ^4.24.14 |
| axios | ^1.15.0 |
| recharts | ^3.8.1 |
| lucide-react | ^1.8.0 |
| date-fns | ^4.1.0 |
| typescript | ^5 |
| eslint-config-next | 14.2.35 (ESLint plugin only — not a Next.js framework version) |

(Source: `frontend/package.json` -- Confidence: High)

### 5.3 Notable Cross-Service Divergences

- **`orchestrator/requirements.txt`** lists only `aiohttp>=3.9`, `redis>=5.0`, `aiokafka>=0.12`. It does not declare `pydantic` or `pydantic-settings`, yet the service uses Pydantic models. This is possible only because it imports from `DataNormalizer/` and `shared/` volumes at runtime which pull in the conda environment's pydantic installation. This creates an implicit dependency invisible to `pip install -r requirements.txt`. (Source: `services/orchestrator/requirements.txt` -- Confidence: High)

- **`comparative-scoring/requirements.txt`** lists only `aiohttp>=3.9` — the service is a thin HTTP adapter that proxies to `prediction-api`. All heavy ML deps live in `services/ComparativeAndScoreing/requirements.txt` (`torch>=2.0`, `mlflow>=2.10`). (Source: `services/comparative-scoring/requirements.txt` -- Confidence: High)

- **Root `requirements.txt`** contains only `openai`, `langchain`, `langchain-openai`, `langgraph`, `instructor`, `pydantic`, `pandas`. It is a minimal bootstrap manifest; per-service deps are authoritative. (Source: `requirements.txt` -- Confidence: High)

---

## 6. Implementation vs Original Spec

The canonical source for deviations is `KnowledgeBase/project_scaffold/implementation_deviations.md`.

| Component | Original spec | As implemented | Reason |
|---|---|---|---|
| Primary LLM | GPT-4o | qwen3:8b via local Ollama | Zero cost; offline; data sovereignty; quality sufficient for structured extraction |
| Lightweight LLM | GPT-4o-mini | qwen3:1.7b via local Ollama | Same |
| LLM fallback for intent parsing | claude-sonnet-4-6 as general fallback | claude-sonnet-4-6 for Stage 3 broadening only; opt-in via `ANTHROPIC_API_KEY` | Redesigned scope — Ollama handles all primary paths |
| Embedding model | OpenAI text-embedding-3-large (3072 dims) | BAAI/bge-small-en-v1.5 (384 dims, fastembed ONNX) + all-MiniLM-L6-v2 (384 dims, sentence-transformers) | No external API calls; local ONNX inference; sufficient quality at 384 dims for < 100K records |
| Fallback embedding | e5-large-v2 | Not used (superseded by the two models above) | Consolidation |
| Vector dimensions | 3072 | 384 | Matches local model output; migration `22_agent_memory_vector_dim.sql` corrects original table definition |
| Vector store | Qdrant (self-hosted) + pgvector mirror | pgvector only (PostgreSQL 16) | Pilot corpus < 100 K records where pgvector HNSW is sufficient; zero additional infrastructure |
| BPP simulator | fidedocker/sandbox-2.0 | sim-bpp (local Node.js, port 3002) | sandbox-2.0 had a fixed catalog; sim-bpp hot-reloads `catalog.json` and supports the auto-advance lifecycle state machine |
| ERP event bus | Apache Kafka (acks=all, replication >= 3) | PostgreSQL outbox pattern (`erp_sync_records` table, `FOR UPDATE SKIP LOCKED` worker) | Kafka broker not yet deployed; outbox is operationally equivalent and simpler |
| Audit event bus | Kafka (7-year retention, replication >= 3) | Direct PostgreSQL `INSERT` into `audit_trail_events`; `kafka_offset` column is a placeholder | Same; `splunk_indexed` flag column exists but no exporter wired |
| LLM call tracing | LangSmith | `reasoning_payload JSONB` column in `audit_trail_events` | LangSmith deferred to Phase 4; all trace data is captured and ready for wiring |
| Container orchestration | Kubernetes (EKS/AKS/GKE) + Helm + ArgoCD | Docker Compose single-host, 18 services on `beckn_network` bridge | Phase 4 target |
| API gateway | Kong | None — direct HTTP via Docker DNS | Phase 4 |
| CI/CD | GitHub Actions (lint → test → build → Helm) | Manual `docker compose up` | Phase 4 |
| Image scanning | Trivy in CI | Not configured | Phase 4 |
| SIEM | Splunk sink + ServiceNow consumer | `splunk_indexed` flag column exists; no exporter | Phase 4 |
| Retention enforcement | Nightly DELETE/archival job | `retention_until` timestamp exists; no scheduled job | Phase 4 |
| Agent memory ETL | PostgreSQL → Qdrant nightly batch sync | Not applicable — pgvector is the sole store | Qdrant eliminated |
| Model governance pipeline | Weekly 100-scenario eval via GitHub Actions + LangSmith | Schema (`model_governance_records`) exists; pipeline not implemented | Phase 4 |
| mTLS to SAP/Oracle | mTLS SSL context | SSL context hook wired but not activated | Phase 4 |
| Frontend framework | React 18 + Next.js 14 (KnowledgeBase spec) | Next.js 13.5.6 + React 18 | `package.json` is authoritative; KnowledgeBase spec doc is outdated |
| Frontend auth | Keycloak OIDC (with stub credentials for dev) | Keycloak OIDC only via Phase Two cloud tenant (`euc1.auth.ac`); no stub/credential provider at any environment | `frontend/src/lib/auth.ts` has only `KeycloakProvider`; CLAUDE.md description of "stub credentials" is incorrect |

(Source: `KnowledgeBase/project_scaffold/implementation_deviations.md`, `IntentParser/config.py`, `docker-compose.yml`, `frontend/package.json`, `frontend/src/lib/auth.ts`, code findings -- Confidence: High)

---

## 7. Infrastructure and Protocol Components

### 7.1 ONIX Adapters

Both `onix-bap` (:8081) and `onix-bpp` (:8082) use the `fidedocker/onix-adapter` image (Go binary, `platform: linux/amd64`). They apply middleware chains:

- **BAPCaller / BPPCaller** (outbound): `addRoute → sign → validateSchema`
- **BAPReceiver / BPPReceiver** (inbound): `validateSign → addRoute → validateSchema`

The schema validator is pinned at ONIX commit `d43ec30d`. Later commits introduced a `$ref` resolution bug in `SignatureHeader` / `AckSignatureHeader`. Do not upgrade without running a full end-to-end signing test. (Source: `config/README.md` -- Confidence: High)

ONIX routing target URLs must **not** include the action name — ONIX appends it automatically. `http://host:8000/bpp` with action `discover` becomes `http://host:8000/bpp/discover`. Including the action name produces a 404. (Source: `CLAUDE.md` -- Confidence: High)

### 7.2 Redis Usage Patterns

| Channel / Key pattern | Producer | Consumer | TTL |
|---|---|---|---|
| `beckn_results:{transaction_id}` | beckn-bap-client `/on_discover` | mcp-sidecar subscriber; orchestrator CallbackCollector | Pub/Sub (no TTL) |
| `beckn_on_select_results` | demo-gateway (SupplierAgent response) | negotiation_engine `OnSelectListener` | Pub/Sub |
| ONIX routing cache (internal) | onix-bap / onix-bpp | same adapters | Managed by ONIX |
| Redis Pub/Sub (erp-adapter) | erp-adapter (inbound webhook) | orchestrator (fallback when Kafka unavailable) | Pub/Sub |

(Source: `services/beckn-bap-client/README.md`, `services/negotiation_engine/README.md`, `docs/architecture/decisions/0001-use-redis-pubsub-for-async-beckn-responses.md` -- Confidence: High)

### 7.3 Database Schema Summary

PostgreSQL 16 with pgvector extension. 24 numbered SQL migration files in `database/sql/` executed in lexicographic order. 16 entity tables. Two vector tables:

| Table | Model | Dims | Index |
|---|---|---|---|
| `agent_memory_vectors` | BAAI/bge-small-en-v1.5 (stored enum value: `all-MiniLM-L6-v2`) | 384 | HNSW cosine, `ef_search=100` |
| `bpp_catalog_semantic_cache` | all-MiniLM-L6-v2 | 384 | HNSW cosine |

Two migration files share the `22_` prefix on disk: `22_agent_memory_vector_dim.sql` and `22_pending_approval_columns.sql`. Lexicographic sort order between them is filesystem-dependent; both are independent of each other so the ambiguity has no current impact, but adding dependencies between the two files would risk ordering bugs. (Source: `database/README.md`, `database/sql/00_extensions_and_types.sql`, `DataNormalizer/repositories/memory_repo.py` -- Confidence: High)

---

## 8. Known Technology-Related Defects

The following are confirmed problems discovered during code verification. They are not hypothetical risks — each has a direct failing scenario.

| # | Defect | Location | Impact |
|---|---|---|---|
| 1 | `embedding_model_type` ENUM lacks both actual model names | `database/sql/00_extensions_and_types.sql` | Any INSERT with `embedding_model='BAAI/bge-small-en-v1.5'` fails. `memory_repo.py` works around this by storing `'all-MiniLM-L6-v2'` as a proxy label — misleading for tooling that reads the column. |
| 2 | `ai_provider_type` ENUM lacks `'ollama'` | `database/sql/00_extensions_and_types.sql` | Any model governance record INSERT for an Ollama-hosted model fails at the DB constraint. |
| 3 | `docker-compose.yml` sets `COMPLEX_MODEL=qwen3:1.7b` | Lines 14–15 | Dockerised intention-parser always uses qwen3:1.7b for all queries; qwen3:8b is never invoked in the containerised stack. |
| 4 | catalog-normalizer LLM fallback is Ollama, not OpenAI | `CatalogNormalizer/llm_fallback.py` | The service README incorrectly states `OPENAI_API_KEY` is required for LLM fallback. The actual env vars are `OLLAMA_URL` and `NORMALIZER_MODEL`. |
| 5 | `claude_openai_proxy` binds loopback only by default | `services/claude_openai_proxy/config.py` | Docker containers cannot reach it at `host.docker.internal:8012` unless `CLAUDE_PROXY_HOST=0.0.0.0` is set (as documented in `claude-proxy.service` ExecStart). |
| 6 | `agent_memory_vectors.embedding_model` DEFAULT is `'text-embedding-3-large'` | `database/sql/15_agent_memory_vectors.sql` line 16 | Even after migration 22 adds `'all-MiniLM-L6-v2'` to the ENUM, the column DEFAULT remains the old spec value. Any INSERT relying on the column default writes the wrong model name. |

(Source: code verification findings -- Confidence: High)
