# Future Work

This document catalogs all identified future work: Phase 4 planned deliverables, in-code TODO markers and stubs, features explicitly deferred during Phases 1-3, and architectural improvements surfaced during code review. Entries are ordered from highest to lowest engineering impact.

---

## 1. Phase 4 Explicitly Planned (Weeks 13-16)

Phase 4 contains no new features. Its sole objective is production readiness, defined as all six acceptance criteria satisfied simultaneously: P95 agent response latency under 5 s, OWASP Top 10 pen-test signed off, integration-test coverage at or above 80 %, evaluation-suite accuracy at or above 85 %, a Helm chart that deploys cleanly to a target Kubernetes cluster, and a complete documentation package.

(Source: KnowledgeBase/project_scaffold/milestones/phase4_hardening_testing_production_readiness.md — Confidence: High)

### 1.1 Container Orchestration and CI/CD

| Item | Current state | Phase 4 target |
|---|---|---|
| Container orchestration | Docker Compose single host, 18 services | Kubernetes on EKS, AKS, or GKE with Helm parameterized chart and ArgoCD GitOps |
| CI/CD | Manual `docker compose up` | GitHub Actions pipeline: lint → test → build → Helm push |
| Image security scanning | Not configured | Trivy integrated as CI gate |
| Container images | Standard base images | Distroless hardened images |
| API gateway | Direct HTTP via Docker DNS | Kong API Gateway for rate limiting, auth, and TLS termination |
| Secret management | Plaintext env vars in docker-compose.yml | Kubernetes Secrets backed by KMS (AWS Secrets Manager or Azure Key Vault) |
| Service mesh | None | Optional: Linkerd or Istio for mTLS between pods |

(Source: KnowledgeBase/project_scaffold/implementation_deviations.md — Confidence: High)

### 1.2 Infrastructure and Event Streaming

Kafka is the most significant deferred infrastructure component. Three services have placeholder wiring that silently degrades without it:

- **notification-dispatcher** requires Kafka topic `po.status.changed` to start its consumer. When `KAFKA_BOOTSTRAP` is empty the consumer never starts and no notifications are dispatched.
- **erp-adapter** uses a PostgreSQL outbox worker as a stand-in for the Kafka PO-sync topic. The `kafka_offset` column in `erp_sync_records` is a placeholder — no real offset is ever written.
- **orchestrator** has `kafka_offset=0` hardcoded in every `_persist_audit` call with a `TODO(kafka): real offset when topic is wired` comment in `workflow.py` line 1054.

Phase 4 Kafka deliverables:
- Deploy Kafka broker in KRaft mode (already templated in `docker-compose.yml` for local testing) to the Kubernetes cluster with replication factor 3, `acks=all`, and 7-year log retention for the audit topic.
- Wire `notification-dispatcher` to the real topic.
- Replace the outbox worker in `erp-adapter` with a true Kafka producer.
- Replace the `kafka_offset=0` stub in the orchestrator with real partition + offset tracking.
- Connect `sim-bpp`'s auto-advance lifecycle events to the live Kafka topic (currently already wired but requires a running broker).

(Source: services/orchestrator/src/workflow.py, docker-compose.yml, services/erp-adapter/README.md — Confidence: High)

### 1.3 Observability

| Item | Current state | Phase 4 target |
|---|---|---|
| LLM tracing | `reasoning_payload` JSONB column in `audit_trail_events` captures all data | Wire to LangSmith for per-call cost, latency, and prompt-quality tracking |
| Metrics | No Prometheus scrape endpoints | Add `/metrics` exposition to all Python services (Prometheus format) |
| Dashboards | No Grafana dashboards | Grafana dashboards for procurement pipeline latency, scoring quality, ERP sync lag |
| Distributed tracing | No OpenTelemetry instrumentation | Add OTEL SDK to orchestrator, beckn-bap-client, and data-normalizer |
| Alerting | None | Prometheus alerting rules for P95 latency breach, ERP circuit-breaker open, ML model drift |

(Source: KnowledgeBase/project_scaffold/technologies/observability_stack.md — Confidence: High)

### 1.4 Security Hardening

| Item | Current state | Phase 4 target |
|---|---|---|
| TLS | No TLS between internal services | TLS 1.3 on all API-to-API links |
| Data at rest | Unencrypted PostgreSQL volume | AES-256 encryption with KMS-managed keys |
| Identity | Phase Two hosted Keycloak (dev tenant) | Production Keycloak or Okta/Azure AD realm with SAML 2.0 or OIDC |
| PII scrubbing | None | Strip PII from LLM prompts before send |
| Pen test | Not run | OWASP Top 10 pen test as Phase 4 gate |
| mTLS to SAP/Oracle | SSL context hook wired but not activated | Activate mTLS for on-prem SAP S/4HANA connections |
| ED25519 key material | Testnet sandbox keys in `config/` | Replace with production key pair; document KMS rotation procedure |

(Source: KnowledgeBase/project_scaffold/implementation_deviations.md, Bap-1/docs/ARCHITECTURE.md §7.3 — Confidence: High)

### 1.5 Model Governance Pipeline

The `model_governance_records` table exists in PostgreSQL (migration `16_model_governance_records.sql`) but no governance pipeline writes to it.

Phase 4 deliverables:
- Weekly evaluation suite: 100 representative procurement scenarios run automatically via GitHub Actions.
- Drift thresholds: if intent-classification accuracy falls below 85 % trigger a 48-hour prompt-review; if the user-override rate exceeds 30 % trigger a calibration review.
- LangSmith per-call tracing wired to the evaluation database for regression comparisons.

(Source: KnowledgeBase/project_scaffold/ai_models/model_governance.md — Confidence: High)

### 1.6 Compliance and Data Retention

- **Nightly retention enforcement job**: `audit_trail_events.retention_until` is set to `event_timestamp + 7 years` on every write (SOX 404, GDPR, IT Act 2000 compliance), but no job ever deletes or archives rows whose `retention_until` has passed. A scheduled Kubernetes CronJob or pg_cron task is required.
- **Splunk SIEM exporter**: `audit_trail_events.splunk_indexed` is a placeholder boolean; no exporter pushes events to Splunk or ServiceNow. A Kafka consumer that sinks audit events to Splunk is the intended Phase 4 component.
- **mTLS for SAP/Oracle webhooks**: `erp-adapter` has an SSL context hook in the `adapters/` factory but it is never activated. Activating it requires client certificates from the SAP/Oracle tenant.

(Source: KnowledgeBase/project_scaffold/integrations/audit_splunk_servicenow.md, services/erp-adapter/README.md — Confidence: High)

---

## 2. NotImplementedErrors, TODO Markers, and Stubs

### 2.1 Bap-1 Production Blockers (from `Bap-1/docs/ARCHITECTURE.md §7`)

The full 14-item list is grouped into four categories. Items marked with a TODO grep marker have searchable anchors in the source code.

**§7.1 Protocol and Network (items 1–4)**

| # | Blocker | TODO marker | Phase |
|---|---|---|---|
| 1 | `_performance_dict` in `adapter.py` omits `performanceAttributes` because the ONIX schema validator HTTP-GETs the JSON-LD `@context` URI and the URI is not published yet. Currently worked around by omitting the field entirely. | `TODO(beckn-v2.1-context)` in `Bap-1/src/beckn/adapter.py` | 3-4 |
| 2 | BAP is not registered as a DeDi registry subscriber; `targetType: url` bypass is the current workaround but blocks discovery on the real Beckn mainnet. | No grep marker | 4 |
| 3 | ED25519 keys are testnet sandbox keys; no KMS rotation or HSM signing. | No grep marker | 4 |
| 4 | Discovery shortcut: Bap-1's discovery step calls a local catalog rather than fanning out to real Beckn networks. | No grep marker | 3 |

**§7.2 Data and Business Logic (items 5–8)**

| # | Blocker | TODO marker | Phase |
|---|---|---|---|
| 5 | Bap-1 hardcoded catalog — all queries return the same 6 A4-paper items regardless of query. Assigned to a teammate. | Implicit (hardcoded fixture) | 2 |
| 6 | `TransactionSessionStore` uses `InMemoryBackend` only. `StateBackend` Protocol is defined in `Bap-1/src/agent/session.py` lines 37–43 for a `PostgresBackend` swap but the swap is not implemented. Sessions are lost on restart. | `TODO(persistence)` in `Bap-1/src/agent/session.py`, `Bap-1/src/server.py`, `frontend/src/lib/session-store.ts` | 2 |
| 7 | `rank_and_select` node in `nodes.py` uses cheapest-wins heuristic. Multi-criterion scoring (ML RankNet Phase 2 / OptNet Phase 3) not yet connected to the Bap-1 graph. | `TODO(comparison-engine)` in `Bap-1/src/agent/nodes.py::rank_and_select`, `Bap-1/src/server.py::_build_scoring` | 2 |
| 8 | Payment is hardcoded to cash-on-delivery; no payment gateway integration. | No grep marker | 3 |

**§7.3 Security and Access (items 9–10)**

| # | Blocker | TODO marker | Phase |
|---|---|---|---|
| 9 | Bap-1 stub users are hardcoded with cleartext passwords; no Keycloak SSO. The `/commit` route has no RBAC gate. | No grep marker | 4 |
| 10 | Approval workflow absent: `/commit` executes immediately without checking requester role or approval threshold. | `TODO(approval-workflow)` in `Bap-1/src/server.py::commit`, `frontend/src/components/ConfirmCommitDialog.tsx` | 2 |

**§7.4 Observability and Ops (items 11–14)**

| # | Blocker | TODO marker | Phase |
|---|---|---|---|
| 11 | Order status uses 30-second HTTP polling loop (`StatusPoller.tsx`). No WebSocket push. | `TODO(realtime-ws)` in `Bap-1/src/server.py::status`, `frontend/src/components/StatusPoller.tsx` | 2 |
| 12 | No structured audit trail from Bap-1 layer; no Kafka → Splunk sink. | No grep marker | 3 |
| 13 | No CI/CD pipeline. | No grep marker | 4 |
| 14 | LLM inference uses local Ollama; no managed LLM service, no rate limiting, no cost controls. | No grep marker | 3-4 |

(Source: Bap-1/docs/ARCHITECTURE.md §7, verified via grep — Confidence: High)

### 2.2 Orchestrator In-Memory State (services/orchestrator)

`services/orchestrator/src/workflow.py` has five module-level dictionaries that hold all orchestrator state:

```python
_sessions: dict[str, dict] = {}           # line 98
_session_times: dict[str, float] = {}     # line 99
_order_enrichments: dict[str, dict] = {}  # line 106
_pending_approvals: dict[str, dict] = {}  # line 111
_erp_state_cache: dict[str, dict] = {}    # line 117
```

All five are lost on container restart. SESSION_TTL is 1800 s (line 100) with lazy eviction only — no background sweeper. Unlike Bap-1, the orchestrator has no `StateBackend` Protocol; the switch to Redis- or PostgreSQL-backed state requires a refactor, not just a swap. There is no TODO marker for this item.

(Source: Code finding — services/orchestrator/src/workflow.py — Confidence: High)

### 2.3 Kafka Offset Stub in Audit Trail

Every call to `_persist_audit` in `workflow.py` passes `kafka_offset=0` with an inline comment: `TODO(kafka): real offset when topic is wired`. Until Kafka is deployed and the orchestrator becomes a Kafka producer, every audit event carries a meaningless offset. The `splunk_indexed` flag is never set to `True` from the orchestrator.

(Source: Code finding — services/orchestrator/src/workflow.py line 1054 — Confidence: High)

### 2.4 Negotiate Audit Event Type Never Written

`audit_event_type` ENUM contains a `negotiate` value (one of 9 valid values). However, `_run_autonomous_negotiation` in `workflow.py` contains zero calls to `_persist_audit`. Negotiation outcomes are appended only to `result['messages']` (lines 3476-3492) and are never persisted to `audit_trail_events`. The `negotiate` ENUM value is effectively unused from the orchestrator layer.

(Source: Code finding — services/orchestrator/src/workflow.py — Confidence: High)

### 2.5 IntentParser Recovery Stubs

`IntentParser/recovery.py` module docstring (lines 1–6) explicitly states: "All functions are async stubs that log intent; replace stubs with real integrations (DB logging, notification service, RFQ microservice) as infrastructure is provisioned."

Three functions are stubs:

| Function | Intended behavior | Current implementation |
|---|---|---|
| `log_unmet_demand(item, query, location)` | Write unmet demand record to PostgreSQL for procurement analytics | `logger.info("UNMET_DEMAND …")` only |
| `notify_buyer_no_stock(buyer_email, item, query)` | Send email/Slack to buyer confirming no catalog match | `logger.info("BUYER_NOTIFY …")` only |
| `trigger_open_rfq_flow(item, query, location)` | POST to an RFQ microservice to start an open request-for-quote | `logger.info("OPEN_RFQ …")` only |

No owner is assigned and no completion timeline exists in any KnowledgeBase document.

(Source: Code finding — IntentParser/recovery.py lines 107-130 — Confidence: High)

### 2.6 Demo-Gateway Default Port Mismatch

`services/orchestrator/src/workflow.py` line 55 defaults `DEMO_GATEWAY_URL` to `http://localhost:8015`. The `frontend_demo_gateway` README states the service listens on port 8005 (`uvicorn … --port 8005`). However, `docker-compose.yml` defines the `demo-gateway` service on `8015:8015` and passes `--port 8015`. The local-run default and the Docker default are inconsistent: engineers running the orchestrator locally without the env var set will fail to reach the demo gateway. The `DEMO_GATEWAY_URL` env var must always be set explicitly in local development.

(Source: Code finding — services/orchestrator/src/workflow.py line 55, services/frontend_demo_gateway/README.md, docker-compose.yml — Confidence: High)

---

## 3. Deferred Features (from `implementation_deviations.md`)

The following items were explicitly removed from scope during Phases 1-3. They are documented in `KnowledgeBase/project_scaffold/implementation_deviations.md`.

### 3.1 Vector Store Migration to Qdrant

The design spec called for Qdrant (self-hosted) as the primary vector store with a pgvector mirror for durability. The as-built system uses pgvector only.

Trigger for migration: pilot corpus exceeds approximately 100 K records, at which point HNSW in pgvector may exhibit memory pressure and index-build latency not acceptable for the P95 < 100 ms SLA. Migration path: spin up a Qdrant StatefulSet (already in the Phase 4 Kubernetes spec), run a one-time ETL from `agent_memory_vectors`, and update `DataNormalizer/repositories/memory_repo.py` to write to Qdrant instead of pgvector.

(Source: KnowledgeBase/project_scaffold/implementation_deviations.md — Confidence: High)

### 3.2 Agent Memory Nightly ETL

The design spec included a nightly PostgreSQL → Qdrant batch-sync job. Because Qdrant was not deployed, no ETL job exists. If Qdrant is introduced (see 3.1), the ETL must be implemented — likely as a Kubernetes CronJob running `fastembed` re-embedding + Qdrant upsert for all `agent_memory_vectors` rows modified since the previous run.

(Source: KnowledgeBase/project_scaffold/implementation_deviations.md — Confidence: High)

### 3.3 Database ENUM Type Inconsistencies

Two ENUM types in `database/sql/00_extensions_and_types.sql` use spec-era values that do not match the as-built deployment. These will cause `INSERT` failures if application code ever tries to store the actual values:

**`embedding_model_type`** (lines 144-147 of `00_extensions_and_types.sql`):
- Contains: `text-embedding-3-large`, `e5-large-v2`
- Actual deployed models: `all-MiniLM-L6-v2` (bpp semantic cache), `BAAI/bge-small-en-v1.5` (agent memory)
- Migration `22_agent_memory_vector_dim.sql` adds `all-MiniLM-L6-v2` via `ALTER TYPE ... ADD VALUE`, but does NOT update the column DEFAULT (still `text-embedding-3-large`) and does NOT add `BAAI/bge-small-en-v1.5`
- Fix required: add `BAAI/bge-small-en-v1.5` to the ENUM and update the `agent_memory_vectors.embedding_model` column DEFAULT to `all-MiniLM-L6-v2`

**`ai_provider_type`** (lines 157-160 of `00_extensions_and_types.sql`):
- Contains: `openai`, `anthropic`
- Actual primary provider: `ollama` (qwen3:8b, qwen3:1.7b)
- Fix required: add `ollama` value via `ALTER TYPE ... ADD VALUE`

(Source: Code finding — database/sql/00_extensions_and_types.sql, database/sql/15_agent_memory_vectors.sql, database/sql/22_agent_memory_vector_dim.sql — Confidence: High)

### 3.4 Kafka for ERP Sync

The spec called for ERP PO-push events to be published on a Kafka topic with the outbox worker as consumer. As built, the outbox worker (`erp-adapter` background task using `FOR UPDATE SKIP LOCKED`) polls `erp_sync_records` directly and calls the ERP vendor REST API. The `kafka_offset` column in `erp_sync_records` is a placeholder. Phase 4 wiring: replace the polling worker with a Kafka producer on `po.created`; introduce a separate Kafka consumer in `erp-adapter` to drive vendor API calls.

(Source: KnowledgeBase/project_scaffold/implementation_deviations.md — Confidence: High)

### 3.5 Catalog-Normalizer LLM Backend Documentation Error

`services/catalog-normalizer/README.md` incorrectly states that `OPENAI_API_KEY` is required for LLM fallback and that the service returns empty offerings if the key is absent. The actual implementation in `CatalogNormalizer/llm_fallback.py` uses Ollama (`OLLAMA_URL`, default `http://localhost:11434/v1`) with `NORMALIZER_MODEL` (default `qwen3:1.7b`). `OPENAI_API_KEY` is never read. The README must be corrected to document `OLLAMA_URL` and `NORMALIZER_MODEL` as the relevant env vars.

(Source: Code finding — CatalogNormalizer/llm_fallback.py lines 19-25 — Confidence: High)

### 3.6 Complexity-Routing Disabled in Docker Deployment

`IntentParser/config.py` defaults `COMPLEX_MODEL` to `qwen3:8b` and `SIMPLE_MODEL` to `qwen3:1.7b`. `docker-compose.yml` overrides both to `qwen3:1.7b` for the `intention-parser` service, collapsing the two-tier routing so that all queries use the lighter model inside Docker. No comment explains the rationale (likely a memory or startup-time constraint on the development host). Engineers running the full stack should be aware that the complexity-routing architecture described in CLAUDE.md and `IntentParser/README.md` is only active in local (non-Docker) deployments.

(Source: Code finding — IntentParser/config.py line 9, docker-compose.yml lines 14-15 — Confidence: High)

### 3.7 ComparativeAndScoreing Phase 2 → Phase 3 Gating

The Phase 2 RankNet/LambdaRank model (`ComparativeAndScoreing/`) should remain in production until any of the following triggers for Phase 3 OptNet/cvxpylayers:

- NDCG@5 plateaus: less than 0.5 % improvement over 3 consecutive retraining cycles
- Closed procurement records exceed 50 000 in PostgreSQL
- Procurement team requires multi-supplier split-orders (single-argmax output is structurally incompatible)
- Decision-quality gap exceeds 15 % relative regret versus oracle on holdout

Production handover from Phase 1 heuristic to Phase 2 ML requires: at least 5 000 override events in the audit trail, a trained model with NDCG@5 ≥ 0.85, and a manual operator promotion from Staging to Production in MLflow.

(Source: services/ComparativeAndScoreing/README.md — Confidence: High)

---

## 4. Architectural Improvements Worth Considering

These are not in any phase plan but were surfaced by code review as risks to reliability, scalability, or security.

### 4.1 Fire-and-Forget Async Write Failures Are Silent

The orchestrator calls `asyncio.create_task(_persist_memory(...))` and `asyncio.create_task(_persist_audit(...))` with no error propagation. If the data-normalizer is unavailable, both writes are silently dropped. The orchestrator logs a DEBUG entry but returns success to the caller. In a procurement system where audit trail completeness is a SOX 404 requirement, silent audit drops are a compliance risk. Recommendation: move audit writes to a local Redis queue with a background drain worker, mirroring the ERP outbox pattern already used in `erp-adapter`.

(Source: Code finding — services/orchestrator/src/workflow.py — Confidence: High)

### 4.2 Orchestrator Sessions Must Be Externalized for Horizontal Scaling

The orchestrator's five in-memory dictionaries (sessions, order enrichments, pending approvals, ERP state cache, run-ID index) are incompatible with more than one orchestrator replica. Any horizontal scaling attempt will result in 50 % of requests receiving stale or empty sessions. The fix is to move session storage to Redis with a TTL-aware hash pattern, matching the 1800 s TTL already used for in-memory entries. The `beckn-bap-client`'s `CallbackCollector` has the same issue — it uses per-process asyncio queues.

(Source: Code finding — services/orchestrator/src/workflow.py, services/beckn-bap-client — Confidence: High)

### 4.3 Internal Service APIs Have No Authentication

All inter-service HTTP calls inside `beckn_network` use no authentication. Any process that can reach the Docker bridge can call `POST /normalize/order`, `POST /normalize/audit`, or `GET /admin/users` without credentials. Phase 4 minimum: add a shared `INTERNAL_API_TOKEN` header validated by `data-normalizer`, `analytics`, and `erp-adapter`. Long-term: mutual TLS via service mesh.

(Source: Inferred from services/data-normalizer/README.md, services/erp-adapter/README.md — Confidence: Medium)

### 4.4 claude_openai_proxy Is a Single Point of Failure for Negotiation Demos

`demo-gateway` and `negotiation-engine` both depend on the `claude_openai_proxy` service at `host.docker.internal:8012`. This service is: not in `docker-compose.yml`, not containerized, bound to loopback by default (requires `CLAUDE_PROXY_HOST=0.0.0.0` in the systemd unit for Docker reachability), and limited to `CLAUDE_PROXY_MAX_CONCURRENCY=2` concurrent requests. If the proxy is not running, the SupplierAgent in demo flows falls back to a deterministic step-down formula — but this fallback is not documented in CLAUDE.md or any service README. The proxy also bills the developer's personal Claude account for every request. Recommended long-term replacement: a self-hosted Ollama-backed LLM for the SupplierAgent role in demo/test environments, matching the pattern used by the negotiation engine's buyer-side LLM calls.

(Source: Code finding — services/claude_openai_proxy/README.md, docker-compose.yml lines 462-466 — Confidence: High)

### 4.5 discovery_engine Service Is Orphaned

`services/discovery_engine/` contains a complete multi-network Beckn discovery fan-out implementation (circuit breakers, geo-proximity deduplication, per-network timeouts). It is not in `docker-compose.yml`, not imported by any other service, and not called by the orchestrator. Its README claims port 8006, which conflicts with `data-normalizer`'s published port. The service represents the intended Phase 3 multi-network discovery milestone (per `KnowledgeBase/milestones/phase3_advanced_intelligence.md`) but was never plumbed into the orchestrator pipeline. Options: (a) integrate it — add a `DISCOVERY_ENGINE_URL` env var to the orchestrator and route all discovery calls through it instead of calling `beckn-bap-client` directly; (b) document it as a planned Phase 4 component; (c) archive it as superseded by the built-in multi-network fan-out logic in `beckn-bap-client`.

(Source: Code finding — services/discovery_engine/src/coordinator.py, docker-compose.yml — Confidence: High)

### 4.6 Frontend Has Zero Tests and Missing App Router Infrastructure

The Next.js 13 frontend has no test suite of any kind (no Jest, Vitest, or Playwright tests) and is missing three App Router infrastructure files:

- No `loading.tsx` anywhere in `src/app/` — skeleton loaders are absent; users see blank panels during data fetches
- No `error.tsx` anywhere in `src/app/` — unhandled errors produce a white screen rather than a contextual error boundary
- No `not-found.tsx` — 404s produce the default Next.js page

Additionally, `AuthGuard.tsx` exists in `src/components/` but is never imported, and `Geist` fonts are present in `src/app/fonts/` but are not registered in the root layout, causing the body to fall back to Arial.

Recommended priority order: (1) add `error.tsx` and `loading.tsx` as these affect every data-loading page in the procurement wizard; (2) add a minimal Playwright E2E smoke test covering login → `/` dashboard render → `/request/new` wizard launch; (3) remove or wire `AuthGuard.tsx`.

(Source: frontend/README.md, frontend/CLAUDE.md — Confidence: High)

### 4.7 Analytics Service Returns 503 on DB Unavailability With No Mock Fallback

`services/analytics/src/main.py` returns HTTP 503 when the PostgreSQL connection pool is unavailable. A `mock.py` file exists in the service directory but is documented as "for local dev use only, not auto-served." The frontend dashboard pages (`/dashboard`, `/analytics`) display an error state when the DB is down during integration demos. A bounded mock-data fallback (similar to the orchestrator's `status: "mock"` fallback pattern) would improve demo reliability without affecting production behavior.

(Source: services/analytics/README.md — Confidence: Medium)

### 4.8 Keycloak Setup Is Undocumented and Required for Frontend

The Next.js frontend requires a live Keycloak (or Phase Two hosted Keycloak at `euc1.auth.ac`) OIDC instance. `frontend/src/lib/auth.ts` uses only `KeycloakProvider` with non-null assertions on `KEYCLOAK_CLIENT_ID`, `KEYCLOAK_CLIENT_SECRET`, and `KEYCLOAK_ISSUER` — any missing variable throws at runtime. The "stub credentials dev" description in `frontend/CLAUDE.md` is incorrect. No setup guide, realm export, or user-provisioning script exists in the repository. The credentials `priya@example.com / password123` documented in Phase 1 test guides belong to the old Bap-1 monolith server, not the Next.js app.

Recommended addition to the repository: a `frontend/docs/keycloak-setup.md` file documenting the Phase Two tenant configuration (realm name `procurement-agent`, client ID `procurement-frontend`, required realm-roles mapper, three user accounts with roles `requester`, `approver`, `admin`) plus a `realm-export.json` for import into any Keycloak instance.

(Source: Code finding — frontend/src/lib/auth.ts, frontend/.env.example — Confidence: High)

### 4.9 Two SQL Migration Files Share the `22_` Prefix

`database/sql/22_agent_memory_vector_dim.sql` and `database/sql/22_pending_approval_columns.sql` share the same numeric prefix. The `setup_database.py` script sorts files lexicographically with Python's `sorted()`, which on Linux produces `22_agent_memory_vector_dim.sql` before `22_pending_approval_columns.sql` (underscore `_` sorts before most letters). On filesystems with locale-sensitive collation or Windows with `os.scandir`, the order may differ. Because the two migrations are independent of each other there is no FK-correctness risk, but the ambiguity violates the project's convention that "numeric order matches FK dependency." Recommended fix: rename `22_pending_approval_columns.sql` to `23_pending_approval_columns.sql` after verifying no other migration depends on it.

(Source: Code finding — database/README.md, database/sql/ directory — Confidence: High)

---

## 5. Summary Table

| Priority | Item | Effort | Phase |
|---|---|---|---|
| Critical | Deploy Kafka; wire notification-dispatcher + erp-adapter + orchestrator audit offsets | High | 4 |
| Critical | Externalize orchestrator session state to Redis | Medium | 4 |
| Critical | Fix `embedding_model_type` ENUM — add `BAAI/bge-small-en-v1.5`, update column DEFAULT | Low | Now |
| Critical | Add `ai_provider_type = 'ollama'` to ENUM | Low | Now |
| High | Implement `notify_buyer_no_stock`, `log_unmet_demand`, `trigger_open_rfq_flow` stubs | Medium | 3-4 |
| High | Write `negotiate` audit events from `_run_autonomous_negotiation` | Low | Now |
| High | Document claude_openai_proxy startup and systemd unit in CLAUDE.md | Low | Now |
| High | Add `error.tsx`, `loading.tsx` to Next.js frontend | Low | Now |
| High | Write Keycloak/Phase Two setup guide | Low | Now |
| High | Fix catalog-normalizer README (remove OPENAI_API_KEY, document OLLAMA_URL) | Low | Now |
| Medium | Integrate or formally archive discovery_engine service | Medium | 3-4 |
| Medium | Add internal API authentication (shared bearer token) | Medium | 4 |
| Medium | Rename `22_pending_approval_columns.sql` to `23_` | Low | Now |
| Medium | Fix DEMO_GATEWAY_URL default port discrepancy (8015 vs 8005) | Low | Now |
| Medium | Activate mTLS for SAP/Oracle in erp-adapter | Medium | 4 |
| Medium | Add Playwright E2E smoke test for frontend | Medium | 4 |
| Low | Analytics mock-data fallback for DB-unavailable demos | Low | 4 |
| Low | Nightly retention enforcement CronJob for audit_trail_events | Low | 4 |
| Low | Document COMPLEX_MODEL Docker override rationale in docker-compose.yml | Low | Now |
| Low | Qdrant migration (if corpus exceeds 100 K records) | High | Post-Phase 4 |
