# Configuration Reference

Complete environment variable tables for every service in the Procurement Agent monorepo. Each table was derived from the service's `config.py` (or equivalent) and cross-checked against `docker-compose.yml`. Values marked **CHANGE_ME** in the codebase are flagged here as production-unsafe.

(Source: per-service `config.py` files and `docker-compose.yml` -- Confidence: High)

---

## orchestrator

Port: `8004` (host ports `8004` and `8000` in Docker Compose — dual-mapped so the frontend's default `NEXT_PUBLIC_API_BASE_URL=http://localhost:8000` resolves correctly).

(Source: `services/orchestrator/src/workflow.py` lines 51–94 -- Confidence: High)

| Variable | Default | Required? | Purpose |
|---|---|---|---|
| `INTENTION_PARSER_URL` | `http://localhost:8001` | Yes | Step 1: NL intent parsing service |
| `BECKN_BAP_URL` | `http://localhost:8002` | Yes | Step 2+4: Beckn BAP client for discover/select/init/confirm |
| `COMPARATIVE_SCORING_URL` | `http://localhost:8003` | Yes | Step 3: Scoring adapter |
| `DATA_NORMALIZER_URL` | `http://localhost:8006` | Yes | Persistence layer for all DB writes |
| `DEMO_GATEWAY_URL` | `http://localhost:8015` | Yes (autonomous negotiation) | LangGraph negotiation demo gateway; must be `http://localhost:8015` (README incorrectly documents port 8005) |
| `ANALYTICS_URL` | `http://localhost:8009` | No | Analytics dashboard data |
| `ERP_ADAPTER_URL` | `http://localhost:8007` | No | ERP budget gate and PO push |
| `ERP_INTERNAL_TOKEN` | `dev-internal-token-CHANGE_ME` | **Yes (production)** | Bearer token sent to erp-adapter; must be rotated |
| `ERP_BUDGET_CHECK_ENABLED` | `true` | No | Enables the ERP budget check call; set `false` to skip entirely |
| `ERP_BUDGET_CHECK_REQUIRED` | `false` | No | `true` = fail-closed if budget check errors; `false` = fail-open (dev-safe default) |
| `ERP_BUDGET_CHECK_TIMEOUT_MS` | `800` | No | Hard timeout for the synchronous budget gate call |
| `ERP_SYNC_ENABLED` | `true` | No | Enables async PO outbox sync to ERP |
| `ERP_DEFAULT_COST_CENTER` | `CC-IND-PROC-01` | No | Default cost-center code sent in PO payloads |
| `REDIS_URL` | `""` (disabled) | No | Redis fallback for ERP state cache; primary bus is Kafka |
| `ERP_STATE_CACHE_TTL_SECS` | `3600` | No | TTL for in-memory ERP state cache |
| `KAFKA_BOOTSTRAP` | `""` (disabled) | No | Kafka broker for real-time order tracking; empty disables the consumer |
| `KAFKA_TOPIC` | `po.status.changed` | No | Kafka topic for order status events |
| `KAFKA_GROUP_ID` | `orchestrator-ws-broker` | No | Kafka consumer group for the WebSocket broker task |
| `SELLER_WEBHOOK_HMAC_SECRET` | `dev-seller-hmac-CHANGE_ME` | **Yes (production)** | HMAC-SHA256 secret for incoming seller push webhooks |
| `BUYER_NAME` | `Procurement Agent` | No | Buyer display name sent in Beckn init/confirm contracts |
| `BUYER_EMAIL` | `procurement@example.com` | No | Buyer contact email sent in Beckn contracts |
| `BUYER_PHONE` | `+91-0000000000` | No | Buyer phone for Beckn contracts |
| `BUYER_ADDRESS_STREET` | `""` | No | Buyer street address |
| `BUYER_ADDRESS_CITY` | `Bangalore` | No | Buyer city |
| `BUYER_ADDRESS_STATE` | `Karnataka` | No | Buyer state |
| `BUYER_ADDRESS_AREA_CODE` | `560100` | No | Buyer PIN code |
| `BUYER_ADDRESS_COUNTRY` | `IND` | No | Buyer country (ISO 3166-1 alpha-3) |

**Notes:**

- In-memory session store (`_sessions`) has TTL 1800 seconds with no persistence. A server restart loses all in-flight compare sessions. `TODO(persistence)` in `Bap-1/src/agent/session.py` covers the PostgresBackend swap; that pattern also applies here.
- `ERP_BUDGET_CHECK_REQUIRED=false` (docker-compose default) means ERP connectivity errors do not block `/commit`. For a production deployment this should be `true`.

---

## IntentParser

Runs locally (outside Docker) on port `8001`. Also deployed as the `intention-parser` Docker container with overridden model names.

(Source: `IntentParser/config.py` lines 1–56 and `docker-compose.yml` lines 9–18 -- Confidence: High)

| Variable | Default (local) | Docker override | Required? | Purpose |
|---|---|---|---|---|
| `OLLAMA_URL` | `http://localhost:11434/v1` | `http://host.docker.internal:11434/v1` | Yes | Ollama API base URL for LLM calls |
| `COMPLEX_MODEL` | `qwen3:8b` | `qwen3:1.7b` | No | LLM model for Stage 1 classification and complex Stage 2 extraction. **Docker override disables the two-tier routing — both paths use qwen3:1.7b in the containerised service.** |
| `SIMPLE_MODEL` | `qwen3:1.7b` | `qwen3:1.7b` | No | LLM model for simple/short Stage 2 queries |
| `EMBEDDING_MODEL` | `all-MiniLM-L6-v2` | (not set) | No | Sentence-transformers model for Stage 3 BPP semantic cache |
| `ANTHROPIC_API_KEY` | `""` (disabled) | (not set) | No | Enables Claude Sonnet 4.6 as last-resort Stage 3 broadening fallback. Empty = Claude fallback disabled. |
| `CLAUDE_MODEL` | `claude-sonnet-4-6` | (not set) | No | Claude model name when `ANTHROPIC_API_KEY` is set |
| `MCP_SSE_URL` | `http://localhost:3000/sse` | (not set) | No | MCP sidecar SSE endpoint for Stage 3 BPP validation |
| `MCP_PROBE_TIMEOUT` | `8.0` | (not set) | No | Timeout in seconds for MCP tool calls |
| `BECKN_DOMAIN` | `procurement` | (not set) | No | Beckn domain identifier passed to the sidecar's `search_bpp_catalog` tool |
| `BECKN_VERSION` | `1.1.0` | (not set) | No | Beckn protocol version passed to the sidecar |
| `DB_HOST` | `localhost` | `host.docker.internal` | Yes | PostgreSQL host for Stage 3 pgvector semantic cache |
| `DB_PORT` | `5432` | (not set) | No | PostgreSQL port |
| `DB_NAME` | `procurement_agent` | (not set) | No | Database name |
| `DB_USER` | `postgres` | (not set) | No | Database user |
| `DB_PASSWORD` | `""` | (not set) | **Yes (production)** | Database password; empty is unsafe |
| `DB_SSL` | `prefer` | (not set) | No | SSL mode for asyncpg connections |
| `DB_MIN_POOL` | `5` | (not set) | No | asyncpg minimum connection pool size |
| `DB_MAX_POOL` | `20` | (not set) | No | asyncpg maximum connection pool size |
| `DB_CMD_TIMEOUT` | `5.0` | (not set) | No | asyncpg command timeout in seconds |
| `HNSW_EF_SEARCH` | `100` | (not set) | No | pgvector HNSW ef_search parameter for ANN queries |

**Notes:**

- `VALIDATED_THRESHOLD` (0.85) and `AMBIGUOUS_THRESHOLD` (0.45) are hardcoded constants in `config.py` (not env-configurable despite appearing as named constants). They cannot be overridden without a code change.
- The Docker container runs `PYTHONPATH=/app` with `./IntentParser` and `./shared` bind-mounted.

---

## beckn-bap-client

Port: `8002`. Manages the Beckn protocol lifecycle (discover/select/init/confirm/status) and handles async on_discover callbacks via Redis Pub/Sub.

(Source: `services/beckn-bap-client/src/config.py` and `services/beckn-bap-client/src/handler.py` line 30 -- Confidence: High)

| Variable | Default | Required? | Purpose |
|---|---|---|---|
| `BAP_ID` | `bap.example.com` | **Yes (production)** | Beckn Application Platform identifier registered on the network |
| `BAP_URI` | `http://localhost:8000/beckn` | **Yes (production)** | Public callback URI for ONIX to route on_* callbacks back to this service |
| `ONIX_URL` | `http://localhost:8081` | Yes | Base URL of the onix-bap Go adapter that handles signing and routing |
| `DOMAIN` | `nic2004:52110` | No | Beckn domain code; docker-compose sets `beckn.one/testnet` for sandbox |
| `COUNTRY` | `IND` | No | Buyer country for Beckn context |
| `CITY` | `std:080` | No | Buyer city code for Beckn context |
| `CORE_VERSION` | `2.0.0` | No | Beckn core spec version sent in all request contexts |
| `REQUEST_TIMEOUT` | `30` | No | HTTP request timeout in seconds for outbound Beckn calls |
| `CALLBACK_TIMEOUT` | `10.0` | No | Seconds the `CallbackCollector` waits for on_select/on_init/on_confirm/on_status before raising a timeout |
| `CATALOG_NORMALIZER_URL` | `http://localhost:8005` | Yes | URL of the catalog-normalizer service for on_discover payload normalization |
| `REDIS_URL` | `redis://localhost:6379` | Yes (Stage 3) | Redis URL for Pub/Sub; used by `/on_discover` to publish results to `beckn_results:{txn_id}`. If absent, MCP sidecar will time out. |

**Notes:**

- `BAP_URI` must be a publicly reachable URL in production. ONIX appends `/{action}` to it when routing callbacks, so do not include a trailing action name.
- `REDIS_URL` must be set as a real environment variable (not just in `.env`) because it is read via `os.getenv()` in `handler.py`, not through the Pydantic Settings model.

---

## data-normalizer

Port: `8006`. The sole write path into PostgreSQL. Also hosts the pgvector agent memory endpoints and the audit trail API.

(Source: `services/data-normalizer/src/handler.py` environment block and `DataNormalizer/repositories/request_repo.py` line 12 -- Confidence: High)

| Variable | Default | Required? | Purpose |
|---|---|---|---|
| `PORT` | `8006` | No | Service listen port |
| `DB_HOST` | `localhost` | Yes | PostgreSQL host; `host.docker.internal` in Docker |
| `DB_PORT` | `5432` | No | PostgreSQL port |
| `DB_NAME` | `procurement_agent` | No | Target database name |
| `DB_USER` | `postgres` | No | Database user |
| `DB_PASSWORD` | `postgres123` | **Yes (production)** | Database password; change in production |
| `SYSTEM_USER_ID` | `00000000-0000-0000-0000-000000000001` | No | UUID for the fallback system user upserted into `users` when no `requester_id` is provided. This user gets email `system@procurement-agent.internal`, role `requester`, and `approval_threshold=999999.99`. |

**Notes:**

- The `SYSTEM_USER_ID` is not in `docker-compose.yml`; the hardcoded default is used in all deployments unless explicitly overridden.
- The all-MiniLM-L6-v2 model (~90 MB) is downloaded from Hugging Face on first startup of the memory write endpoint. Cold start for this download is 10–30 seconds.

---

## erp-adapter

Port: `8007`. Vendor-neutral ERP integration with synchronous budget gate, async outbox PO push, and inbound HMAC-signed webhooks.

(Source: `services/erp-adapter/src/config.py` -- Confidence: High)

| Variable | Default | Required? | Purpose |
|---|---|---|---|
| `PORT` | `8007` | No | Service listen port |
| `ERP_INTERNAL_TOKEN` | `dev-internal-token-CHANGE_ME` | **Yes (production)** | Bearer token validated on all `/api/v1/*` routes from orchestrator |
| `ERP_VENDORS` | `mock` | Yes | Comma-separated vendor list: `mock`, `sap`, `oracle`, or `sap,oracle` |
| `DB_HOST` | `procurement-postgres` | Yes | PostgreSQL host for the outbox table |
| `DB_PORT` | `5432` | No | PostgreSQL port |
| `DB_NAME` | `procurement_agent` | No | Database name |
| `DB_USER` | `postgres` | No | Database user |
| `DB_PASSWORD` | `postgres123` | **Yes (production)** | Database password |
| `REDIS_URL` | `redis://redis:6379` | No | Redis for fallback ERP state publishing when Kafka is unavailable |
| `KAFKA_BOOTSTRAP` | `""` (disabled) | No | Kafka broker; empty disables the Kafka producer |
| `KAFKA_TOPIC` | `po.status.changed` | No | Topic for PO status change events |
| `ERP_MOCK_BASE_URL` | `http://erp-mock:8008` | No (mock vendor only) | Base URL for the erp-mock service |
| `SAP_OAUTH_TOKEN_URL` | `http://erp-mock:8008/sap/oauth2/token` | No (SAP vendor only) | SAP OAuth2 token endpoint |
| `SAP_BASE_URL` | `http://erp-mock:8008/sap/opu/...` | No (SAP vendor only) | SAP S/4HANA OData base URL |
| `SAP_CLIENT_ID` | `mock-sap-client` | **Yes (SAP production)** | SAP OAuth2 client ID |
| `SAP_CLIENT_SECRET` | `mock-sap-secret` | **Yes (SAP production)** | SAP OAuth2 client secret |
| `SAP_BUDGET_CHECK_URL` | `http://erp-mock:8008/sap/budget/check` | No (SAP vendor only) | SAP-shaped budget check endpoint |
| `SAP_WEBHOOK_HMAC_SECRET` | `dev-sap-hmac-CHANGE_ME` | **Yes (production)** | Primary HMAC-SHA256 key for verifying `X-Sap-Signature` on inbound SAP webhooks |
| `SAP_WEBHOOK_HMAC_SECRET_NEXT` | `""` (disabled) | No | Rotation key: when set, both primary and next are accepted simultaneously to enable zero-downtime key rotation |
| `ORACLE_OAUTH_TOKEN_URL` | `http://erp-mock:8008/oauth2/v1/token` | No (Oracle vendor only) | Oracle OAuth2 token endpoint |
| `ORACLE_BASE_URL` | `http://erp-mock:8008/fscmRestApi/...` | No (Oracle vendor only) | Oracle ERP Cloud REST base URL |
| `ORACLE_CLIENT_ID` | `mock-oracle-client` | **Yes (Oracle production)** | Oracle OAuth2 client ID |
| `ORACLE_CLIENT_SECRET` | `mock-oracle-secret` | **Yes (Oracle production)** | Oracle OAuth2 client secret |
| `ORACLE_BUDGET_CHECK_URL` | `http://erp-mock:8008/oracle/budget/check` | No (Oracle vendor only) | Oracle-shaped budget check endpoint |
| `ORACLE_WEBHOOK_HMAC_SECRET` | `dev-oracle-hmac-CHANGE_ME` | **Yes (production)** | Primary HMAC-SHA256 key for Oracle webhook verification |
| `ORACLE_WEBHOOK_HMAC_SECRET_NEXT` | `""` (disabled) | No | Oracle HMAC rotation key |
| `BREAKER_FAIL_MAX` | `5` | No | Per-vendor circuit breaker consecutive failure threshold before tripping to OPEN |
| `BREAKER_RESET_TIMEOUT_SECS` | `60` | No | Seconds in OPEN state before auto-probe (half-open) |
| `BUDGET_CHECK_TOTAL_TIMEOUT_MS` | `800` | No | Hard timeout for the synchronous budget gate; orchestrator mirrors this as `ERP_BUDGET_CHECK_TIMEOUT_MS` |
| `WORKER_CONCURRENCY` | `10` | No | Number of concurrent outbox worker coroutines |
| `WORKER_BACKOFF_CSV` | `5,30,120,600,3600` | No | Retry backoff delays in seconds (5 attempts total, up to 1 hour) |
| `WORKER_POLL_INTERVAL_SECONDS` | `2.0` | No | How often the outbox worker polls for pending rows |
| `LOG_PAYLOADS` | `false` | No | When `true`, full request/response bodies are logged. Never set `true` in production (PII risk). |

**Dual-secret HMAC rotation protocol:**

To rotate a webhook secret without downtime: (1) set `_NEXT` to the new secret; (2) deploy; (3) update the ERP vendor to sign with the new key; (4) verify new signatures arrive; (5) move `_NEXT` value to the primary var; (6) clear `_NEXT`.

---

## erp-mock

Port: `8008`. Local ERP stub for development. All state is in-memory and non-durable.

(Source: `services/erp-mock/src/config.py` -- Confidence: High)

| Variable | Default | Required? | Purpose |
|---|---|---|---|
| `PORT` | `8008` | No | Service listen port |
| `MOCK_SCENARIO` | `happy` | No | Active scenario: `happy`, `budget_exhausted`, `po_create_fails`, `webhook_delayed`, `erp_approval_required`, `erp_preferred_supplier`. Can also be overridden per-request with `X-Mock-Scenario` header. |
| `WEBHOOK_TARGET_URL` | `http://erp-adapter:8007` | No | Target URL for automatic webhook callbacks after `/mock/po/create` |
| `WEBHOOK_DELAY_SECONDS` | `2.0` | No | Seconds to wait before posting the inbound webhook back to erp-adapter |
| `SAP_WEBHOOK_HMAC_SECRET` | `dev-sap-hmac-CHANGE_ME` | No | HMAC key used to sign outbound mock webhooks; must match `SAP_WEBHOOK_HMAC_SECRET` in erp-adapter |
| `ORACLE_WEBHOOK_HMAC_SECRET` | `dev-oracle-hmac-CHANGE_ME` | No | Oracle HMAC signing key (currently unused by the mock emitter; reserved for future use) |

---

## mcp-sidecar

Port: `3000`. MCP SSE bridge between IntentParser and the Beckn BAP client. Runs locally, not in Docker.

(Source: `services/mcp-sidecar/config.py` -- Confidence: High)

| Variable | Default | Required? | Purpose |
|---|---|---|---|
| `PORT` | `3000` | No | SSE server listen port |
| `BAP_CLIENT_URL` | `http://localhost:8002` | Yes | URL of beckn-bap-client's `/discover` endpoint |
| `BAP_API_KEY` | (none) | **Yes — service refuses to start without it** | Bearer token for the BAP client API. Any non-empty string works in dev. Must never be committed to source control. |
| `REDIS_URL` | `redis://localhost:6379` | **Yes** | Redis Pub/Sub URL; must be a real env var (not just `.env`) — read via `os.getenv()` in `bap_client.py`, not through Pydantic Settings |
| `REDIS_RESULT_TIMEOUT` | `15` | **Yes** | Seconds to wait for a result on the Redis channel before returning `found:false`; also must be a real env var. This is the primary latency ceiling for discovery probes. |
| `MCP_BAP_TIMEOUT` | `3.0` | No | HTTP safety valve for the fire-and-forget POST to beckn-bap-client; governs only the HTTP layer, not the meaningful Redis wait |
| `RANKING_MIN_SIMILARITY` | `0.30` | No | Cosine similarity floor; items below this threshold are filtered from results |

**Notes:**

- `REDIS_URL` and `REDIS_RESULT_TIMEOUT` are the two exceptions to the Pydantic Settings pattern: they are read via `os.getenv()` in `bap_client.py` and must therefore be present in the process environment, not just the `.env` file.
- Start command: `cd services/mcp-sidecar && BAP_API_KEY="<any-string>" uvicorn server:app --port 3000` (inside `conda activate infosys_project`).

---

## negotiation_engine

Port: `8004` on container, `18004` on host (to avoid collision with orchestrator which also maps `8004`).

(Source: `services/negotiation_engine/src/config.py` -- Confidence: High)

| Variable | Default | Required? | Purpose |
|---|---|---|---|
| `NEGOTIATION_API_HOST` | `0.0.0.0` | No | FastAPI bind host |
| `NEGOTIATION_API_PORT` | `8004` | No | FastAPI listen port |
| `NEGOTIATION_LOG_LEVEL` | `INFO` | No | Log verbosity |
| `OPENAI_API_KEY` | `None` | No | API key sent to the LLM endpoint; since the target is the local Claude proxy at `:8012`, any non-empty string (e.g. `your-local-proxy-key`) is accepted |
| `NEGOTIATION_OPENAI_BASE_URL` | `http://host.docker.internal:8012/v1` | Yes | Base URL for the OpenAI-compatible LLM endpoint. Points at the `claude_openai_proxy` service which must be running on the host. |
| `NEGOTIATION_OPENAI_MODEL` | `claude-3-5-sonnet` | No | Model name sent to the proxy; mapped to the Claude alias configured in `claude_openai_proxy/config.py` |
| `NEGOTIATION_OPENAI_TIMEOUT_S` | `30.0` | No | LLM call timeout in seconds |
| `NEGOTIATION_ADVISORY_MAX_TOKENS` | `512` | No | Max token budget for advisory LLM node responses |
| `REDIS_URL` | `redis://localhost:6379/0` | Yes | Redis URL for async on_select callback transport |
| `NEGOTIATION_REDIS_ON_SELECT_CHANNEL` | `beckn_on_select_results` | No | Redis channel the `OnSelectListener` subscribes to for resuming parked LangGraph states |
| `NEGOTIATION_REDIS_HITL_PREFIX` | `negotiation_hitl_decisions` | No | Redis channel prefix for HITL override signals |
| `NEGOTIATION_POSTGRES_DSN` | `None` (disabled) | No | PostgreSQL DSN for durable LangGraph checkpointing via `AsyncPostgresSaver`. When unset, falls back to in-memory `MemorySaver` (state lost on restart). |
| `KAFKA_BOOTSTRAP_SERVERS` | `None` (disabled) | No | Kafka broker for audit event publishing to `procurement.negotiation.v1`; fail-open when unset |
| `NEGOTIATION_KAFKA_TOPIC` | `procurement.negotiation.v1` | No | Kafka topic for negotiation audit events |
| `NEGOTIATION_KAFKA_POLICY_VIOLATIONS_TOPIC` | `procurement.negotiation.policy_violations.v1` | No | Topic for policy violation events |
| `NEGOTIATION_KAFKA_DLQ_TOPIC` | `procurement.negotiation.dlq.v1` | No | Dead-letter queue topic |
| `NEGOTIATION_KAFKA_CLIENT_ID` | `negotiation-engine` | No | Kafka producer client ID |
| `QDRANT_URL` | `None` (disabled) | No | Qdrant URL for agent memory; not used in the as-built system (pgvector is the sole vector store) |
| `QDRANT_API_KEY` | `None` (disabled) | No | Qdrant API key; unused in as-built system |
| `LANGCHAIN_TRACING_V2` | `false` | No | Set `true` to enable LangSmith tracing (Phase 4) |
| `LANGCHAIN_ENDPOINT` | `https://api.smith.langchain.com` | No | LangSmith API endpoint |
| `LANGCHAIN_API_KEY` | `None` | No (required if tracing enabled) | LangSmith API key; tracing is skipped silently if unset |
| `LANGCHAIN_PROJECT` | `procurement-negotiation-prod` | No | LangSmith project name |

**Notes:**

- `NEGOTIATION_OPENAI_BASE_URL` points at `host.docker.internal:8012` which requires the `claude_openai_proxy` service to be running on the host with `CLAUDE_PROXY_HOST=0.0.0.0` (the systemd unit sets this). The proxy is not in `docker-compose.yml`.
- When `NEGOTIATION_POSTGRES_DSN` is unset, a restart of the container discards all in-flight negotiation states.

---

## comparative-scoring

Port: `8003`. Thin HTTP adapter forwarding to the `prediction-api` MLOps service; falls back to min-price heuristic.

(Source: `services/comparative-scoring/src/handler.py` lines 45–51 -- Confidence: High)

| Variable | Default | Required? | Purpose |
|---|---|---|---|
| `PREDICTION_API_URL` | `http://prediction-api:8004` | No | URL of the MLOps `prediction-api` service (from `services/ComparativeAndScoreing/`); must be reachable if ML scoring is desired |
| `PREDICTION_TIMEOUT_S` | `8.0` | No | Timeout in seconds waiting for `prediction-api` response before triggering fallback |
| `SCORING_FALLBACK_ENABLED` | `true` | No | When `true`, a `prediction-api` failure falls back to the Phase 1 min-price heuristic. Set `false` for canary deploys that must surface ML failures. |

**Notes:**

- `prediction-api` is part of the separate MLOps stack under `services/ComparativeAndScoreing/`. Start it with `docker compose -f services/ComparativeAndScoreing/docker-compose.mlops.yaml up prediction-api`. On first start with no Production MLflow model registered, `prediction-api` itself falls back to static weights `[0.4, 0.3, 0.3]` (controlled by `ALLOW_FALLBACK_WEIGHTS=true` in the MLOps service).

---

## discovery_engine

Port: `8006`. Multi-network Beckn discovery fan-out service. **Status: orphaned — not in `docker-compose.yml` and not called by any other service.** Config documented for completeness.

(Source: `services/discovery_engine/src/config.py` -- Confidence: High)

| Variable | Default | Required? | Purpose |
|---|---|---|---|
| `DISCOVERY_API_HOST` | `0.0.0.0` | No | FastAPI bind host |
| `DISCOVERY_API_PORT` | `8006` | No | FastAPI listen port (conflicts with data-normalizer; would require a port change to co-deploy) |
| `DISCOVERY_LOG_LEVEL` | `INFO` | No | Log verbosity |
| `DISCOVERY_NETWORKS_JSON` | Two placeholder entries (`network_a` and `network_b`) | Yes | JSON array of `{"name": str, "base_url": str, "timeout_s": float}` objects defining the Beckn networks to fan out to |
| `DISCOVERY_DEFAULT_TIMEOUT_S` | `8.0` | No | Per-network request timeout applied when a network entry omits `timeout_s` |
| `DISCOVERY_CB_FAILURE_THRESHOLD` | `3` | No | Consecutive failures before a per-network circuit breaker trips to OPEN |
| `DISCOVERY_CB_RECOVERY_TIMEOUT_S` | `30.0` | No | Seconds in OPEN state before the circuit breaker probes the network again |
| `DISCOVERY_GEO_PROXIMITY_KM` | `0.5` | No | Great-circle distance threshold for treating two identical-name/currency items as geographic duplicates (merges `sources[]` rather than duplicating) |
| `DISCOVERY_HTTP_CONNECTOR_LIMIT` | `64` | No | aiohttp connector concurrency limit |
| `DISCOVERY_HTTP_OUTER_TIMEOUT_S` | `60.0` | No | Outer timeout on the entire aiohttp ClientSession as a belt-and-suspenders guard |

---

## notification-dispatcher

Port: `8010` (container only — no host port published in `docker-compose.yml`).

(Source: `services/notification-dispatcher/src/config.py` -- Confidence: High)

| Variable | Default | Required? | Purpose |
|---|---|---|---|
| `KAFKA_BOOTSTRAP` | `""` (disabled) | Yes (for notifications to work) | Kafka broker address. The consumer loop never starts when empty — no notifications are sent. |
| `KAFKA_TOPIC` | `po.status.changed` | No | Kafka topic to consume for order status events |
| `KAFKA_GROUP_ID` | `notification-dispatcher` | No | Kafka consumer group ID |
| `SLACK_WEBHOOK_URL` | `""` (disabled) | No | Slack incoming webhook URL; empty disables the Slack channel |
| `TEAMS_WEBHOOK_URL` | `""` (disabled) | No | Microsoft Teams webhook URL; empty disables the Teams channel |
| `SMTP_HOST` | `""` (disabled) | No | SMTP server hostname; empty disables the email channel |
| `SMTP_PORT` | `587` | No | SMTP port (STARTTLS) |
| `SMTP_USER` | `""` | No | SMTP authentication username |
| `SMTP_PASSWORD` | `""` | No | SMTP authentication password |
| `SMTP_FROM` | `noreply@procurement-agent.local` | No | From address for order email notifications |
| `DB_HOST` | `localhost` | No | PostgreSQL host for recipient email lookup; empty `DB_USER` disables DB access |
| `DB_PORT` | `5432` | No | PostgreSQL port |
| `DB_NAME` | `procurement_agent` | No | Database name |
| `DB_USER` | `""` (disabled) | No | Database user for email recipient lookup; empty skips DB lookup and disables email recipient resolution |
| `DB_PASSWORD` | `""` | No | Database password |

**Routing rules by `po_status` / `state` (case-insensitive):**

| Status | Slack | Teams | Email |
|---|---|---|---|
| `confirmed` | Yes | Yes | Yes |
| `shipped` | Yes | Yes | No |
| `delivered` | Yes | Yes | Yes |
| `cancelled` | Yes | Yes | No |
| Anything else | No | No | No |

---

## sim-bpp

Port: `3002`. Local Beckn BPP simulator written in Python (replaced `fidedocker/sandbox-2.0`). Catalog hot-reloads from a bind-mounted JSON file.

(Source: `services/sim-bpp/src/handler.py` lines 38–62 -- Confidence: High)

| Variable | Default | Required? | Purpose |
|---|---|---|---|
| `PORT` | `3002` | No | Service listen port |
| `ONIX_BPP_CALLER` | `http://onix-bpp:8082/bpp/caller` | Yes | Base URL of the onix-bpp caller module. sim-bpp appends `/on_{action}` when posting callbacks. |
| `BPP_ID` | `bpp.example.com` | No | BPP identifier embedded in all response contexts |
| `BPP_URI` | `http://onix-bpp:8082/bpp/receiver` | No | BPP receiver URI sent in catalog responses so ONIX can route transactions back |
| `CATALOG_PATH` | `/app/catalog.json` | No | Path to the catalog JSON file; bind-mounted at `./services/sim-bpp/catalog.json` in docker-compose. Re-read on every request — no restart needed to update the catalog. |
| `SIM_BPP_AUTO_ADVANCE` | `false` (code default) | No | **`true` in docker-compose.yml.** When enabled, automatically transitions a confirmed order through `ACCEPTED → PACKED → SHIPPED → OUT_FOR_DELIVERY → DELIVERED` at the interval below. |
| `SIM_BPP_ADVANCE_INTERVAL_SECS` | `5` | No | Seconds between each auto-advance lifecycle step |
| `KAFKA_BOOTSTRAP` | `""` (disabled) | No | Kafka broker for publishing `po.status.changed` events during auto-advance; empty disables Kafka publishing |
| `KAFKA_TOPIC` | `po.status.changed` | No | Kafka topic for lifecycle events |
| `DATA_NORMALIZER_URL` | `http://data-normalizer:8006` | Yes (auto-advance) | URL for PATCHing `purchase_orders.status` during lifecycle transitions |

**Note:** `SIM_BPP_AUTO_ADVANCE` defaults to `false` in code but is set to `true` in `docker-compose.yml`. A developer running only local services (not Docker) will not see automatic lifecycle transitions unless the env var is set explicitly.

---

## frontend

Port: `3000`. Next.js 13.5 App Router application.

(Source: `frontend/.env.example`, `frontend/src/lib/auth.ts`, `frontend/src/lib/api.ts` -- Confidence: High)

| Variable | Default | Required? | Purpose |
|---|---|---|---|
| `NEXTAUTH_URL` | `http://localhost:3000` | **Yes** | Public URL of this Next.js app. Must match the redirect URI registered in the Keycloak client. |
| `NEXTAUTH_SECRET` | (none) | **Yes** | Secret used to sign and verify session JWTs. Generate with `openssl rand -base64 32`. Empty is invalid. |
| `KEYCLOAK_ISSUER` | `https://euc1.auth.ac/auth` | **Yes** | OIDC issuer URL. For Phase Two (phasetwo.io) cloud: `https://app.phasetwo.io/auth/realms/<realm>`. For self-hosted: `https://<host>/realms/<realm>`. |
| `KEYCLOAK_CLIENT_ID` | `procurement-frontend` | **Yes** | Client ID in the Keycloak realm |
| `KEYCLOAK_CLIENT_SECRET` | (none) | **Yes** | Client secret (confidential client). Must be copied from the Keycloak dashboard. |
| `NEXT_PUBLIC_API_BASE_URL` | `http://localhost:8000` | Yes | Orchestrator base URL. Matches the orchestrator's `8000` host port mapping in docker-compose. |

**Keycloak client requirements:**

- Client authentication: ON (confidential client, not public)
- Standard flow: enabled (authorization code + PKCE)
- Valid Redirect URIs: `${NEXTAUTH_URL}/api/auth/callback/keycloak`
- Web origins: `${NEXTAUTH_URL}`
- Realm roles mapper on the client scope: `realm_access.roles` added to the ID token (`Add to ID token: ON`). Without this, `auth.ts` falls back to decoding the access token manually.

**Roles:** `admin`, `approver`, `requester`. Unknown roles default to `requester`. Role claim path: `realm_access.roles` in the JWT.

**Important:** There is no stub credentials provider. Even local development requires a live Keycloak / Phase Two OIDC instance with a configured realm, client, and user accounts. The example `.env.example` targets the Phase Two cloud tenant `euc1.auth.ac`, realm `procurement-agent`.

---

## analytics

Port: `8009`.

(Source: docker-compose.yml analytics service environment block and `services/analytics/README.md` -- Confidence: High)

| Variable | Default | Required? | Purpose |
|---|---|---|---|
| `PORT` | `8009` | No | Service listen port |
| `DB_HOST` | `localhost` | Yes | PostgreSQL host; `host.docker.internal` in Docker |
| `DB_PORT` | `5432` | No | PostgreSQL port |
| `DB_NAME` | `procurement_agent` | No | Database name |
| `DB_USER` | `postgres` | No | Database user |
| `DB_PASSWORD` | `postgres123` | **Yes (production)** | Database password; change in production |

**Notes:** Returns HTTP 503 (not mock data) when the DB connection pool is unavailable. A `mock.py` exists for local dev scripting but is not served automatically.

---

## claude_openai_proxy (local host service)

Port: `8012` (loopback `127.0.0.1` by default; `0.0.0.0` when running as the systemd unit to allow Docker bridge access). This service is **not in `docker-compose.yml`** — it must be started separately on the host. Required by `negotiation-engine` and `demo-gateway`.

(Source: `services/claude_openai_proxy/config.py` and `services/claude_openai_proxy/claude-proxy.service` -- Confidence: High)

Start command (local dev): `uvicorn services.claude_openai_proxy.main:app --host 127.0.0.1 --port 8012`

Start command (systemd, allows Docker access): `systemctl --user enable --now claude-proxy` (after copying `claude-proxy.service` to `~/.config/systemd/user/`)

| Variable | Default | Required? | Purpose |
|---|---|---|---|
| `CLAUDE_PROXY_KEY` | `""` (auth disabled) | **Yes (production)** | Bearer token for `Authorization: Bearer <key>` on all `/v1/*` routes. Empty disables auth with a startup warning. |
| `CLAUDE_PROXY_HOST` | `127.0.0.1` | No | Bind host. Set `0.0.0.0` when running the systemd unit so Docker-bridged containers can reach it via `host.docker.internal:8012`. |
| `CLAUDE_PROXY_PORT` | `8012` | No | Listen port |
| `CLAUDE_PROXY_BINARY_PATH` | `/home/carbaje/.local/bin/claude` | **Yes** | Absolute path to the `claude` CLI binary on the host. Must be updated per machine. |
| `CLAUDE_PROXY_DEFAULT_MODEL` | `sonnet` | No | Claude alias used when the requested OpenAI model name has no mapping |
| `CLAUDE_PROXY_MAX_CONCURRENCY` | `2` | No | Maximum concurrent `claude -p` subprocess invocations. Excess requests queue, not reject. |
| `CLAUDE_PROXY_TIMEOUT_S` | `120.0` | No | Hard subprocess timeout; the CLI is killed if it emits no new output within this window |
| `CLAUDE_PROXY_DISABLE_TOOLS` | `true` | No | When `true`, all acting/IO tools (`Bash`, `Edit`, `Write`, `Read`, etc.) are disallowed in `claude -p` mode to prevent interactive permission hangs |
| `CLAUDE_PROXY_PERMISSION_MODE` | `default` | No | Claude permission mode passed to the CLI |
| `CLAUDE_PROXY_INCLUDE_PARTIAL` | `true` | No | Whether to stream partial assistant text before the final result |

**Model mapping (OpenAI name → Claude alias):**

| OpenAI name | Claude alias |
|---|---|
| `gpt-4o` | `sonnet` |
| `gpt-4o-mini` | `haiku` |
| `gpt-4-turbo` | `sonnet` |
| `gpt-4` | `opus` |
| `gpt-3.5-turbo` | `haiku` |
| `claude-3-5-sonnet` | `sonnet` |
| `claude-3-5-haiku` | `haiku` |

Names starting with `claude` pass through unchanged.

**Limitations:** `temperature`, `top_p`, and `max_tokens` are accepted in requests but silently ignored — the Claude CLI has no sampling knobs. Each request bills the host's Claude account. Cold start per request is ~1–3 seconds.

---

## Secrets That Must Be Set in Production

The following variables have no safe default and **will silently leave the system insecure or broken** if not overridden before a production deployment.

(Source: code review of all config files -- Confidence: High)

| Variable | Service | Risk if not set |
|---|---|---|
| `NEXTAUTH_SECRET` | frontend | Session JWTs are unsigned; any JWT is accepted |
| `KEYCLOAK_CLIENT_SECRET` | frontend | OIDC flow breaks; no user can authenticate |
| `KEYCLOAK_ISSUER` | frontend | Defaults to a hardcoded Phase Two dev tenant; all auth goes to the wrong realm |
| `ERP_INTERNAL_TOKEN` | orchestrator, erp-adapter | Default `dev-internal-token-CHANGE_ME` is public knowledge; any caller can hit `/api/v1/*` on erp-adapter |
| `SELLER_WEBHOOK_HMAC_SECRET` | orchestrator | Default `dev-seller-hmac-CHANGE_ME` is public; forged seller webhooks will be accepted |
| `SAP_WEBHOOK_HMAC_SECRET` | erp-adapter, erp-mock | Default `dev-sap-hmac-CHANGE_ME` is public; forged SAP webhooks accepted |
| `ORACLE_WEBHOOK_HMAC_SECRET` | erp-adapter, erp-mock | Default `dev-oracle-hmac-CHANGE_ME` is public; forged Oracle webhooks accepted |
| `SAP_CLIENT_SECRET` | erp-adapter | Default `mock-sap-secret` is public; used only when `ERP_VENDORS=sap` |
| `ORACLE_CLIENT_SECRET` | erp-adapter | Default `mock-oracle-secret` is public; used only when `ERP_VENDORS=oracle` |
| `DB_PASSWORD` | data-normalizer, analytics, erp-adapter, notification-dispatcher | Default `postgres123` is trivial; grants full DB access |
| `BAP_API_KEY` | mcp-sidecar | Service refuses to start without it; any non-empty string works in dev but should be rotated for production |
| `CLAUDE_PROXY_KEY` | claude_openai_proxy | Auth is disabled when empty; any client can trigger Claude CLI invocations that bill the host account |
| `CLAUDE_PROXY_BINARY_PATH` | claude_openai_proxy | Hardcoded to `/home/carbaje/.local/bin/claude`; will fail on every other machine |
| `BAP_ID` | beckn-bap-client | Default `bap.example.com` is a placeholder; must be replaced with the registered BAP identifier on the target Beckn network |
| `BAP_URI` | beckn-bap-client | Default is localhost; must be a publicly reachable URL for ONIX to route callbacks correctly |

---

## Dev vs Production Differences

Variables where the development default is intentionally unsafe, or where production requires a different value.

(Source: comparison of code defaults vs `docker-compose.yml` overrides -- Confidence: High)

| Variable | Dev default / docker-compose value | Production requirement |
|---|---|---|
| `ERP_BUDGET_CHECK_REQUIRED` | `false` (fail-open) | `true` (fail-closed); prevents budget overruns even if erp-adapter is unreachable |
| `LOG_PAYLOADS` (erp-adapter) | `false` | Must remain `false`; `true` logs full PO and budget payloads containing PII and financial data |
| `SIM_BPP_AUTO_ADVANCE` | `true` in docker-compose | Irrelevant in production (sim-bpp is replaced by a real Beckn network BPP) |
| `COMPLEX_MODEL` (IntentParser) | `qwen3:1.7b` in docker-compose (overrides code default of `qwen3:8b`) | In production with a capable GPU host, restore to `qwen3:8b` to enable two-tier complexity routing; currently collapsed to qwen3:1.7b in Docker |
| `CLAUDE_PROXY_HOST` | `127.0.0.1` (loopback, dev) | `0.0.0.0` when running the systemd unit so Docker-bridged containers can reach port 8012 via `host.docker.internal` |
| `NEGOTIATION_POSTGRES_DSN` | unset (MemorySaver — state lost on restart) | Set to a valid DSN to enable `AsyncPostgresSaver` for durable LangGraph checkpointing |
| `KAFKA_BOOTSTRAP` | `""` (disabled in all services) | A Kafka broker address for all services that require event-driven fan-out (negotiation audit, real-time tracking, notifications). Kafka is deferred to Phase 4. |
| `NEXTAUTH_URL` | `http://localhost:3000` | Public HTTPS hostname; must match the Keycloak redirect URI exactly |
| `LANGCHAIN_TRACING_V2` | `false` | `true` with a valid `LANGCHAIN_API_KEY` for Phase 4 LangSmith observability |
| `DB_HOST` | `host.docker.internal` (docker-compose) | Container DNS name (e.g. `procurement-postgres`) when the DB itself is containerised, or a managed PostgreSQL hostname in cloud deployments |
| `DOMAIN` (beckn-bap-client) | `nic2004:52110` (code default) / `beckn.one/testnet` (docker-compose) | Real Beckn network domain for the target industry vertical |
| `SAP_OAUTH_TOKEN_URL`, `SAP_BASE_URL`, `ORACLE_OAUTH_TOKEN_URL`, `ORACLE_BASE_URL` | Point at `erp-mock:8008` | Real SAP S/4HANA or Oracle ERP Cloud endpoints |
