# Project History

## 1. Repository Summary

| Metric | Value |
|---|---|
| Total commits (all branches) | 137 |
| First commit | 2026-04-13 |
| Most recent commit | 2026-07-06 |
| Active development window | ~12 weeks (April–July 2026) |
| Contributors | 3 |
| Total branches (local + remote) | 22 named branches |

**Contributors by commit count (all branches):**

| Contributor | Commits | Primary focus |
|---|---|---|
| Cristian | 71 | Agent memory, audit trail, real-time tracking, catalog normalizer, data normalizer |
| Eduardo García Díaz | 40 | Beckn protocol integration, orchestrator, ERP adapter, analytics, RBAC, UI |
| CARBAJE | 26 | IntentParser, MCP sidecar, scoring/ML, negotiation engine, infra/Docker |

(Source: `git shortlog -sn --all` -- Confidence: High)

**Named branches (as of 2026-07-07):**

- `main` — stable baseline; receives phase-completion merges
- `phase1`, `phase2`, `phase3` — phase integration branches
- `BAP-1` — Phase 1 monolith prototype
- `feature/agent-framework` — LangGraph ReAct graph
- `PhaseI/feat/IntentionParserScript` — first IntentParser implementation
- `module/microservices-architecture` — initial service split
- `feature/catalog-normalizer`, `feature/data-normalizer` — per-service feature branches
- `feature/agent-memory-learning`, `feature/audit_trail_system`, `feature/real-time-tracking` — Phase 3 acceptance deliverables
- `phase3-NegotiationAgent`, `phase3multi-network_search` — Phase 3 scope branches
- `erp-integration`, `analytics-dashboard`, `keycloack`, `login`, `role-based` — enterprise feature branches
- `phase4/claude_code_proxy` — experimental Claude proxy (partially reverted; see section 3)
- `procurement-flow-refinement` — current refinement/polish (active at documentation time)

---

## 2. Phase Timeline

### Phase 1 — Foundation and Protocol Integration (Weeks 1–4, April 2026)

**Planned deliverables:**
- Beckn sandbox setup with ED25519-signed ONIX adapter
- Core API flows: `/discover`, `/select`
- NL Intent Parser (Stage 1 classification + Stage 2 BecknIntent extraction)
- LangGraph ReAct agent framework
- Frontend scaffold
- Data models

**Actual delivery:**

| Deliverable | Status | Notes |
|---|---|---|
| ONIX adapter (onix-bap/onix-bpp) | Done | Go binary, ED25519, schema validator pinned at d43ec30d |
| Core API flows (discover + select) | Done | Full discover→select→init→confirm→status in Bap-1 monolith |
| NL Intent Parser | Done | Two-stage qwen3:1.7b via Ollama + instructor; milestone test suite added |
| LangGraph ReAct agent | Done | `feature/agent-framework` branch: parse→discover→rank→select→present graph |
| Frontend scaffold | Partial | First approach committed (2026-04-20); Bap-1 frontend only; full Next.js deferred |
| Data models | Done | PostgreSQL schema (24 SQL scripts) + shared models (BecknIntent, BudgetConstraints, DiscoverOffering) |

**Key commits:**

| Date | Commit | Description |
|---|---|---|
| 2026-04-13 | `4d0772e` | First Commit (CARBAJE) |
| 2026-04-14 | `e60f215` | Beckn protocol updated to v2 (Cristian) |
| 2026-04-16 | `7f6c2d9` | IntentParser module with FastAPI service (CARBAJE) |
| 2026-04-16 | `1a46551` | BAP initial app and docs (Eduardo) |
| 2026-04-17 | `344f4c3` | Integrate IntentParser and BAP; shared model for intent (Eduardo) |
| 2026-04-20 | `0f88c96` | Add frontend first approach (CARBAJE) |
| 2026-04-20 | `58e92d2` | Procurement ReAct Agent complete (CARBAJE) |
| 2026-04-22 | `62f0222` | Add PostgreSQL schema, setup script, and tests (Eduardo) |
| 2026-04-24 | `037bcbf` | Full Beckn transaction flow: init/confirm/status with provider abstractions (Eduardo) |
| ~2026-04-28 | `a4c191b` | "Phase 1 complete" (Eduardo) |

**Key architectural decisions in Phase 1:**
- Beckn Protocol v2.0.0 chosen (not v1.x); Beckn v2.1 wire-shape discovered via live adapter probing — no public schema documentation existed for `/init`/`/confirm` Contract shape.
- All Beckn traffic routed through the ONIX Go adapter at `:8081`/`:8082` rather than direct BPP HTTP calls — establishes the non-negotiable constraint documented in CLAUDE.md.
- Schema validator pinned at ONIX commit `d43ec30d` after discovering a `$ref` resolution bug in later commits (`SignatureHeader`/`AckSignatureHeader`).
- DeDi registry bypass (`targetType: url`) adopted for all ONIX routing YAMLs — enables full Beckn lifecycle within a Docker-only environment without a live registry.

(Source: git log + KnowledgeBase/project_scaffold/milestones/phase1_foundation_protocol_integration.md -- Confidence: High)

---

### Phase 2 — Core Intelligence and Transaction Flow (Weeks 5–8, late April–May 2026)

**Planned deliverables:**
- Microservices decomposition (6-service architecture)
- Catalog Normalizer as standalone service
- Data Normalizer (central persistence layer)
- Comparative Scoring Engine (Phase 1: cheapest-wins; Phase 2 RankNet foundation)
- Orchestrator state machine
- Full procurement lifecycle in Docker Compose

**Actual delivery:**

| Deliverable | Status | Notes |
|---|---|---|
| Catalog Normalizer (:8005) | Done | 5 format variants; 17 unit tests; LLM fallback uses Ollama, not OpenAI (README bug documented) |
| Data Normalizer (:8006) | Done | 6 HTTP routes; FK chain for full order lifecycle; Phase 3 memory/audit routes added later |
| Comparative Scoring (:8003) | Done | Thin adapter to prediction-api (ML) with min-price heuristic fallback |
| MLOps stack (ComparativeAndScoreing) | Done | RankNet/SGD training pipeline, MLflow registry, NDCG@5 drift check |
| Orchestrator (:8004) | Done | 5-step state machine; compare/commit two-phase flow; 30-min session TTL |
| IntentParser async pipeline | Done | Stage 3 hybrid pgvector ANN + MCP sidecar; ADR-0001 written |
| MCP Sidecar (:3000) | Done | Never-throw contract; Redis Pub/Sub subscriber; all-MiniLM-L6-v2 ranking |
| Analytics (:8009) | Done | 3 endpoints: full dashboard, business-impact KPIs, CPO benchmark |
| ERP Adapter (:8007) | Done | Budget gate + PO push outbox + HMAC dual-secret rotation + circuit breakers |
| sim-bpp (:3002) | Done | Replaced `fidedocker/sandbox-2.0`; AND-token catalog matching; 9 providers/31 items |
| Frontend (Next.js) | Done | Phase Two Keycloak OIDC; `/compare` + `/commit` wizard; analytics dashboard |

**Key commits:**

| Date | Commit | Description |
|---|---|---|
| 2026-04-23 | — | Catalog normalizer implemented and tested (Cristian) |
| 2026-04-24 | — | Microservices architecture implemented (Cristian) |
| 2026-04-27 | — | Catalog normalizer + comparative scoring + IntentParser as microservices (Cristian) |
| 2026-04-29 | `d7fbf2f` | IntentParser async pipeline + MCP Sidecar service (CARBAJE) |
| 2026-04-29 | `22bf270` | Data normalizer (Cristian) |
| 2026-04-30 | `fb2e2d0` | **Redis Pub/Sub async Beckn discovery + ADR-0001 architecture docs** (CARBAJE) |
| 2026-05-11 | `52ee5df` | Scoring and Comparative Model (CARBAJE) |
| 2026-05-19 | `0a3376e` | Add charts and analytics microservice (Eduardo) |
| 2026-05-21 | `116839d` | Dashboard overhaul: benchmarking and accessibility (Eduardo) |
| 2026-05-22 | `7eba860` | **Add Negotiation Agent** (CARBAJE) |
| 2026-05-27 | `a465111` | **ERP adapter microservice** (Eduardo) |

**Key architectural decisions in Phase 2:**

- **ADR-0001 (Redis Pub/Sub for async Beckn discovery):** The Beckn v2.0.0 `POST /discover` returns only an ACK; the catalog arrives later via `/on_discover` webhook. The MCP sidecar needed to present a synchronous response to IntentParser. Holding the HTTP connection open blocked the asyncio event loop — a deadlock. Solution: subscribe to Redis `beckn_results:{transaction_id}` _before_ firing the discover request as `asyncio.create_task`, then await the Redis message. This is the single most consequential design decision in the codebase. (Source: `docs/architecture/decisions/0001-use-redis-pubsub-for-async-beckn-responses.md` -- Confidence: High)
- **Kafka deferral:** The spec required Kafka as the ERP and audit event bus. The team substituted a PostgreSQL outbox pattern (`erp_sync_records` table with `FOR UPDATE SKIP LOCKED`) and direct PostgreSQL inserts for audit events, with `kafka_offset` columns as placeholders. Rationale: zero additional infra; Kafka deferred to Phase 4. (Source: KnowledgeBase/project_scaffold/implementation_deviations.md -- Confidence: High)
- **sandbox-2.0 replacement with sim-bpp:** The `fidedocker/sandbox-2.0` container had a fixed catalog and was opaque to debugging. `services/sim-bpp/` was written as a Node.js replacement with hot-reloadable `catalog.json`, AND-token catalog matching (preventing false positives on stopwords), and `SIM_BPP_AUTO_ADVANCE` lifecycle progression. (Source: KnowledgeBase/project_scaffold/implementation_deviations.md + services/sim-bpp/README.md -- Confidence: High)
- **Qdrant replaced by pgvector:** The spec called for Qdrant as the vector store for agent memory and BPP catalog semantic cache. The pilot corpus was projected to stay under 100K records, making pgvector with HNSW sufficient. No additional infrastructure was needed. The agent_memory_vectors table uses vector(384) with cosine HNSW. (Source: KnowledgeBase/project_scaffold/implementation_deviations.md -- Confidence: High)
- **GPT-4o/GPT-4o-mini replaced by Ollama qwen3:** Primary: `qwen3:8b` for Stage 1 classification and complex Stage 2 extraction. Lightweight: `qwen3:1.7b` for simple Stage 2 queries. Claude Sonnet 4.6 retained only as an opt-in Stage 3 query-broadening fallback via `ANTHROPIC_API_KEY`. Note: docker-compose.yml overrides both `COMPLEX_MODEL` and `SIMPLE_MODEL` to `qwen3:1.7b`, collapsing the complexity-routing logic in the containerised deployment. (Source: IntentParser/config.py + docker-compose.yml -- Confidence: High)

---

### Phase 3 — Advanced Intelligence and Enterprise Features (Weeks 9–12, June–July 2026)

**Planned deliverables (per team assignments):**
- Negotiation Engine (CARBAJE)
- Multi-Network Search (CARBAJE)
- Agent Memory and Learning (Cristian)
- Audit Trail System (Cristian)
- Analytics Dashboard (Eduardo)
- ERP Integration (Eduardo)

**Actual delivery:**

| Deliverable | Status | Owner | Notes |
|---|---|---|---|
| Negotiation Engine (:18004) | Done | CARBAJE | LangGraph state machine; 3-layer guardrails; 5 category profiles; async Redis resume |
| demo-gateway (:8015) | Done | CARBAJE | BFF bridging orchestrator ↔ negotiation_engine ↔ SupplierAgent (Claude proxy) |
| claude_openai_proxy (:8012) | Done | CARBAJE | Loopback FastAPI wrapping `claude -p` as OpenAI-compatible endpoint |
| Multi-network discovery (discovery_engine) | Code complete, unintegrated | CARBAJE | Fan-out + circuit breakers + deduplication; absent from docker-compose.yml; no callers |
| Agent Memory and Learning | Done | Cristian | BAAI/bge-small-en-v1.5 fastembed ONNX → pgvector; write/search via data-normalizer |
| Audit Trail System | Done | Cristian | 9 ENUM event types; 20+ write sites in workflow.py; 7-year retention; frontend viewer |
| Real-time Tracking | Done | Cristian | sim-bpp auto-advance; WebSocket at `/ws/status/{txn_id}`; Kafka→notification-dispatcher |
| notification-dispatcher (:8010) | Done | Cristian | Kafka consumer; Slack Block Kit / Teams Adaptive Card / SMTP fan-out |
| Analytics dashboard | Done | Eduardo | 3 API endpoints; CPO benchmark; business-impact KPIs |
| ERP Integration | Done (Phase 2/3 overlap) | Eduardo | Committed 2026-05-27; pybreaker circuit breakers; dual HMAC rotation; 6 mock scenarios |
| RBAC + approval workflow | Done | Eduardo | Role-based execution modes (advisory/hitl/autonomous); approval decision chain in DB |
| Keycloak authentication | Done | Eduardo | Phase Two hosted Keycloak; realm: `procurement-agent`; frontend `.env.local` configured |

**Key commits:**

| Date | Commit | Description |
|---|---|---|
| 2026-06-01 | `b1e59f9` | Merge phase3-NegotiationAgent (CARBAJE) |
| 2026-06-01 | `5ae0c53` | Discovery engine, demo gateway, negotiation engine fixes (CARBAJE) |
| 2026-06-01 | `33969d7` | Switch to Phase Two Keycloak login (Eduardo) |
| 2026-06-03 | `c3043be` | Add sim-bpp; route discovery through real onix path (Eduardo) |
| 2026-06-04 | `9028952` | Serve real ML (RankNet) scoring via HTTP microservices (CARBAJE) |
| 2026-06-10 | `98ec0f5` | Add order read-side, user provisioning, and UI updates (Eduardo) |
| 2026-06-16 | `f4e3760` | Unify negotiation stack; route parsers to host GPU Ollama (CARBAJE) |
| 2026-06-19 | `9247ce0` | Humanize buyer offer; negotiate delivery date (CARBAJE) |
| 2026-06-23 | `ef26e8c` | **Claude proxy on :8012; UFW docker bridge rule** (CARBAJE) |
| 2026-06-25 | `f6ee9c7` | RBAC: role-based operating modes with approval workflow (Eduardo) |
| 2026-06-25 | `c484723` | Integrate Claude proxy for IntentParser (Cristian) |
| 2026-07-01 | `c4f3224` | **Hard-lock LLM client to Ollama; refuse :8012 proxy** (CARBAJE) |
| 2026-07-01 | `6b05f71` | Fix real-time tracking; enable Slack notifications; sim-bpp auto-advance (Cristian) |
| 2026-07-03 | `892a461` | Implement transaction memory write and RAG retrieval (Cristian) |
| 2026-07-03 | `3bb4a90` | Apply post-processing memory bonuses to ML ranking (Cristian) |
| 2026-07-06 | `fd385b2` | Complete Phase 3 audit trail read path and frontend viewer (Cristian) |
| 2026-07-06 | `432e4d8` | Complete Phase 3 memory learning acceptance criteria (Cristian) |
| 2026-07-06 | `fc5f756` | Fix advisory order page missing data and audit trail ID mismatch (Cristian) |

**Key architectural decisions in Phase 3:**

- **claude_openai_proxy and subsequent hard-lock:** On 2026-06-23, CARBAJE implemented a loopback proxy at `:8012` allowing the negotiation SupplierAgent and demo-gateway to call Claude Sonnet 4.6 via an OpenAI-compatible API (needed because the demo LangGraph Negotiation Engine uses an `openai.AsyncOpenAI` client). Two days later (2026-06-25), Cristian wired the IntentParser container to also route through `:8012`. On 2026-07-01, CARBAJE reverted this for IntentParser with commit `c4f3224` ("hard-lock LLM client to Ollama, refuse :8012 proxy"), restoring the offline-first design. The proxy remains in use for demo-gateway and negotiation-engine only. (Source: git log + services/claude_openai_proxy/README.md -- Confidence: High)
- **Negotiation flow routing:** The orchestrator's autonomous negotiation path routes through demo-gateway (`DEMO_GATEWAY_URL`, default `:8015`) rather than calling negotiation-engine directly. This means the production flow is: orchestrator → demo-gateway → negotiation_engine → Redis `beckn_on_select_results`. The orchestrator polls the demo-gateway's `/api/demo/negotiate/{thread_id}` endpoint. (Source: services/orchestrator/src/workflow.py -- Confidence: High)
- **discovery_engine left unintegrated:** `services/discovery_engine/` implements multi-network Beckn fan-out (concurrent aiohttp dispatch, per-network circuit breakers, geo-proximity deduplication at 0.5 km) but was never added to docker-compose.yml and has no callers in any other service. Its port (8006) conflicts with data-normalizer. Status: code complete, integration deferred indefinitely. (Source: docker-compose.yml + services/discovery_engine/src/coordinator.py -- Confidence: High)
- **Audit trail kafka_offset placeholder:** The `audit_trail_events` table has a `kafka_offset BIGINT` column. All 13 orchestrator write sites set this to `0` with comment `TODO(kafka): real offset when topic is wired`. The `negotiate` audit_event_type enum value exists in the schema but no call site in the orchestrator writes it — the negotiation outcome is appended to `result['messages']` but never persisted to the audit trail. (Source: services/orchestrator/src/workflow.py -- Confidence: High)

---

### Phase 4 — Hardening, Testing, and Production Readiness (Weeks 13–16)

**Status: Not started. All deliverables deferred.**

Phase 4 is defined by six simultaneous pass/fail criteria:

1. P95 agent response latency < 5 seconds under representative load
2. OWASP Top 10 pen test signed off
3. Integration test coverage >= 80%
4. Evaluation suite accuracy >= 85%
5. Helm chart deploys cleanly to target Kubernetes cluster
6. Documentation package complete

**Deferred items awaiting Phase 4:**

| Item | Notes |
|---|---|
| Kubernetes / Helm / ArgoCD | Currently: Docker Compose single host, 18 containers |
| Kafka event bus (audit + ERP + notifications) | Currently: PostgreSQL outbox + direct DB insert + `kafka_offset=0` placeholders |
| LangSmith tracing | Currently: `reasoning_payload` JSONB captures the same data; LangSmith wiring absent |
| Splunk/ServiceNow sink | Currently: `splunk_indexed=false` column exists; no exporter |
| Retention enforcement job | Currently: `retention_until = event_timestamp + 7 years` column exists; no nightly DELETE |
| CI/CD (GitHub Actions lint→test→build→Helm) | Currently: manual `docker compose up` |
| Trivy image scanning | Not configured |
| mTLS to SAP/Oracle | SSL context hook wired but not activated |
| Kong API Gateway | Not deployed; direct HTTP via Docker DNS |
| Model governance weekly eval suite | Schema exists; pipeline deferred |

(Source: KnowledgeBase/project_scaffold/implementation_deviations.md + CLAUDE.md -- Confidence: High)

---

## 3. Major Architectural Inflections

### 3.1 Qdrant → pgvector (Phase 1 / Phase 2 boundary)

**Trigger:** Spec called for a self-hosted Qdrant instance as vector store for agent memory (VECTOR(3072), `text-embedding-3-large`) and a pgvector mirror for durability.

**Decision:** Use pgvector as the sole vector store. The pilot corpus was projected to stay under 100K records, making pgvector HNSW performance sufficient. Zero additional infrastructure required.

**Impact:**
- Two tables: `bpp_catalog_semantic_cache` (migration 18) and `agent_memory_vectors` (migration 15, corrected to `vector(384)` by migration 22).
- Embedding models switched from OpenAI `text-embedding-3-large` (3072 dims) to `all-MiniLM-L6-v2` (384 dims, sentence-transformers, no external calls) for the BPP catalog cache and `BAAI/bge-small-en-v1.5` (384 dims, fastembed ONNX, ~65 MB) for agent memory.
- The `embedding_model_type` ENUM in `00_extensions_and_types.sql` still contains only `'text-embedding-3-large'` and `'e5-large-v2'` (spec-era values). Migration 22 adds `'all-MiniLM-L6-v2'` but `'BAAI/bge-small-en-v1.5'` is not in any ENUM — this is a known schema inconsistency. (Source: database/sql/22_agent_memory_vector_dim.sql + KnowledgeBase/project_scaffold/implementation_deviations.md -- Confidence: High)

### 3.2 sandbox-2.0 → sim-bpp (Phase 2)

**Trigger:** `fidedocker/sandbox-2.0` had a fixed catalog, opaque matching logic, and no lifecycle simulation.

**Decision:** Replace with `services/sim-bpp/` — a Node.js Express server with a bind-mounted `catalog.json` (hot-reload), AND-token matching (tokenize query; discard tokens matching nothing in the catalog vocabulary; require all remaining tokens to appear in item name + keywords), and configurable auto-advance lifecycle (`ACCEPTED → PACKED → SHIPPED → OUT_FOR_DELIVERY → DELIVERED` on a per-second interval).

**Impact:** The 9-provider, 31-item catalog drives all end-to-end tests and demo flows. `SIM_BPP_AUTO_ADVANCE=true` is the default in docker-compose.yml, meaning every test run progresses the order to `DELIVERED` automatically unless overridden. (Source: services/sim-bpp/README.md + commit `c3043be` -- Confidence: High)

### 3.3 Kafka deferral + PostgreSQL outbox adoption (Phase 2)

**Trigger:** Spec required Kafka as the central event bus with 7-year retention, replication factor >= 3, `acks=all`.

**Decision:** Three parallel substitutions:
- **ERP PO sync:** `erp_sync_records` table with `FOR UPDATE SKIP LOCKED` outbox worker; `kafka_offset` column is a placeholder.
- **Audit events:** Direct `INSERT INTO audit_trail_events`; `kafka_offset` column defaults to 0; `splunk_indexed=false` flag.
- **Real-time status:** Kafka `po.status.changed` topic was added in Phase 3 for the notification-dispatcher Kafka consumer. This is the one component that does use Kafka in the current deployment — but only for status fan-out, not for the primary audit or ERP sync paths.

**Impact:** The Kafka broker is present in docker-compose.yml (KRaft mode, single broker, `CLUSTER_ID=5L6g3nShT-eMCtK--X86sw`) specifically to support the notification-dispatcher and sim-bpp auto-advance Kafka producer. The orchestrator also produces to Kafka for session-level WebSocket broadcast. However, audit and ERP sync remain on the outbox/direct-insert path. (Source: KnowledgeBase/project_scaffold/implementation_deviations.md + docker-compose.yml -- Confidence: High)

### 3.4 Redis Pub/Sub introduction for async Beckn discovery (ADR-0001, Phase 2)

**Trigger:** Beckn v2.0.0 `POST /discover` returns only an ACK — the catalog arrives asynchronously via an `/on_discover` webhook. The MCP sidecar needed to return catalog results synchronously to IntentParser. The naive approach (hold HTTP connection open while awaiting the callback) blocked the asyncio event loop — a deadlock.

**Decision (ADR-0001):** Introduce a Redis Pub/Sub channel `beckn_results:{transaction_id}`. The protocol is:
1. Pre-generate the `transaction_id` UUID before any network call.
2. `SUBSCRIBE` to `beckn_results:{transaction_id}` before firing the discover request.
3. Fire `POST /discover` as `asyncio.create_task(...)` — non-blocking.
4. The `/on_discover` webhook handler calls `PUBLISH beckn_results:{transaction_id} {payload}`.
5. The subscriber (MCP sidecar) unblocks and returns the catalog.

**Impact:** Establishes the hard constraint that the MCP sidecar must never `await` the discover POST — only `asyncio.create_task(...)`. Violation reintroduces the deadlock. Also establishes that `REDIS_RESULT_TIMEOUT` (default 15 s) is the primary latency ceiling for discovery probes. `MCP_BAP_TIMEOUT` (default 3 s) governs only the HTTP fire-and-forget task, not the catalog wait. (Source: docs/architecture/decisions/0001-use-redis-pubsub-for-async-beckn-responses.md -- Confidence: High)

### 3.5 ONIX schema validator pin (Phase 1, constraint carried forward)

**Trigger:** During Phase 1 Beckn integration work, a `$ref` resolution bug was discovered in ONIX adapter commits after `d43ec30d`. The bug manifests in `SignatureHeader` and `AckSignatureHeader` — signing failures in later builds.

**Decision:** Pin the `fidedocker/onix-adapter` image to the git commit hash `d43ec30d`. This pin is enforced in `config/README.md` with an explicit warning: "Do not upgrade without an end-to-end signing test against a live network."

**Impact:** All four config YAML files reference this pinned build. Any upgrade to the ONIX adapter requires a full round-trip signing regression test before the pin can be moved. (Source: config/README.md -- Confidence: High)

### 3.6 claude_openai_proxy introduction and IntentParser reversion (Phase 3)

**Trigger:** The negotiation SupplierAgent (in demo-gateway) and the negotiation-engine needed a live LLM for natural-language counter-offers. The LangGraph code uses an `openai.AsyncOpenAI` client, which cannot natively call the Anthropic API. The local `claude` CLI supports a `-p` flag (non-interactive, stdin-fed prompt) with `--output-format stream-json`.

**Decision:** Write `services/claude_openai_proxy/` — a loopback FastAPI service that translates OpenAI-compatible `/v1/chat/completions` requests to `claude -p --no-session-persistence --output-format stream-json` subprocess invocations. Binds `127.0.0.1:8012` (or `0.0.0.0:8012` for Docker reachability via `host.docker.internal`).

**Reversion:** Cristian wired IntentParser to also route through `:8012` on 2026-06-25. CARBAJE reverted this on 2026-07-01 ("hard-lock LLM client to Ollama, refuse :8012 proxy"), restoring the offline-first design for the parsing pipeline. The proxy now serves only demo-gateway and negotiation-engine.

**Impact:** Claude Sonnet 4.6 is used for the SupplierAgent LLM role in demo flows (model mapped as `claude-3-5-sonnet` → `sonnet` in the proxy model map). `temperature`, `top_p`, and `max_tokens` are accepted but silently ignored. Each request bills the host's Anthropic account. Concurrency is capped at 2 by default. (Source: services/claude_openai_proxy/config.py + services/claude_openai_proxy/README.md + git log -- Confidence: High)

---

## 4. Recent Commit Summary

The 20 most recent commits on all branches as of 2026-07-06:

| Hash | Date | Author | Message |
|---|---|---|---|
| `fc5f756` | 2026-07-06 | Cristian | fix: resolve advisory order page missing data and audit trail ID mismatch |
| `8450964` | 2026-07-06 | Eduardo | Align docs with implemented stack |
| `a7bfba3` | 2026-07-06 | Cristian | Buttons updated |
| `29442b0` | 2026-07-06 | Cristian | feat(audit-trail): add View Audit Trail button to OrderView |
| `e31e65c` | 2026-07-06 | Cristian | fix(audit-trail): rename [id] route segment to [txn_id] to match existing siblings |
| `fd385b2` | 2026-07-06 | Cristian | feat(audit-trail): complete Phase 3 audit trail read path and frontend viewer |
| `432e4d8` | 2026-07-06 | Cristian | feat(agent-memory): complete Phase 3 memory learning acceptance criteria |
| `33062ed` | 2026-07-05 | Eduardo | Add modes and run-based procurement orchestration |
| `3bb4a90` | 2026-07-03 | Cristian | feat(memory): apply post-processing memory bonuses to ML ranking |
| `dc95150` | 2026-07-03 | Cristian | docs(phase3): add agent memory learning test guide and acceptance checklist |
| `892a461` | 2026-07-03 | Cristian | feat(agent-memory): implement transaction memory write and RAG retrieval |
| `87d08ad` | 2026-07-01 | Cristian | Updates of the documentation |
| `ee6a45d` | 2026-07-01 | Cristian | fix(real-time-tracking): fix status flow and enable Slack notifications + sim-bpp auto-advance |
| `fbaeec7` | 2026-07-01 | Cristian | fix(infra): parameterize notification-dispatcher DB creds and bridge demo-gateway to beckn_network |
| `2b6cfc1` | 2026-07-01 | CARBAJE | Merge (phase4/claude_code_proxy): hard-lock LLM client to Ollama, refuse :8012 proxy |
| `c4f3224` | 2026-07-01 | CARBAJE | fix(intent-parser): hard-lock LLM client to Ollama, refuse :8012 proxy |
| `a9ca3cd` | 2026-06-25 | Cristian | fix(intent-parser): wire intention-parser to Claude proxy and clean up stale fallbacks |
| `c484723` | 2026-06-25 | Cristian | merge(phase4/claude_code_proxy): integrate Claude API proxy for IntentParser |
| `f6ee9c7` | 2026-06-25 | Eduardo | feat(rbac): implement role-based operating modes with approval workflow |
| `d8fcf91` | 2026-06-24 | Eduardo | feat(analytics): implement business impact API and update benchmark fetching logic |

The final cluster (2026-07-03 to 2026-07-06) represents the Phase 3 acceptance criteria closure: agent memory write/search/RAG, memory bonuses applied to ML ranking scores, audit trail frontend viewer, and the `[txn_id]` routing fix that resolved a missing-data bug on the advisory order page.

(Source: `git log --oneline --all` -- Confidence: High)

---

## 5. Evolution of Key Components

### 5.1 IntentParser

**Phase 1 origin (April 2026):**
Branch `PhaseI/feat/IntentionParserScript` implemented the first parser script, translated to English and wrapped in a FastAPI service on 2026-04-16 (`7f6c2d9`). Initial design: single-stage, one LLM call, `qwen3:1.7b` via Ollama + `instructor` Mode.JSON, `max_retries=3`. Output: `ParsedIntent` only.

**Phase 1 integration (April 2026):**
On 2026-04-17 (`344f4c3`), Eduardo integrated IntentParser with the BAP monolith and created the shared model for intent (`shared/models.py`: `BecknIntent`, `BudgetConstraints`, `DiscoverOffering`). The anti-corruption layer was established: `delivery_timeline` is int hours, `location_coordinates` is `"lat,lon"` decimal, `budget_constraints` is typed not raw.

**Phase 2 pipeline extension (April 2026):**
On 2026-04-29 (`d7fbf2f`), CARBAJE committed the async pipeline with three stages:
1. Stage 1: LLM intent classification → `ParsedIntent` (qwen3:8b/1.7b complexity-routed)
2. Stage 2: BecknIntent extraction → validated `BecknIntent` struct
3. Stage 3: Hybrid pgvector ANN + MCP sidecar validation → `VALIDATED` / `AMBIGUOUS` / `CACHE_MISS` result

Stage 3 thresholds are hardcoded: VALIDATED >= 0.85, AMBIGUOUS 0.45–0.85, CACHE_MISS < 0.45. The recovery flow (`broaden_procurement_query` → retry → `log_unmet_demand` → `notify_buyer_no_stock` → `trigger_open_rfq_flow`) exists as stubs only.

**Phase 3 proxy experiment and reversion (June–July 2026):**
Cristian wired the dockerised `intention-parser` to the Claude proxy on 2026-06-25. CARBAJE reverted this on 2026-07-01 with a hard-lock to Ollama. The net result: in the Docker stack, both `COMPLEX_MODEL` and `SIMPLE_MODEL` are set to `qwen3:1.7b`, disabling complexity routing. Locally (outside Docker), `COMPLEX_MODEL` defaults to `qwen3:8b`.

(Source: git log + IntentParser/config.py + IntentParser/README.md -- Confidence: High)

### 5.2 Orchestrator

**Phase 1 — LangGraph ReAct agent (April 2026):**
`feature/agent-framework` branch. Single `ProcurementAgent` wrapping a `StateGraph` with five nodes: `parse_intent → discover → rank_and_select → send_select → present_results`. Ranking: `min(offerings, key=lambda o: float(o.price_value))`. No persistence, no ERP, no audit.

**Phase 2 — Microservice state machine (April–May 2026):**
Extracted from Bap-1 monolith into `services/orchestrator/` at `:8004`. Pipeline re-implemented as five HTTP calls to downstream microservices (intention-parser, beckn-bap-client, comparative-scoring, data-normalizer). Added the two-phase `compare` / `commit` flow with 30-minute in-memory session TTL. Added `POST /run` for single-shot autonomous execution. Persistence to data-normalizer is fire-and-forget (5-second timeout, never raises).

**Phase 3 — Enterprise features (June–July 2026):**
- Agent memory: `_persist_memory()` (fire-and-forget `asyncio.create_task`) and `_fetch_memory_context()` (5-second timeout) wired at confirm and compare respectively. Memory delta scoring formula: `0.03 × exp(-days_old × ln(2)/90)` per past PO, capped at ±0.10, max 5 orders per provider.
- Audit trail: `_persist_audit()` called at 13 sites across `run_pipeline`, `run_pipeline_from_intent`, `_compare_phase`, commit handler, status poll, seller webhook, approval decision, cancel, and the autonomous run flow. The `negotiate` audit event type exists in the schema but has zero write sites — the negotiation outcome is not persisted to the audit trail (gap).
- RBAC: `PROCUREMENT_EXECUTION_MODE` (advisory/hitl/autonomous) and three-tier approval routing (auto/manager/CFO based on `amount_total` vs user `approval_threshold`).
- ERP budget gate: `POST /api/v1/budget/check` synchronous call to erp-adapter before `/commit`. `ERP_BUDGET_CHECK_REQUIRED=false` in docker-compose.yml (fail-open default for development).
- Autonomous negotiation: `_run_autonomous_negotiation()` polls `DEMO_GATEWAY_URL` (`http://localhost:8015` default; note: demo-gateway README states port 8015, resolving the port discrepancy).

(Source: services/orchestrator/src/workflow.py + KnowledgeBase/project_scaffold/milestones/ -- Confidence: High)

### 5.3 Beckn Integration Layer

**Phase 1 — Bap-1 monolith:**
`src/beckn/` in Bap-1: `adapter.py` (UUID txn IDs, RFC 3339 timestamps, URL construction), `client.py` (aiohttp, `discover_async` + `select`/`init`/`confirm`/`status`), `callbacks.py` (`CallbackCollector` with one `asyncio.Queue` per `(transaction_id, action)`). The monolith exposes `/bpp/discover` as a six-offering mock catalog endpoint for unit tests.

During Phase 1, eight Beckn v2.1 wire-shape gotchas were discovered via live ONIX probing and are documented in `Bap-1/CLAUDE.md`: `Contract` is `additionalProperties: false`; `commitments` required everywhere; `status.code` ENUM is `DRAFT|ACTIVE|CANCELLED|COMPLETE` (not `CONFIRMED`); `performance` entries are strict; `/status` payload is `{message:{contract:{id,commitments}}}` not `{orderId:...}`; schemas are compiled in a `.so` binary.

**Phase 2 — beckn-bap-client microservice:**
Extracted and extended as `services/beckn-bap-client/` at `:8002`. Added the `/on_discover` webhook endpoint that publishes to Redis `beckn_results:{transactionId}` (ADR-0001 implementation). Dual publish-and-collect: the Redis channel serves the MCP sidecar; `CallbackCollector` serves the orchestrator. `CALLBACK_TIMEOUT` defaults to 10 seconds. The catalog normalizer call is delegated to `catalog-normalizer:8005`.

**Phase 3 — sim-bpp route through real ONIX:**
Commit `c3043be` (2026-06-03, Eduardo) replaced the direct BPP mock with the full ONIX routing path: `beckn-bap-client → onix-bap:8081 → onix-bpp:8082 → sim-bpp:3002 → onix-bpp:8082 → onix-bap:8081 → beckn-bap-client /on_discover`. This completed the end-to-end Beckn v2.0.0 protocol flow over a real (simulated) network for the first time.

(Source: Bap-1/CLAUDE.md + services/beckn-bap-client/README.md + git log -- Confidence: High)
