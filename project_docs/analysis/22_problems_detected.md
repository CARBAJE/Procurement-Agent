# Detected Problems

Sources: doc surveys (4 areas), targeted code verification (10 topic rounds), CLAUDE.md.
Confidence levels reflect evidence quality.

---

## 1. Documentation vs Implementation Contradictions

Each row shows what a document claims versus what the code actually does. Severity: **Critical** (will cause failures), **High** (will mislead engineers), **Medium** (causes confusion), **Low** (cosmetic).

### 1.1 catalog-normalizer README — LLM fallback backend

| | Detail |
|---|---|
| **Claim** | `services/catalog-normalizer/README.md`: OPENAI_API_KEY required for UNKNOWN payload LLM fallback; if absent, returns empty offerings. |
| **Reality** | `CatalogNormalizer/llm_fallback.py` lines 19–23 use `instructor.from_openai(OpenAI(base_url=OLLAMA_URL, api_key="ollama"))`. The SDK is an Ollama shim. `OPENAI_API_KEY` is never read. Actual env vars are `OLLAMA_URL` (default `http://localhost:11434/v1`) and `NORMALIZER_MODEL` (default `qwen3:1.7b`). |
| **Severity** | Critical — engineers will set `OPENAI_API_KEY` and be confused when the service still fails to call UNKNOWN catalog fallback after adding it. |
| **Action** | Replace OPENAI_API_KEY entry in the README with OLLAMA_URL and NORMALIZER_MODEL. Remove any reference to OpenAI. |

(Source: CatalogNormalizer/llm_fallback.py -- Confidence: High)

### 1.2 docker-compose.yml COMPLEX_MODEL — complexity routing silently disabled

| | Detail |
|---|---|
| **Claim** | `CLAUDE.md` architecture section: "LLM intent classification (qwen3:8b) → BecknIntent extraction (qwen3:8b/1.7b routed by complexity)". `IntentParser/config.py` line 9 defaults `COMPLEX_MODEL` to `qwen3:8b`. |
| **Reality** | `docker-compose.yml` lines 14–15 set both `COMPLEX_MODEL=qwen3:1.7b` and `SIMPLE_MODEL=qwen3:1.7b` for the `intention-parser` container. The complexity-routing branch in `IntentParser/orchestrator.py` line 87 (`COMPLEX_MODEL if _is_complex(query) else SIMPLE_MODEL`) always resolves to `qwen3:1.7b`. The larger model is never invoked from Docker. |
| **Severity** | High — engineers debugging quality regressions on complex queries will look at the wrong model. The DockerCompose override is not documented or commented. |
| **Action** | Add a comment in docker-compose.yml explaining the deliberate downgrade (likely resource/memory constraint). Add a note in CLAUDE.md that the Docker deployment collapses to qwen3:1.7b for all query tiers. |

(Source: IntentParser/config.py line 9, docker-compose.yml lines 14–15 -- Confidence: High)

### 1.3 Database ENUM types — spec-era model names only

| | Detail |
|---|---|
| **Claim** | `implementation_deviations.md` states embedding models were replaced with `all-MiniLM-L6-v2` and `BAAI/bge-small-en-v1.5`. |
| **Reality** | `database/sql/00_extensions_and_types.sql` lines 144–147: `embedding_model_type` ENUM contains only `text-embedding-3-large` and `e5-large-v2`. `all-MiniLM-L6-v2` and `BAAI/bge-small-en-v1.5` are absent. `database/sql/15_agent_memory_vectors.sql` line 16 declares `embedding_model embedding_model_type NOT NULL DEFAULT 'text-embedding-3-large'`. Any INSERT using the actual deployed model names will fail with a PostgreSQL invalid enum value error unless migration `22_agent_memory_vector_dim.sql` has been applied. Similarly, `ai_provider_type` ENUM (lines 157–159) has only `openai` and `anthropic`; `ollama` is missing. |
| **Severity** | Critical — a fresh schema install followed by any agent memory write will produce a DB constraint error until migration 22 is applied. The default value in migration 15 still writes the wrong model name even after migration 22 adds the new ENUM values. |
| **Action** | (1) Add `all-MiniLM-L6-v2` and `BAAI/bge-small-en-v1.5` to `embedding_model_type` in `00_extensions_and_types.sql` base definition. (2) Change `DEFAULT 'text-embedding-3-large'` in `15_agent_memory_vectors.sql` to `DEFAULT 'all-MiniLM-L6-v2'`. (3) Add `ollama` to `ai_provider_type`. (4) Update migration 22 to also change the DEFAULT on the column. |

(Source: database/sql/00_extensions_and_types.sql, database/sql/15_agent_memory_vectors.sql -- Confidence: High)

### 1.4 frontend/CLAUDE.md — auth stub claim is false

| | Detail |
|---|---|
| **Claim** | `frontend/CLAUDE.md` Stack table, Auth row: "stub credentials dev / Keycloak OIDC prod". Phase 1 test guide documents login as `priya@example.com / password123`. |
| **Reality** | `frontend/src/lib/auth.ts` lines 1–17: Only `KeycloakProvider` is imported and configured. No `CredentialsProvider` exists at any environment. All three env vars (`KEYCLOAK_CLIENT_ID`, `KEYCLOAK_CLIENT_SECRET`, `KEYCLOAK_ISSUER`) use the non-null assertion operator and throw at runtime if absent. The Phase 1 credentials belong to the old `Bap-1` monolith frontend, not the Next.js app. The actual configured provider is Phase Two (`phasetwo.io`) hosted Keycloak at `euc1.auth.ac/auth/realms/procurement-agent`. |
| **Severity** | High — a developer will spend time looking for stub credentials that do not exist and will be unable to log in to the frontend without access to the Phase Two tenant. |
| **Action** | Correct `frontend/CLAUDE.md` auth row to "Phase Two hosted Keycloak (phasetwo.io) — OIDC — required in all environments including local dev". Add minimal Keycloak/Phase Two setup steps to `frontend/README.md`. |

(Source: frontend/src/lib/auth.ts lines 1–17, frontend/.env.local lines 22–23 -- Confidence: High)

### 1.5 CLAUDE.md service port map — three incorrect entries

| | Detail |
|---|---|
| **Claim** | `CLAUDE.md` layout section lists `frontend_demo_gateway :8005`, `discovery_engine :8006`, `negotiation_engine :8004` alongside their conflicting services. |
| **Reality** | (1) `frontend_demo_gateway` (demo-gateway) runs on container port 8015 and host port 8015 per docker-compose.yml lines 504–508, not 8005. Port 8005 is correctly assigned to catalog-normalizer. (2) `discovery_engine` claims port 8006 in its own README and config.py, which conflicts with data-normalizer's production port 8006 — but discovery_engine has no docker-compose.yml entry and is never called, so there is no runtime conflict; the CLAUDE.md listing it at :8006 is therefore misleading without that context. (3) Both orchestrator and negotiation_engine container bind port 8004; docker-compose resolves this by mapping negotiation-engine to host port 18004 (line 455), not 8004. |
| **Severity** | Medium — confuses engineers reading the port map, especially when debugging connectivity issues. |
| **Action** | Update CLAUDE.md layout section: demo-gateway :8015 (not :8005), add "(host: 18004)" annotation to negotiation_engine, mark discovery_engine as "(orphaned — no docker-compose entry)". |

(Source: docker-compose.yml lines 455, 504–508 -- Confidence: High)

### 1.6 claude_openai_proxy — completely absent from CLAUDE.md

| | Detail |
|---|---|
| **Claim** | CLAUDE.md lists all services; negotiation-engine and demo-gateway docs reference an LLM backend at `:8012`. The source of :8012 is not documented anywhere in CLAUDE.md or docker-compose.yml commentary. |
| **Reality** | `services/claude_openai_proxy/` is a full FastAPI service that translates OpenAI-compatible API calls to local `claude` CLI invocations (one-shot, non-interactive). It binds loopback `127.0.0.1:8012`. `docker-compose.yml` lines 467 and 517 reference it via `host.docker.internal:8012` for negotiation-engine and demo-gateway, but the service itself has no docker-compose entry and is intentionally not containerized (requires host-installed `claude` binary and `~/.claude/.credentials.json`). A `systemd` unit file (`services/claude_openai_proxy/claude-proxy.service`) manages it on Linux hosts. |
| **Severity** | High — engineers running the negotiation or demo flows will get connection refused at :8012 with no clue what should be running there. |
| **Action** | Add `claude_openai_proxy` to CLAUDE.md with its local startup command (`uvicorn services.claude_openai_proxy.main:app --host 127.0.0.1 --port 8012`) and the prerequisite that the `claude` CLI must be authenticated. Reference the systemd unit for persistent operation. |

(Source: services/claude_openai_proxy/README.md, docker-compose.yml lines 467, 517 -- Confidence: High)

### 1.7 IntentParser README — VALIDATED_THRESHOLD listed as env-configurable but hardcoded

| | Detail |
|---|---|
| **Claim** | `IntentParser/README.md` configuration table lists `VALIDATED_THRESHOLD` (0.85) and `AMBIGUOUS_THRESHOLD` (0.45) as environment variables. |
| **Reality** | Both thresholds are hardcoded constants in `IntentParser/core/validator.py`. They do not read from `os.getenv()` or from `IntentParser/config.py`. Setting these env vars has no effect. |
| **Severity** | Medium — operators trying to tune thresholds via environment will see no effect. |
| **Action** | Either wire the thresholds to env vars in `config.py` and read them in validator.py, or remove the rows from the README configuration table and mark them as hardcoded constants. |

(Source: IntentParser/README.md configuration table -- Confidence: High per survey note)

### 1.8 KnowledgeBase data_dictionary_er_model.md — stale VECTOR dimension

| | Detail |
|---|---|
| **Claim** | `KnowledgeBase/project_scaffold/data_dictionary_er_model.md` documents `AgentMemoryVector` with `VECTOR(3072)` and `text-embedding-3-large` or `e5-large-v2`. |
| **Reality** | As-built: `vector(384)` with `BAAI/bge-small-en-v1.5` (fastembed ONNX). Migration `22_agent_memory_vector_dim.sql` corrected the dimension from 3072 to 384. |
| **Severity** | Low — KnowledgeBase is supplementary documentation; engineers building against the actual DB will see the correct schema. However it will cause confusion during onboarding. |
| **Action** | Update the ER model entry for `agent_memory_vectors` in `data_dictionary_er_model.md` to reflect the as-built values. |

(Source: KnowledgeBase/project_scaffold/implementation_deviations.md, database/sql/22_agent_memory_vector_dim.sql -- Confidence: High)

### 1.9 Audit 'negotiate' event type — never written despite being in ENUM

| | Detail |
|---|---|
| **Claim** | `services/orchestrator/src/workflow.py` line 1047 docstring and the Phase 3 audit trail test guide both list `negotiate` as one of the 9 valid `audit_event_type` enum values and imply it is written during negotiation. |
| **Reality** | `_run_autonomous_negotiation()` (workflow.py lines 602–749) contains zero calls to `_persist_audit`. Negotiation outcomes are appended only to `result['messages']` (lines 3476–3492). The `negotiate` enum value is effectively unused in the orchestrator. `erp_sync` and `notification` event types are likewise not written by the orchestrator; they are presumably owned by erp-adapter and notification-dispatcher respectively. |
| **Severity** | High — SOX 404 and GDPR compliance require the complete decision chain in the audit trail. An auditor reconstructing a confirmed order will find no trace of the negotiation step. |
| **Action** | Add `_persist_audit` calls at the start of each negotiation round, at counter-offer generation, and at negotiation finalization (accepted/rejected/escalated) in `_run_autonomous_negotiation`. |

(Source: services/orchestrator/src/workflow.py lines 602–749, 1047 -- Confidence: High)

### 1.10 demo-gateway default port mismatch

| | Detail |
|---|---|
| **Claim** | `services/frontend_demo_gateway/README.md` line 83 states the service starts with `uvicorn ... --port 8005`. |
| **Reality** | `docker-compose.yml` lines 504–508 deploy demo-gateway on container port 8015 and host port 8015. `services/orchestrator/src/workflow.py` line 55 defaults `DEMO_GATEWAY_URL` to `http://localhost:8015`. Autonomous negotiation initiated from a locally-run orchestrator (outside Docker) will fail to reach demo-gateway unless `DEMO_GATEWAY_URL` is explicitly overridden, because the default in workflow.py is 8015 but a dev running demo-gateway standalone per its README will start it on 8005. |
| **Severity** | Medium — developers running services individually will hit connection errors. |
| **Action** | Align the `--port` argument in the demo-gateway README to 8015, matching docker-compose.yml and the orchestrator default. |

(Source: services/frontend_demo_gateway/README.md line 83, docker-compose.yml line 508, services/orchestrator/src/workflow.py line 55 -- Confidence: High)

---

## 2. Dead Code

Items confirmed or strongly indicated to be unreachable or non-functional.

| Item | Location | Evidence | Severity |
|---|---|---|---|
| `AuthGuard.tsx` | `frontend/src/app/auth/AuthGuard.tsx` | Documented in `frontend/CLAUDE.md` Known Issues as dead code, "not imported anywhere". | Low |
| Geist font registration | `frontend/src/app/fonts/` | Fonts present but not registered in layout; body falls back to Arial. Documented in CLAUDE.md Known Issues. | Low |
| `services/discovery_engine/` | Full service directory | Complete production-quality implementation with coordinator, circuit breaker, deduplication, and tests. No entry in docker-compose.yml. No import in any other service. No DISCOVERY_ENGINE_URL in orchestrator env block. Status: orphaned. (Inferred — not formally declared dead by any document.) | High — if engineer attempts to extend multi-network search they may accidentally start from this orphaned path |
| `services/frontend_demo_gateway/mock_negotiate.py` | `services/frontend_demo_gateway/mock_negotiate.py` | README explicitly states "mock_negotiate.py is legacy superseded by live_negotiate.py; do not add new code to mock_negotiate.py". | Low |
| `IntentParser/recovery.py` stubs | `IntentParser/recovery.py` lines 107–130 | Module docstring states all three functions are async stubs that only log intent. `log_unmet_demand`, `notify_buyer_no_stock`, `trigger_open_rfq_flow` — none write to DB or call any external service. No owner assigned, no completion plan. | Medium — recovery flow fails silently; buyers are never notified and RFQ is never triggered |
| `Bap-1/mock_onix.py` | `Bap-1/mock_onix.py` | Documented in Bap-1/CLAUDE.md as "legacy mock; only for unit tests (aioresponses); not for local dev". Functionality overlaps with aioresponses fixtures in tests/conftest.py. | Low |

---

## 3. Incomplete Features

Features with a schema, stub, or placeholder but no working implementation.

### 3.1 mTLS to SAP/Oracle ERP

- **Status:** SSL context hook wired in `services/erp-adapter/` but not activated.
- **Impact:** ERP traffic to SAP S/4HANA and Oracle ERP Cloud is not mutually authenticated. Not blocking for dev/staging where `ERP_VENDORS=mock`, but will block production SAP/Oracle integration.
- **Deferred to:** Phase 4.

(Source: KnowledgeBase/project_scaffold/implementation_deviations.md -- Confidence: High)

### 3.2 ERP cancel_po — NotImplementedError on production adapters

- **Status:** `SAPS4HanaAdapter.cancel_po` and `OracleERPCloudAdapter.cancel_po` raise `NotImplementedError`. The `MockERPAdapter` provides a stub implementation.
- **Impact:** Any cancellation flow that reaches `erp-adapter` with `ERP_VENDORS=sap` or `oracle` will throw a 500 and fail to cancel the PO in the ERP system.
- **Deferred to:** No documented timeline.

(Source: services/erp-adapter/README.md ERPAdapter Protocol section -- Confidence: High)

### 3.3 Splunk / ServiceNow SIEM export

- **Status:** `audit_trail_events.splunk_indexed` boolean column exists. Index `idx_audit_splunk` (partial, `WHERE splunk_indexed = FALSE`) is defined. No Splunk sink or ServiceNow consumer exists anywhere in the codebase.
- **Impact:** SOX 404 audit requirement to push events to SIEM is unmet. The `splunk_indexed` flag is never set to TRUE; all rows remain `splunk_indexed = FALSE` indefinitely.
- **Deferred to:** Phase 4.

(Source: database/sql/17_indexes.sql, database/sql/14_audit_trail_events.sql -- Confidence: High)

### 3.4 Retention enforcement job

- **Status:** `audit_trail_events.retention_until = event_timestamp + 7 years` is correctly computed on every INSERT. No nightly DELETE or archival job exists.
- **Impact:** Data retention compliance depends on a job that has never been implemented. Records will accumulate indefinitely past their retention window.
- **Deferred to:** Phase 4.

(Source: KnowledgeBase/project_scaffold/implementation_deviations.md -- Confidence: High)

### 3.5 LangSmith tracing

- **Status:** `audit_trail_events.reasoning_payload` (JSONB) captures LLM reasoning at every pipeline step. No LangSmith SDK calls exist anywhere in the codebase.
- **Impact:** Per-call LLM tracing is unavailable. `model_governance_records` schema exists but the weekly evaluation pipeline that would write to it via GitHub Actions is not implemented.
- **Deferred to:** Phase 4.

(Source: KnowledgeBase/project_scaffold/implementation_deviations.md -- Confidence: High)

### 3.6 Bap-1 session persistence (PostgresBackend)

- **Status:** `StateBackend` Protocol defined in `Bap-1/src/agent/session.py` lines 37–43 with `put`/`get`/`delete`/`sweep` methods. Only `InMemoryBackend` is implemented. Module docstring explicitly flags this as TODO(persistence).
- **Impact:** All Bap-1 sessions are lost on process restart. The 30-minute TTL and in-memory dictionaries in `services/orchestrator/src/workflow.py` (lines 98–123) have the same limitation.
- **Owner:** Documented in `Bap-1/docs/ARCHITECTURE.md §7.2 #6` as a teammate deliverable.

(Source: Bap-1/src/agent/session.py lines 9–13, Bap-1/docs/ARCHITECTURE.md §7.2 -- Confidence: High)

### 3.7 Bap-1 comparison engine (multi-criterion scoring)

- **Status:** `nodes.py::rank_and_select` uses `min(price)` heuristic. TODO(comparison-engine) marker present. `services/comparative-scoring` has the Phase 2 RankNet adapter but `Bap-1/src/agent/nodes.py` is not wired to it.
- **Impact:** Bap-1 `/compare` always returns cheapest item regardless of delivery time, rating, or negotiation history.
- **Owner:** Documented in `Bap-1/docs/ARCHITECTURE.md §7.2 #7` as a teammate deliverable.

(Source: Bap-1/CLAUDE.md, Bap-1/docs/ARCHITECTURE.md §7.2 -- Confidence: High)

### 3.8 Bap-1 approval workflow

- **Status:** TODO(approval-workflow) in `Bap-1/src/server.py::commit` and `frontend/src/components/procurement/ConfirmCommitDialog.tsx`. No approval gate exists before Bap-1 `/commit`.
- **Owner:** Documented in `Bap-1/docs/ARCHITECTURE.md §7.3 #10` as a teammate deliverable.

(Source: Bap-1/CLAUDE.md, Bap-1/docs/ARCHITECTURE.md §7.3 -- Confidence: High)

### 3.9 Bap-1 real-time WebSocket

- **Status:** `Bap-1/src/server.py::status` and `frontend/src/components/StatusPoller.tsx` use 30-second HTTP polling. TODO(realtime-ws) marker present.
- **Owner:** Documented in `Bap-1/docs/ARCHITECTURE.md §7.4 #11` as a teammate deliverable.

(Source: Bap-1/CLAUDE.md, Bap-1/docs/ARCHITECTURE.md §7.4 -- Confidence: High)

### 3.10 discovery_engine multi-network fan-out (orphaned integration)

- **Status:** `services/discovery_engine/` contains a complete `MultiNetworkCoordinator` (fan-out, deduplication, circuit breakers per network). It is not deployed in docker-compose.yml, not called by orchestrator, and not imported by beckn-bap-client. The single-gateway discovery inside beckn-bap-client is the only operational discovery path.
- **Impact:** Multi-network Beckn search (searching multiple registries concurrently) is impossible with the current deployed stack despite having an implementation.
- **Deferred to:** No documented timeline. The service appears to be a Phase 3 deliverable that was implemented but never plumbed in.

(Source: services/discovery_engine/README.md, docker-compose.yml, services/orchestrator/src/workflow.py lines 131–134 -- Confidence: High)

### 3.11 Kafka offset tracking in audit trail

- **Status:** `audit_trail_events.kafka_offset BIGINT` column exists. `services/orchestrator/src/workflow.py` line 1054 hardcodes `kafka_offset=0` with comment "TODO(kafka): real offset when topic is wired". Kafka IS deployed in docker-compose.yml (apache/kafka:latest), but audit events are written directly to PostgreSQL without going through Kafka, so no real offset is ever available.
- **Impact:** The `kafka_offset` column is always 0, making the Kafka-based replay and compliance audit-log architecture described in KnowledgeBase/integrations/audit_splunk_servicenow.md non-functional.

(Source: services/orchestrator/src/workflow.py line 1054, docker-compose.yml -- Confidence: High)

### 3.12 Keycloak / Phase Two realm setup documentation

- **Status:** `frontend/src/lib/auth.ts` requires a live Phase Two (phasetwo.io) Keycloak OIDC tenant with realm `procurement-agent`, confidential client `procurement-frontend`, realm roles mapper configured to add roles to the ID token, and user accounts with `admin`/`approver`/`requester` roles. No setup guide, no realm export file, and no user provisioning instructions exist anywhere in the repository.
- **Impact:** Developers cloning the repo cannot run the frontend at all. `frontend/.env.local` (git-ignored but present in the working tree) contains the working credentials for the dev tenant, which is a credentials exposure risk if accidentally committed.

(Source: frontend/src/lib/auth.ts lines 1–17, frontend/.env.local -- Confidence: High)

---

## 4. Unclear Architectural Decisions

Situations where the reason for a structural choice is undocumented, creating maintenance risk.

### 4.1 mcp-sidecar runs locally instead of Dockerized

`services/mcp-sidecar/README.md` explicitly states the service "runs locally, not in Docker". The technical reason is that `REDIS_URL` and `REDIS_RESULT_TIMEOUT` are read via `os.getenv()` (not pydantic-settings) in `bap_client.py` and must be real environment variables, not just entries in `.env`. However, this is a weak justification since Docker can inject real env vars. No ADR or comment documents the decision.

The practical consequence is that `mcp-sidecar` is the only service in the IntentParser Stage 3 path that requires manual startup outside `docker compose up`. This creates a two-class startup sequence that is not obvious from CLAUDE.md.

### 4.2 Bap-1/ directory continued existence

`Bap-1/` is documented in the memory files as "documentation only" with service code living in `services/`. However, `Bap-1/` contains a runnable FastAPI server (`Bap-1/src/server.py` on port 8000), 129 passing tests, and its own CLAUDE.md. The relationship between `Bap-1/src/server.py` (port 8000) and `services/orchestrator/src/workflow.py` (also port 8000/8004 per docker-compose) is not documented. Engineers may be uncertain which codebase to extend for a new feature.

### 4.3 DataNormalizer/ root package vs services/data-normalizer/ service

`DataNormalizer/` is a Python package at the repo root containing all repository logic (repositories, normalizer facade, Pydantic models). `services/data-normalizer/` is a thin HTTP adapter (handler.py only) that imports from `DataNormalizer/` via a Docker bind-mount (`./DataNormalizer:/app/DataNormalizer`). The split is logical but not documented in CLAUDE.md or the service README. The same pattern applies to `CatalogNormalizer/` and `services/catalog-normalizer/`, and to `shared/` used by multiple services. Engineers adding a new endpoint must know to write logic in `DataNormalizer/` (not in `services/data-normalizer/src/handler.py`) to keep unit-testable and DB-layer code separate from the HTTP layer.

### 4.4 Orchestrator autonomous negotiation routes through demo-gateway

`services/orchestrator/src/workflow.py::_run_autonomous_negotiation` (lines 602–749) calls `DEMO_GATEWAY_URL` (default: `http://localhost:8015`), which is `services/frontend_demo_gateway/`. The demo-gateway then calls `negotiation-engine:8004`. This means the production negotiation path goes: orchestrator → demo-gateway → negotiation_engine → Redis, introducing a service hop that exists for demo/frontend reasons. There is no direct orchestrator → negotiation_engine path. No architectural diagram or ADR explains this routing choice.

### 4.5 Two migration files share the "22_" prefix

`database/sql/22_agent_memory_vector_dim.sql` and `database/sql/22_pending_approval_columns.sql` both use the `22_` numeric prefix. `database/setup_database.py` sorts and executes files in lexicographic order. On POSIX systems `22_agent_memory_vector_dim.sql` sorts before `22_pending_approval_columns.sql` (alphabetic order of the suffix). On some filesystems the sort is case-sensitive or locale-dependent. The database README documents this as "22a/22b" to clarify intent but the filenames on disk do not reflect this. If the order matters (the two files are independent, so it currently does not), the ambiguity will eventually cause an issue. This should be resolved by renaming one file to `22b_` or `23_`.

### 4.6 docs/ARCHITECTURE.md missing from repo root

`Bap-1/CLAUDE.md` references `Bap-1/docs/ARCHITECTURE.md §7` — that file exists and is correct. However the reference path in the CLAUDE.md text is written without the `Bap-1/` prefix in some contexts, which causes confusion about whether a repo-root `docs/ARCHITECTURE.md` should exist. A repo-root `docs/ARCHITECTURE.md` does not exist. Engineers following the reference must know to look in `Bap-1/docs/`, not `docs/`.

---

## 5. Missing Test Coverage

### 5.1 Services with zero test coverage

| Service | Port | Test status |
|---|---|---|
| catalog-normalizer | 8005 | No `tests/` directory. Zero pytest-discoverable tests. |
| analytics | 8009 | No `tests/` directory. Zero pytest-discoverable tests. |
| beckn-bap-client | 8002 | No `tests/` directory. Zero pytest-discoverable tests. |
| mcp-sidecar | 3000 | No `tests/` directory. Zero pytest-discoverable tests. |
| intention-parser (Docker wrapper) | 8001 | No `tests/` directory. Thin wrapper of IntentParser/ which has tests, but the HTTP handler is untested. |
| erp-mock | 8008 | No `tests/` directory. Zero pytest-discoverable tests. |
| erp-adapter | 8007 | `tests/test_contracts.py` is a standalone Python script (`if __name__ == '__main__':`). Not discoverable by pytest without a wrapper. Six smoke tests are documented in the README but use curl commands, not pytest. |

(Source: services/*/tests/ glob, surveys -- Confidence: High)

### 5.2 Frontend — zero tests of any kind

`frontend/` has no Jest, Vitest, or Playwright configuration. There are no `*.test.ts`, `*.spec.ts`, or `e2e/` files. This is explicitly acknowledged in `frontend/README.md` and `frontend/CLAUDE.md` Known Issues sections. The 11 page routes, 24 API routes, wizard session state, and auth flow have no automated coverage.

(Source: frontend/README.md Known Issues, frontend/CLAUDE.md Known Issues -- Confidence: High)

### 5.3 Integration and E2E test gaps

The Phase 2 microservices integration test guide in `KnowledgeBase/project_scaffold/tests/phase2/phase2_microservices.md` is entirely curl-based, not an automated test suite. No pytest integration test covers the full orchestrator → intention-parser → beckn-bap-client → onix → sim-bpp → catalog-normalizer → comparative-scoring → data-normalizer pipeline in a single automated run. The only full-pipeline pytest test is `services/data-normalizer/tests/test_full_pipeline.py`, which covers the data persistence layer only, using a test DB with mocked upstream services.

### 5.4 Circuit breaker state transition tests

`services/erp-adapter/` uses `pybreaker` per-vendor circuit breakers (`BREAKER_FAIL_MAX=5`, `BREAKER_RESET_TIMEOUT_SECS=60`). `services/discovery_engine/` implements its own asyncio circuit breaker. Neither has automated tests covering the CLOSED → OPEN → HALF-OPEN → CLOSED transition sequence under simulated consecutive failures. The erp-adapter smoke tests in `tests/test_contracts.py` do not simulate circuit breaker state transitions.

### 5.5 LangGraph negotiation edge cases

`services/negotiation_engine/tests/test_async_flow.py` covers 6 async scenarios and `test_guardrails.py` covers 16 unit cases. The following paths lack test coverage:
- `max_rounds` exhaustion followed by buyer concession
- `evaluate_ambiguous_terms` branch (advisory-only categories like `it_equipment`)
- `timeout_handler` node (Redis REDIS_RESULT_TIMEOUT expiry with no on_select callback)
- AsyncPostgresSaver checkpoint persistence across process restart

### 5.6 Memory retrieval latency SLA

`services/data-normalizer/tests/test_memory_performance.py` contains a `test_search_latency_p99_under_100ms` test tagged `@pytest.mark.integration`. This test requires a live PostgreSQL with 20 seeded records and is not part of any CI pipeline. The P99 < 100ms SLA documented in CLAUDE.md and Phase 3 acceptance criteria is therefore never automatically verified.

---

## Summary Table

| # | Category | Count | Highest Severity |
|---|---|---|---|
| 1 | Doc vs Implementation | 10 | Critical (3 items) |
| 2 | Dead code | 6 | High (1 item) |
| 3 | Incomplete features | 12 | High (6 items) |
| 4 | Unclear architecture | 6 | Medium |
| 5 | Missing tests | 6 | High (2 items) |
| 6 | Resolved (Phase 4) | 4 | Critical (2 items) |

---

## 6. Resolved in Phase 4

Issues identified during earlier analysis that were fixed as part of Phase 4
delivery. Kept here for traceability; these are no longer open problems.

### 6.1 [FIXED] Invalid enum values in order_repo.py causing silent DB failures

| | Detail |
|---|---|
| **Root cause** | `DataNormalizer/repositories/order_repo.py` wrote `negotiation_strategy_type = "negotiated"` and `acceptance_status_type = "agreed"`. Neither is a valid member of the respective PostgreSQL ENUM types. |
| **Impact** | Every negotiated order produced a silent constraint error. The `negotiation_outcomes` row was never written, so `initial_price` and `final_price` were always equal and all savings metrics showed zero. |
| **Fix** | `"negotiated"` → `"accept_margin"` (negotiated path) / `"skipped"` (no-negotiation path); `"agreed"` → `"accepted"` (negotiated) / `"skipped"` (no-negotiation). |
| **File** | `DataNormalizer/repositories/order_repo.py` |
| **Severity (before fix)** | Critical |

(Source: DataNormalizer/repositories/order_repo.py — Confidence: High)

### 6.2 [FIXED] original_price not forwarded by orchestrator

| | Detail |
|---|---|
| **Root cause** | Neither the autonomous run flow nor the HITL `decide_run` flow passed `original_price` (catalog list price before negotiation) to `_persist_order_record()`. The field defaulted to `None`, collapsing into the final negotiated price. |
| **Impact** | `negotiation_outcomes.initial_price` always equalled `final_price`, making calculated savings always 0 even when negotiation achieved a real discount. |
| **Fix** | Both call sites in `services/orchestrator/src/workflow.py` now pass `original_price`; `data-normalizer POST /normalize/order` was updated to accept and forward the field to `order_repo.py`. |
| **File** | `services/orchestrator/src/workflow.py` (two call sites); `services/data-normalizer/src/handler.py` |
| **Severity (before fix)** | Critical |

(Source: services/orchestrator/src/workflow.py — Confidence: High)

### 6.3 [FIXED] Cancel button bypassing navigation guard

| | Detail |
|---|---|
| **Root cause** | The Cancel button in `RunView` called `router.push("/request/new")` directly, bypassing the `useNavigationGuard` hook that is supposed to intercept navigation away from an active procurement session. |
| **Impact** | Users could abandon active procurement requests without receiving the cancellation confirmation dialog or triggering the `/cancel` API call. Procurement requests would remain in an open state in the database. |
| **Fix** | `useNavigationGuard` was extended with a `triggerLeave(href)` method. The Cancel button now calls `triggerLeave("/request/new")` when the guard is active, which invokes the confirmation dialog before proceeding. |
| **File** | `frontend/src/components/procurement/RunView.tsx`; `frontend/src/hooks/useNavigationGuard.ts` |
| **Severity (before fix)** | High |

(Source: frontend/src/components/procurement/RunView.tsx — Confidence: High)

### 6.4 [FIXED] Missing /explain-selection endpoint in Docker intention-parser

| | Detail |
|---|---|
| **Root cause** | `POST /explain-selection` was initially added only to the local FastAPI service (`IntentParser/api.py`). The Docker `intention-parser` container runs a separate entry point (`services/intention-parser/src/handler.py`) that wraps Stages 1+2 only and did not include the new endpoint. |
| **Impact** | All frontend requests to `/explain-selection` returned HTTP 404 from the Docker service, which the Next.js API route translated to a 502. The `SelectionExplanationCard` always showed the error fallback; no explanations were ever displayed. |
| **Fix** | `POST /explain-selection` handler was added to `services/intention-parser/src/handler.py` with identical implementation logic (Ollama `qwen3:1.7b`, temperature 0.3, `<think>` stripping, empty-string fallback on error). The container was rebuilt and redeployed. |
| **File** | `services/intention-parser/src/handler.py` |
| **Severity (before fix)** | High |

(Source: services/intention-parser/src/handler.py — Confidence: High)
