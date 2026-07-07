# Environment Variables Reference

All configuration in the Procurement Agent is environment-variable driven. Each service owns a module-level `config.py` that reads variables through a Pydantic Settings model. Direct use of `os.getenv()` outside `config.py` is a violation of the project convention — two known exceptions are documented in each relevant section.

Related documentation: [Architecture](ARCHITECTURE.md) | [Components](COMPONENTS.md) | [Security](SECURITY.md)

---

## How Configuration Works

```
repo root
├── .env                  ← loaded by docker-compose.yml; sets defaults for all containers
├── IntentParser/
│   └── config.py         ← Pydantic BaseSettings; reads env vars at import time
├── services/
│   ├── orchestrator/src/config.py
│   ├── beckn-bap-client/src/config.py
│   ├── mcp-sidecar/config.py
│   └── ...               ← every service has its own config.py
└── frontend/
    └── .env.local        ← Next.js convention; never committed (git-ignored)
```

**Docker deployments:** `docker-compose.yml` reads the root `.env` file and passes variables into each container's `environment:` block. All containers share the same `.env` but each service only reads the variables it declares in its `config.py`.

**Local services (IntentParser, mcp-sidecar):** These run outside Docker and must have variables exported in the shell before starting. The recommended approach:

```bash
# Inside conda activate infosys_project
export $(grep -v '^#' .env | xargs)
cd IntentParser && uvicorn api:app --port 8001 --reload
cd services/mcp-sidecar && BAP_API_KEY="any-dev-string" uvicorn server:app --port 3000
```

**`os.getenv()` exceptions:** Two variables bypass the Pydantic Settings pattern and must be real process environment variables (not just present in `.env`):
- `REDIS_URL` in `beckn-bap-client/src/handler.py`
- `REDIS_URL` and `REDIS_RESULT_TIMEOUT` in `mcp-sidecar/bap_client.py`

---

## Global / Shared

These variables appear in multiple services. Their canonical value should be set once in the root `.env` and forwarded to each container.

| Variable | Default | Required | Description |
|---|---|---|---|
| `DATABASE_URL` | (not used as a single global) | No | PostgreSQL DSN. Most services use individual `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASSWORD` components rather than a single URL. |
| `REDIS_URL` | `redis://redis:6379` (Docker) / `redis://localhost:6379` (local) | Yes | Redis Pub/Sub broker URL. Used by beckn-bap-client, mcp-sidecar, orchestrator, negotiation_engine, and erp-adapter. |
| `LOG_LEVEL` | `INFO` | No | Log verbosity. Applies where services honour a `LOG_LEVEL` variable (not all services use this name — see per-service tables). |

---

## IntentParser (:8001)

Runs locally (outside Docker) on port `8001`. Also deployed as the `intention-parser` Docker container with model overrides. The Docker override **collapses two-tier LLM routing** — both complex and simple paths use `qwen3:1.7b` in the container.

Source: `IntentParser/config.py`

| Variable | Default (local) | Docker override | Required | Description |
|---|---|---|---|---|
| `OLLAMA_URL` | `http://localhost:11434/v1` | `http://host.docker.internal:11434/v1` | Yes | Ollama API base URL for LLM calls |
| `COMPLEX_MODEL` | `qwen3:8b` | `qwen3:1.7b` | No | LLM for Stage 1 classification and complex Stage 2 extraction. Docker override disables two-tier routing. |
| `SIMPLE_MODEL` | `qwen3:1.7b` | `qwen3:1.7b` | No | LLM for simple/short Stage 2 queries |
| `EMBEDDING_MODEL` | `all-MiniLM-L6-v2` | (not set) | No | Sentence-transformers model for Stage 3 BPP semantic cache |
| `ANTHROPIC_API_KEY` | `""` (disabled) | (not set) | No | (SECRET) Enables Claude Sonnet 4.6 as last-resort Stage 3 broadening fallback. Empty = Claude fallback disabled. Only the broadening prompt is sent; no buyer identity or pricing data leaves the host. |
| `CLAUDE_MODEL` | `claude-sonnet-4-6` | (not set) | No | Claude model alias used when `ANTHROPIC_API_KEY` is set |
| `MCP_SSE_URL` | `http://localhost:3000/sse` | (not set) | No | MCP sidecar SSE endpoint for Stage 3 BPP validation |
| `MCP_PROBE_TIMEOUT` | `8.0` | (not set) | No | Timeout in seconds for MCP tool calls |
| `BECKN_DOMAIN` | `procurement` | (not set) | No | Beckn domain identifier passed to `search_bpp_catalog` |
| `BECKN_VERSION` | `1.1.0` | (not set) | No | Beckn protocol version passed to the sidecar |
| `DB_HOST` | `localhost` | `host.docker.internal` | Yes | PostgreSQL host for Stage 3 pgvector semantic cache |
| `DB_PORT` | `5432` | (not set) | No | PostgreSQL port |
| `DB_NAME` | `procurement_agent` | (not set) | No | Database name |
| `DB_USER` | `postgres` | (not set) | No | Database user |
| `DB_PASSWORD` | `""` | (not set) | Yes (production) | (SECRET, NO DEFAULT) Database password; empty string is unsafe in any shared environment |
| `DB_SSL` | `prefer` | (not set) | No | SSL mode for asyncpg connections |
| `DB_MIN_POOL` | `5` | (not set) | No | asyncpg minimum connection pool size |
| `DB_MAX_POOL` | `20` | (not set) | No | asyncpg maximum connection pool size |
| `DB_CMD_TIMEOUT` | `5.0` | (not set) | No | asyncpg command timeout in seconds |
| `HNSW_EF_SEARCH` | `100` | (not set) | No | pgvector HNSW ef_search parameter for ANN queries |

**Note:** `VALIDATED_THRESHOLD` (0.85) and `AMBIGUOUS_THRESHOLD` (0.45) are named constants in `config.py` but are **not** env-configurable. Changing them requires a code edit.

---

## orchestrator (:8004)

Port `8004` on the container; Docker Compose also publishes host port `8000` so the frontend's default `NEXT_PUBLIC_API_BASE_URL=http://localhost:8000` resolves correctly.

Source: `services/orchestrator/src/workflow.py`

| Variable | Default | Required | Description |
|---|---|---|---|
| `INTENTION_PARSER_URL` | `http://localhost:8001` | Yes | Step 1: NL intent parsing service |
| `BECKN_BAP_URL` | `http://localhost:8002` | Yes | Steps 2 and 4: Beckn BAP client for discover/select/init/confirm |
| `COMPARATIVE_SCORING_URL` | `http://localhost:8003` | Yes | Step 3: Scoring adapter |
| `DATA_NORMALIZER_URL` | `http://localhost:8006` | Yes | Persistence layer for all DB writes |
| `DEMO_GATEWAY_URL` | `http://localhost:8015` | Yes (autonomous negotiation) | LangGraph negotiation demo gateway. NOTE: `docker-compose.yml` and README document port `8005` — the actual running port is `8015`. |
| `ANALYTICS_URL` | `http://localhost:8009` | No | Analytics dashboard data |
| `ERP_ADAPTER_URL` | `http://localhost:8007` | No | ERP budget gate and PO push |
| `ERP_INTERNAL_TOKEN` | `dev-internal-token-CHANGE_ME` | Yes (production) | (SECRET) Bearer token sent to erp-adapter on all `/api/v1/*` routes. Default is a public placeholder — must be rotated before any external deployment. |
| `ERP_BUDGET_CHECK_ENABLED` | `true` | No | Enables the ERP budget check call; set `false` to skip entirely |
| `ERP_BUDGET_CHECK_REQUIRED` | `false` | No | `true` = fail-closed if budget check errors; `false` = fail-open. Docker default is `false` (dev-safe). Production must use `true`. |
| `ERP_BUDGET_CHECK_TIMEOUT_MS` | `800` | No | Hard timeout in milliseconds for the synchronous budget gate call |
| `ERP_SYNC_ENABLED` | `true` | No | Enables async PO outbox sync to ERP |
| `ERP_DEFAULT_COST_CENTER` | `CC-IND-PROC-01` | No | Default cost-center code sent in PO payloads |
| `SELLER_WEBHOOK_HMAC_SECRET` | `dev-seller-hmac-CHANGE_ME` | Yes (production) | (SECRET) HMAC-SHA256 secret for verifying inbound seller push webhooks. Default is a public placeholder. |
| `ERP_STATE_CACHE_TTL_SECS` | `3600` | No | TTL in seconds for in-memory ERP state cache |
| `REDIS_URL` | `""` (disabled) | No | Redis fallback for ERP state cache; primary bus is Kafka |
| `KAFKA_BOOTSTRAP` | `""` (disabled) | No | Kafka broker for real-time order tracking; empty disables the consumer |
| `KAFKA_TOPIC` | `po.status.changed` | No | Kafka topic for order status events |
| `KAFKA_GROUP_ID` | `orchestrator-ws-broker` | No | Kafka consumer group for the WebSocket broker task |
| `BUYER_NAME` | `Procurement Agent` | No | Buyer display name sent in Beckn init/confirm contracts |
| `BUYER_EMAIL` | `procurement@example.com` | No | Buyer contact email sent in Beckn contracts |
| `BUYER_PHONE` | `+91-0000000000` | No | Buyer phone sent in Beckn contracts |
| `BUYER_ADDRESS_STREET` | `""` | No | Buyer street address |
| `BUYER_ADDRESS_CITY` | `Bangalore` | No | Buyer city |
| `BUYER_ADDRESS_STATE` | `Karnataka` | No | Buyer state |
| `BUYER_ADDRESS_AREA_CODE` | `560100` | No | Buyer PIN code |
| `BUYER_ADDRESS_COUNTRY` | `IND` | No | Buyer country (ISO 3166-1 alpha-3) |

**Note:** The in-memory session store (`_sessions`) has a TTL of 1800 seconds and no persistence. A container restart loses all in-flight compare sessions. See the `TODO(persistence)` note in `Bap-1/src/agent/session.py` for the planned `AsyncPostgresSaver` swap.

---

## beckn-bap-client (:8002)

Manages the Beckn protocol lifecycle (discover/select/init/confirm/status) and handles async `on_discover` callbacks via Redis Pub/Sub. See [ADR-0001](../docs/architecture/decisions/0001-use-redis-pubsub-for-async-beckn-responses.md) for why async discovery is decoupled via Redis.

Source: `services/beckn-bap-client/src/config.py` and `services/beckn-bap-client/src/handler.py`

| Variable | Default | Required | Description |
|---|---|---|---|
| `BAP_ID` | `bap.example.com` | Yes (production) | (NO DEFAULT) Beckn Application Platform identifier registered on the Beckn network. Placeholder must be replaced before connecting to a live network. |
| `BAP_URI` | `http://localhost:8000/beckn` | Yes (production) | (NO DEFAULT) Public callback URI for ONIX to route `on_*` callbacks. Must be publicly reachable in production. Do not append a trailing action name — ONIX appends `/{action}` automatically. |
| `ONIX_URL` | `http://localhost:8081` | Yes | Base URL of the onix-bap Go adapter that handles ED25519 signing and routing |
| `DOMAIN` | `nic2004:52110` | No | Beckn domain code; docker-compose sets `beckn.one/testnet` for sandbox |
| `COUNTRY` | `IND` | No | Buyer country for Beckn context |
| `CITY` | `std:080` | No | Buyer city code for Beckn context |
| `CORE_VERSION` | `2.0.0` | No | Beckn core spec version sent in all request contexts |
| `REQUEST_TIMEOUT` | `30` | No | HTTP request timeout in seconds for outbound Beckn calls |
| `CALLBACK_TIMEOUT` | `10.0` | No | Seconds the `CallbackCollector` waits for on_select/on_init/on_confirm/on_status before raising a timeout |
| `CATALOG_NORMALIZER_URL` | `http://localhost:8005` | Yes | URL of the catalog-normalizer service for on_discover payload normalization |
| `REDIS_URL` | `redis://localhost:6379` | Yes | Redis URL for Pub/Sub. **Exception:** read via `os.getenv()` in `handler.py`, not through Pydantic Settings — must be a real process environment variable, not just in `.env`. Required for `/on_discover` to publish results on `beckn_results:{txn_id}`. |

---

## data-normalizer (:8006)

The sole write path into PostgreSQL. Also hosts the pgvector agent memory endpoints and the audit trail API.

Source: `services/data-normalizer/src/handler.py`

| Variable | Default | Required | Description |
|---|---|---|---|
| `PORT` | `8006` | No | Service listen port |
| `DB_HOST` | `localhost` | Yes | PostgreSQL host; docker-compose sets `host.docker.internal` |
| `DB_PORT` | `5432` | No | PostgreSQL port |
| `DB_NAME` | `procurement_agent` | No | Target database name |
| `DB_USER` | `postgres` | No | Database user |
| `DB_PASSWORD` | `postgres123` | Yes (production) | (SECRET) Database password. Default `postgres123` is trivial — must be changed in any non-local deployment. |
| `FASTEMBED_MODEL` | `BAAI/bge-small-en-v1.5` | No | FastEmbed ONNX model for agent memory embeddings. Model (~130 MB) is downloaded from Hugging Face on first use of the memory write endpoint. |
| `MEMORY_SIMILARITY_THRESHOLD` | `0.7` | No | Cosine similarity floor for agent memory recall |
| `MEMORY_TOP_K` | `5` | No | Maximum number of memory items returned per query |
| `SYSTEM_USER_ID` | `00000000-0000-0000-0000-000000000001` | No | UUID for the fallback system user upserted into `users` when no `requester_id` is provided. Not in docker-compose — hardcoded default is used in all deployments unless overridden. |

**Cold start note:** The `all-MiniLM-L6-v2` model (~90 MB) is downloaded from Hugging Face on first startup of the memory write endpoint. Expect 10–30 seconds of cold start delay.

---

## erp-adapter (:8007)

Vendor-neutral ERP integration with synchronous budget gate, async outbox PO push, and inbound HMAC-signed webhooks. Supports `mock`, `sap`, and `oracle` vendors.

Source: `services/erp-adapter/src/config.py`

| Variable | Default | Required | Description |
|---|---|---|---|
| `PORT` | `8007` | No | Service listen port |
| `ERP_INTERNAL_TOKEN` | `dev-internal-token-CHANGE_ME` | Yes (production) | (SECRET) Bearer token validated on all `/api/v1/*` routes. Default is a public placeholder. |
| `ERP_VENDORS` | `mock` | Yes | Comma-separated vendor list: `mock`, `sap`, `oracle`, or `sap,oracle` |
| `DB_HOST` | `procurement-postgres` | Yes | PostgreSQL host for the outbox table |
| `DB_PORT` | `5432` | No | PostgreSQL port |
| `DB_NAME` | `procurement_agent` | No | Database name |
| `DB_USER` | `postgres` | No | Database user |
| `DB_PASSWORD` | `postgres123` | Yes (production) | (SECRET) Database password |
| `REDIS_URL` | `redis://redis:6379` | No | Redis for fallback ERP state publishing when Kafka is unavailable |
| `KAFKA_BOOTSTRAP` | `""` (disabled) | No | Kafka broker; empty disables the Kafka producer |
| `KAFKA_TOPIC` | `po.status.changed` | No | Topic for PO status change events |
| `ERP_MOCK_BASE_URL` | `http://erp-mock:8008` | No (mock vendor) | Base URL for the erp-mock service |
| `SAP_OAUTH_TOKEN_URL` | `http://erp-mock:8008/sap/oauth2/token` | No (SAP vendor) | SAP OAuth2 token endpoint |
| `SAP_BASE_URL` | `http://erp-mock:8008/sap/opu/...` | No (SAP vendor) | SAP S/4HANA OData base URL |
| `SAP_CLIENT_ID` | `mock-sap-client` | Yes (SAP production) | SAP OAuth2 client ID |
| `SAP_CLIENT_SECRET` | `mock-sap-secret` | Yes (SAP production) | (SECRET) SAP OAuth2 client secret. Default is a public placeholder. |
| `SAP_BUDGET_CHECK_URL` | `http://erp-mock:8008/sap/budget/check` | No (SAP vendor) | SAP-shaped budget check endpoint |
| `SAP_WEBHOOK_HMAC_SECRET` | `dev-sap-hmac-CHANGE_ME` | Yes (production) | (SECRET) Primary HMAC-SHA256 key for verifying `X-Sap-Signature` on inbound SAP webhooks |
| `SAP_WEBHOOK_HMAC_SECRET_NEXT` | `""` (disabled) | No | (SECRET) Rotation key: both primary and `_NEXT` are accepted simultaneously during zero-downtime key rotation |
| `ORACLE_OAUTH_TOKEN_URL` | `http://erp-mock:8008/oauth2/v1/token` | No (Oracle vendor) | Oracle OAuth2 token endpoint |
| `ORACLE_BASE_URL` | `http://erp-mock:8008/fscmRestApi/...` | No (Oracle vendor) | Oracle ERP Cloud REST base URL |
| `ORACLE_CLIENT_ID` | `mock-oracle-client` | Yes (Oracle production) | Oracle OAuth2 client ID |
| `ORACLE_CLIENT_SECRET` | `mock-oracle-secret` | Yes (Oracle production) | (SECRET) Oracle OAuth2 client secret. Default is a public placeholder. |
| `ORACLE_BUDGET_CHECK_URL` | `http://erp-mock:8008/oracle/budget/check` | No (Oracle vendor) | Oracle-shaped budget check endpoint |
| `ORACLE_WEBHOOK_HMAC_SECRET` | `dev-oracle-hmac-CHANGE_ME` | Yes (production) | (SECRET) Primary HMAC-SHA256 key for Oracle webhook verification |
| `ORACLE_WEBHOOK_HMAC_SECRET_NEXT` | `""` (disabled) | No | (SECRET) Oracle HMAC rotation key |
| `BREAKER_FAIL_MAX` | `5` | No | Per-vendor circuit breaker consecutive failure threshold before tripping to OPEN |
| `BREAKER_RESET_TIMEOUT_SECS` | `60` | No | Seconds in OPEN state before auto-probe (half-open transition) |
| `BUDGET_CHECK_TOTAL_TIMEOUT_MS` | `800` | No | Hard timeout for the synchronous budget gate; orchestrator mirrors this as `ERP_BUDGET_CHECK_TIMEOUT_MS` |
| `WORKER_CONCURRENCY` | `10` | No | Concurrent outbox worker coroutines |
| `WORKER_BACKOFF_CSV` | `5,30,120,600,3600` | No | Retry backoff delays in seconds (5 attempts total, up to 1 hour) |
| `WORKER_POLL_INTERVAL_SECONDS` | `2.0` | No | How often the outbox worker polls for pending rows |
| `LOG_PAYLOADS` | `false` | No | When `true`, full request/response bodies are logged. **Never set `true` in production** — logs contain PII and financial data. |

**Dual-secret HMAC rotation protocol:**

To rotate a webhook secret with no downtime: (1) set `_NEXT` to the new secret and deploy; (2) update the ERP vendor to sign with the new key; (3) verify new-key signatures are arriving; (4) promote `_NEXT` value to the primary variable; (5) clear `_NEXT`.

---

## erp-mock (:8008)

Local ERP stub for development. All state is in-memory and non-durable. Not used in production.

Source: `services/erp-mock/src/config.py`

| Variable | Default | Required | Description |
|---|---|---|---|
| `PORT` | `8008` | No | Service listen port |
| `MOCK_SCENARIO` | `happy` | No | Active scenario: `happy`, `budget_exhausted`, `po_create_fails`, `webhook_delayed`, `erp_approval_required`, `erp_preferred_supplier`. Can also be overridden per-request with the `X-Mock-Scenario` header. |
| `WEBHOOK_TARGET_URL` | `http://erp-adapter:8007` | No | Target URL for automatic webhook callbacks after `/mock/po/create` |
| `WEBHOOK_DELAY_SECONDS` | `2.0` | No | Seconds to wait before posting the inbound webhook back to erp-adapter |
| `SAP_WEBHOOK_HMAC_SECRET` | `dev-sap-hmac-CHANGE_ME` | No | HMAC key used to sign outbound mock SAP webhooks; must match `SAP_WEBHOOK_HMAC_SECRET` in erp-adapter |
| `ORACLE_WEBHOOK_HMAC_SECRET` | `dev-oracle-hmac-CHANGE_ME` | No | Oracle HMAC signing key (reserved for future use; mock emitter currently does not emit Oracle webhooks) |

---

## mcp-sidecar (:3000)

MCP SSE bridge between IntentParser and the Beckn BAP client. Runs locally, not in Docker.

Source: `services/mcp-sidecar/config.py` and `services/mcp-sidecar/bap_client.py`

Start command (inside `conda activate infosys_project`):
```bash
cd services/mcp-sidecar && BAP_API_KEY="any-dev-string" uvicorn server:app --port 3000
```

| Variable | Default | Required | Description |
|---|---|---|---|
| `PORT` | `3000` | No | SSE server listen port |
| `BAP_CLIENT_URL` | `http://localhost:8002` | Yes | URL of beckn-bap-client's `/discover` endpoint |
| `BAP_API_KEY` | (none) | Yes (NO DEFAULT) | (SECRET) Bearer token for the BAP client API. **Service refuses to start without it.** Any non-empty string works in dev. Must not be committed to source control. |
| `REDIS_URL` | `redis://localhost:6379` | Yes | **Exception:** read via `os.getenv()` in `bap_client.py`, not through Pydantic Settings. Must be a real process environment variable, not just in `.env`. Required for publishing on `beckn_results:{txn_id}`. |
| `REDIS_RESULT_TIMEOUT` | `15` | Yes | **Exception:** also read via `os.getenv()`. Seconds to wait for a result on the Redis channel before returning `{"found": false}`. This is the primary latency ceiling for discovery probes. |
| `MCP_BAP_TIMEOUT` | `3.0` | No | HTTP safety valve for the fire-and-forget POST to beckn-bap-client. Governs only the HTTP layer, not the Redis wait. |
| `RANKING_MIN_SIMILARITY` | `0.30` | No | Cosine similarity floor; items below this threshold are filtered from discovery results |

---

## negotiation_engine

Port `8004` on the container; published as `18004` on the host to avoid collision with the orchestrator which also maps `8004`.

Source: `services/negotiation_engine/src/config.py`

| Variable | Default | Required | Description |
|---|---|---|---|
| `NEGOTIATION_API_HOST` | `0.0.0.0` | No | FastAPI bind host |
| `NEGOTIATION_API_PORT` | `8004` | No | FastAPI listen port |
| `NEGOTIATION_LOG_LEVEL` | `INFO` | No | Log verbosity |
| `OPENAI_API_KEY` | `None` | No | API key sent to the LLM endpoint. Since the target is the local `claude_openai_proxy` at `:8012`, any non-empty string is accepted. |
| `NEGOTIATION_OPENAI_BASE_URL` | `http://host.docker.internal:8012/v1` | Yes | Base URL for the OpenAI-compatible LLM endpoint. Points at the `claude_openai_proxy` service which must be running on the host at port `8012`. |
| `NEGOTIATION_OPENAI_MODEL` | `claude-3-5-sonnet` | No | Model name sent to the proxy; mapped to the Claude alias in `claude_openai_proxy/config.py` |
| `NEGOTIATION_OPENAI_TIMEOUT_S` | `30.0` | No | LLM call timeout in seconds |
| `NEGOTIATION_ADVISORY_MAX_TOKENS` | `512` | No | Max token budget for advisory LLM node responses |
| `REDIS_URL` | `redis://localhost:6379/0` | Yes | Redis URL for async on_select callback transport |
| `NEGOTIATION_REDIS_ON_SELECT_CHANNEL` | `beckn_on_select_results` | No | Redis channel the `OnSelectListener` subscribes to for resuming parked LangGraph states |
| `NEGOTIATION_REDIS_HITL_PREFIX` | `negotiation_hitl_decisions` | No | Redis channel prefix for human-in-the-loop override signals |
| `NEGOTIATION_POSTGRES_DSN` | `None` (disabled) | No | PostgreSQL DSN for durable LangGraph checkpointing via `AsyncPostgresSaver`. When unset, falls back to in-memory `MemorySaver` — **all in-flight negotiation states are lost on restart**. |
| `KAFKA_BOOTSTRAP_SERVERS` | `None` (disabled) | No | Kafka broker for audit event publishing; fail-open when unset |
| `NEGOTIATION_KAFKA_TOPIC` | `procurement.negotiation.v1` | No | Kafka topic for negotiation audit events |
| `NEGOTIATION_KAFKA_POLICY_VIOLATIONS_TOPIC` | `procurement.negotiation.policy_violations.v1` | No | Topic for policy violation events |
| `NEGOTIATION_KAFKA_DLQ_TOPIC` | `procurement.negotiation.dlq.v1` | No | Dead-letter queue topic |
| `NEGOTIATION_KAFKA_CLIENT_ID` | `negotiation-engine` | No | Kafka producer client ID |
| `QDRANT_URL` | `None` (disabled) | No | Qdrant URL for agent memory. Unused in the as-built system — pgvector is the sole vector store. |
| `QDRANT_API_KEY` | `None` (disabled) | No | Qdrant API key; unused in as-built system |
| `LANGCHAIN_TRACING_V2` | `false` | No | Set `true` to enable LangSmith tracing (Phase 4 target) |
| `LANGCHAIN_ENDPOINT` | `https://api.smith.langchain.com` | No | LangSmith API endpoint |
| `LANGCHAIN_API_KEY` | `None` | No (required if tracing enabled) | (SECRET) LangSmith API key; tracing is skipped silently when unset |
| `LANGCHAIN_PROJECT` | `procurement-negotiation-prod` | No | LangSmith project name |

**Note:** `NEGOTIATION_OPENAI_BASE_URL` requires the `claude_openai_proxy` service running on the host with `CLAUDE_PROXY_HOST=0.0.0.0` (the systemd unit sets this). The proxy is not part of `docker-compose.yml` and must be started separately.

---

## notification-dispatcher (:8010)

Kafka consumer that fans out order status events to Slack, Teams, and email. Container port `8010` is not published to the host in `docker-compose.yml`. The consumer loop never starts when `KAFKA_BOOTSTRAP` is empty — no notifications are sent in the default dev setup.

Source: `services/notification-dispatcher/src/config.py`

| Variable | Default | Required | Description |
|---|---|---|---|
| `KAFKA_BOOTSTRAP` | `""` (disabled) | Yes (for notifications) | Kafka broker address. Empty disables the consumer entirely. |
| `KAFKA_TOPIC` | `po.status.changed` | No | Kafka topic to consume for order status events |
| `KAFKA_GROUP_ID` | `notification-dispatcher` | No | Kafka consumer group ID |
| `SLACK_WEBHOOK_URL` | `""` (disabled) | No | (SECRET) Slack incoming webhook URL; empty disables the Slack channel |
| `TEAMS_WEBHOOK_URL` | `""` (disabled) | No | (SECRET) Microsoft Teams webhook URL; empty disables the Teams channel |
| `SMTP_HOST` | `""` (disabled) | No | SMTP server hostname; empty disables the email channel |
| `SMTP_PORT` | `587` | No | SMTP port (STARTTLS) |
| `SMTP_USER` | `""` | No | (SECRET) SMTP authentication username |
| `SMTP_PASSWORD` | `""` | No | (SECRET) SMTP authentication password |
| `SMTP_FROM` | `noreply@procurement-agent.local` | No | From address for order email notifications |
| `DB_HOST` | `localhost` | No | PostgreSQL host for recipient email lookup |
| `DB_PORT` | `5432` | No | PostgreSQL port |
| `DB_NAME` | `procurement_agent` | No | Database name |
| `DB_USER` | `""` (disabled) | No | Database user for email recipient lookup. Empty skips DB lookup and disables email recipient resolution. |
| `DB_PASSWORD` | `""` | No | (SECRET) Database password |

**Notification routing by order status:**

| Status | Slack | Teams | Email |
|---|---|---|---|
| `confirmed` | Yes | Yes | Yes |
| `shipped` | Yes | Yes | No |
| `delivered` | Yes | Yes | Yes |
| `cancelled` | Yes | Yes | No |
| Anything else | No | No | No |

---

## sim-bpp (:3002)

Local Beckn BPP simulator written in Node.js (Express). Replaced `fidedocker/sandbox-2.0`. Catalog hot-reloads from a bind-mounted JSON file — no restart needed to update products.

Source: `services/sim-bpp/`

| Variable | Default | Required | Description |
|---|---|---|---|
| `PORT` | `3002` | No | Service listen port |
| `ONIX_BPP_CALLER` | `http://onix-bpp:8082/bpp/caller` | Yes | Base URL of the onix-bpp caller module. sim-bpp appends `/on_{action}` when posting callbacks. |
| `BPP_ID` | `bpp.example.com` | No | BPP identifier embedded in all response contexts |
| `BPP_URI` | `http://onix-bpp:8082/bpp/receiver` | No | BPP receiver URI sent in catalog responses so ONIX can route transactions back |
| `CATALOG_PATH` | `/app/catalog.json` | No | Path to the catalog JSON file. Bind-mounted at `./services/sim-bpp/catalog.json` in docker-compose. Re-read on every request. |
| `SIM_BPP_AUTO_ADVANCE` | `false` (code default) | No | **Set to `true` in docker-compose.yml.** When enabled, auto-advances a confirmed order through `ACCEPTED → PACKED → SHIPPED → OUT_FOR_DELIVERY → DELIVERED` at the configured interval. |
| `SIM_BPP_ADVANCE_INTERVAL_SECS` | `5` | No | Seconds between each auto-advance lifecycle step |
| `KAFKA_BOOTSTRAP` | `""` (disabled) | No | Kafka broker for publishing `po.status.changed` events during auto-advance |
| `KAFKA_TOPIC` | `po.status.changed` | No | Kafka topic for lifecycle events |
| `DATA_NORMALIZER_URL` | `http://data-normalizer:8006` | Yes (auto-advance) | URL for PATCHing `purchase_orders.status` during lifecycle transitions |

**Important:** `SIM_BPP_AUTO_ADVANCE` defaults to `false` in code but `true` in docker-compose. Running sim-bpp locally (not in Docker) without setting this variable produces no automatic lifecycle transitions.

---

## frontend (Next.js, :3000)

Next.js 13.5 App Router. Authentication is enforced exclusively via NextAuth v4 with KeycloakProvider. There is no stub credentials provider and no dev-mode bypass.

Source: `frontend/.env.example`, `frontend/src/lib/auth.ts`, `frontend/src/lib/api.ts`

| Variable | Default | Required | Description |
|---|---|---|---|
| `NEXTAUTH_URL` | `http://localhost:3000` | Yes | Public URL of this Next.js app. Must exactly match the redirect URI registered in the Keycloak client. Use an HTTPS URL in production. |
| `NEXTAUTH_SECRET` | (none) | Yes (NO DEFAULT) | (SECRET) Secret used to sign and verify session JWTs. Generate with `openssl rand -base64 32`. Empty string is invalid — NextAuth throws at startup. |
| `KEYCLOAK_ISSUER` | `https://euc1.auth.ac/auth` | Yes | OIDC issuer URL. Production Phase Two cloud: `https://app.phasetwo.io/auth/realms/<realm>`. Self-hosted: `https://<host>/realms/<realm>`. Defaults to the Phase Two dev tenant — must be overridden for any non-dev environment. |
| `KEYCLOAK_CLIENT_ID` | `procurement-frontend` | Yes | Client ID in the Keycloak realm |
| `KEYCLOAK_CLIENT_SECRET` | (none) | Yes (NO DEFAULT) | (SECRET) Client secret (confidential client). Copy from the Keycloak dashboard. |
| `NEXT_PUBLIC_API_BASE_URL` | `http://localhost:8000` | Yes | Orchestrator base URL. Matches the orchestrator's host port `8000` mapping in docker-compose. |

**Keycloak client minimum requirements:**

| Setting | Required value |
|---|---|
| Client authentication | ON (confidential client) |
| Standard flow | Enabled |
| Valid Redirect URIs | `${NEXTAUTH_URL}/api/auth/callback/keycloak` |
| Web origins | `${NEXTAUTH_URL}` |
| Realm roles mapper (`realm_access.roles`) | Add to ID token: ON |

**Roles:** `admin`, `approver`, `requester`. Unknown roles default to `requester`.

**Important:** No Keycloak setup guide or realm export exists in the repository. A developer cloning the repo cannot authenticate to the frontend without access to the configured Phase Two tenant or a self-hosted Keycloak realm with matching client settings.

---

## comparative-scoring (:8003)

Thin HTTP adapter forwarding to the `prediction-api` MLOps service; falls back to a min-price heuristic when the ML service is unavailable.

Source: `services/comparative-scoring/src/handler.py`

| Variable | Default | Required | Description |
|---|---|---|---|
| `PREDICTION_API_URL` | `http://prediction-api:8004` | No | URL of the MLOps `prediction-api` service under `services/ComparativeAndScoreing/`. Must be reachable if ML scoring is required. Start the MLOps stack separately: `docker compose -f services/ComparativeAndScoreing/docker-compose.mlops.yaml up prediction-api` |
| `PREDICTION_TIMEOUT_S` | `8.0` | No | Timeout in seconds waiting for prediction-api before triggering fallback |
| `SCORING_FALLBACK_ENABLED` | `true` | No | When `true`, a prediction-api failure falls back to the Phase 1 min-price heuristic. Set `false` for canary deploys that must surface ML failures. |

---

## analytics (:8009)

Dashboard reporting queries. Returns HTTP 503 (not mock data) when the DB connection pool is unavailable.

Source: `docker-compose.yml` analytics service environment block

| Variable | Default | Required | Description |
|---|---|---|---|
| `PORT` | `8009` | No | Service listen port |
| `DB_HOST` | `localhost` | Yes | PostgreSQL host; docker-compose sets `host.docker.internal` |
| `DB_PORT` | `5432` | No | PostgreSQL port |
| `DB_NAME` | `procurement_agent` | No | Database name |
| `DB_USER` | `postgres` | No | Database user |
| `DB_PASSWORD` | `postgres123` | Yes (production) | (SECRET) Database password; default is trivial |

---

## claude_openai_proxy (local host service, :8012)

OpenAI-compatible proxy that wraps the host `claude` CLI binary. Required by the negotiation_engine and demo gateway. **Not in `docker-compose.yml`** — must be started separately on the host.

Source: `services/claude_openai_proxy/config.py` and `services/claude_openai_proxy/claude-proxy.service`

Start commands:
```bash
# Local dev (loopback only)
uvicorn services.claude_openai_proxy.main:app --host 127.0.0.1 --port 8012

# As a systemd unit (allows Docker bridge access)
systemctl --user enable --now claude-proxy
```

| Variable | Default | Required | Description |
|---|---|---|---|
| `CLAUDE_PROXY_KEY` | `""` (auth disabled) | Yes (production) | (SECRET) Bearer token for all `/v1/*` routes. Empty disables auth with a startup warning — any client can trigger Claude CLI invocations that bill the host account. |
| `CLAUDE_PROXY_HOST` | `127.0.0.1` | No | Bind host. Set `0.0.0.0` in the systemd unit so Docker-bridged containers reach it via `host.docker.internal:8012`. |
| `CLAUDE_PROXY_PORT` | `8012` | No | Listen port |
| `CLAUDE_PROXY_BINARY_PATH` | `/home/carbaje/.local/bin/claude` | Yes (NO DEFAULT) | Absolute path to the `claude` CLI binary. Hardcoded to a specific user home directory — **must be updated on every machine**. |
| `CLAUDE_PROXY_DEFAULT_MODEL` | `sonnet` | No | Claude alias used when the requested OpenAI model name has no mapping |
| `CLAUDE_PROXY_MAX_CONCURRENCY` | `2` | No | Maximum concurrent `claude -p` subprocess invocations. Excess requests queue, not reject. |
| `CLAUDE_PROXY_TIMEOUT_S` | `120.0` | No | Hard subprocess timeout; CLI is killed if no output arrives within this window |
| `CLAUDE_PROXY_DISABLE_TOOLS` | `true` | No | When `true`, all acting/IO tools (`Bash`, `Edit`, `Write`, `Read`, etc.) are disallowed in `claude -p` mode to prevent interactive permission hangs |
| `CLAUDE_PROXY_PERMISSION_MODE` | `default` | No | Claude permission mode passed to the CLI |
| `CLAUDE_PROXY_INCLUDE_PARTIAL` | `true` | No | Whether to stream partial assistant text before the final result |

**OpenAI → Claude model mapping:**

| OpenAI name | Claude alias |
|---|---|
| `gpt-4o`, `gpt-4-turbo`, `gpt-4` → | `sonnet` / `sonnet` / `opus` |
| `gpt-4o-mini`, `gpt-3.5-turbo` → | `haiku` |
| `claude-3-5-sonnet` → | `sonnet` |
| `claude-3-5-haiku` → | `haiku` |

Names starting with `claude` pass through unchanged. `temperature`, `top_p`, and `max_tokens` are accepted but silently ignored — the Claude CLI has no sampling knobs.

---

## Secrets Required in Production

All variables marked (SECRET) must be set to non-default values before any environment reachable from an untrusted network. The table below consolidates the critical ones with the consequence of leaving them at default.

| Variable | Service(s) | Risk if not replaced |
|---|---|---|
| `NEXTAUTH_SECRET` | frontend | Session JWTs are effectively unsigned; any crafted JWT is accepted |
| `KEYCLOAK_CLIENT_SECRET` | frontend | OIDC flow breaks; no user can authenticate |
| `KEYCLOAK_ISSUER` | frontend | Defaults to the Phase Two dev tenant; all auth routes to the wrong realm |
| `ERP_INTERNAL_TOKEN` | orchestrator, erp-adapter | Default `dev-internal-token-CHANGE_ME` is public knowledge; any caller can invoke `/api/v1/*` on erp-adapter |
| `SELLER_WEBHOOK_HMAC_SECRET` | orchestrator | Default `dev-seller-hmac-CHANGE_ME` is public; forged seller webhooks pass signature verification |
| `SAP_WEBHOOK_HMAC_SECRET` | erp-adapter, erp-mock | Default `dev-sap-hmac-CHANGE_ME` is public; forged SAP webhooks accepted |
| `ORACLE_WEBHOOK_HMAC_SECRET` | erp-adapter, erp-mock | Default `dev-oracle-hmac-CHANGE_ME` is public; forged Oracle webhooks accepted |
| `SAP_CLIENT_SECRET` | erp-adapter | Default `mock-sap-secret` is public; applies only when `ERP_VENDORS=sap` |
| `ORACLE_CLIENT_SECRET` | erp-adapter | Default `mock-oracle-secret` is public; applies only when `ERP_VENDORS=oracle` |
| `DB_PASSWORD` | data-normalizer, analytics, erp-adapter, notification-dispatcher | Default `postgres123` is trivial; grants full database write access to all tables |
| `BAP_API_KEY` | mcp-sidecar | Service refuses to start without it; any non-empty string works in dev but should be a strong secret in production |
| `CLAUDE_PROXY_KEY` | claude_openai_proxy | Auth disabled when empty; any host-reachable client can trigger Claude CLI calls that bill the host Anthropic account |
| `CLAUDE_PROXY_BINARY_PATH` | claude_openai_proxy | Hardcoded to `/home/carbaje/.local/bin/claude`; service fails silently on every other machine |
| `BAP_ID` | beckn-bap-client | Placeholder `bap.example.com`; must match the registered BAP identifier on the target Beckn network |
| `BAP_URI` | beckn-bap-client | Defaults to `localhost`; ONIX cannot route on_* callbacks to a non-public URL |

**Key rotation support:** erp-adapter implements dual-secret HMAC rotation for SAP and Oracle webhook secrets. Set the `_NEXT` variant during rotation to accept both old and new signatures simultaneously — see the [erp-adapter section](#erp-adapter-8007) for the five-step rotation procedure.

---

## Dev vs Production Differences

Variables where the development default is intentionally unsafe, non-functional, or points at local stubs.

| Variable | Dev / docker-compose value | Production requirement | Risk if ignored in production |
|---|---|---|---|
| `ERP_BUDGET_CHECK_REQUIRED` | `false` (fail-open) | `true` (fail-closed) | Budget overruns pass through if erp-adapter is unreachable |
| `LOG_PAYLOADS` (erp-adapter) | `false` | Must remain `false` | `true` logs full PO and budget payloads containing PII and financial data |
| `SIM_BPP_AUTO_ADVANCE` | `true` (docker-compose) | Not applicable — sim-bpp is replaced by a live Beckn network BPP | No risk in production; sim-bpp is a dev-only service |
| `COMPLEX_MODEL` (IntentParser) | `qwen3:1.7b` (docker-compose override) | Restore to `qwen3:8b` on a GPU-capable host | Two-tier complexity routing is collapsed; all queries use the lighter model, reducing extraction quality |
| `CLAUDE_PROXY_HOST` | `127.0.0.1` (loopback, local dev) | `0.0.0.0` (systemd unit with UFW restricting to Docker bridge `172.16.0.0/12`) | Docker-bridged containers (negotiation_engine, demo gateway) cannot reach the proxy |
| `NEGOTIATION_POSTGRES_DSN` | Unset (`MemorySaver`) | Valid PostgreSQL DSN for `AsyncPostgresSaver` | All in-flight negotiation states are lost on every container restart |
| `KAFKA_BOOTSTRAP` | `""` (disabled in all services) | Kafka broker address across all services | No event-driven fan-out: no notifications, no audit trail, no real-time tracking. Kafka is deferred to Phase 4. |
| `NEXTAUTH_URL` | `http://localhost:3000` | Public HTTPS hostname matching the Keycloak redirect URI exactly | OIDC callback fails; no user can complete login |
| `LANGCHAIN_TRACING_V2` | `false` | `true` with a valid `LANGCHAIN_API_KEY` | No LangSmith observability for negotiation LangGraph traces (Phase 4 target) |
| `DB_HOST` (all services) | `host.docker.internal` (docker-compose) | Container DNS name (`procurement-postgres`) or managed PostgreSQL hostname | Services cannot reach the database |
| `DOMAIN` (beckn-bap-client) | `nic2004:52110` (code) / `beckn.one/testnet` (docker-compose) | Real Beckn network domain for the target industry vertical | Discover requests route to the testnet instead of the live network |
| `SAP_OAUTH_TOKEN_URL`, `SAP_BASE_URL`, `ORACLE_OAUTH_TOKEN_URL`, `ORACLE_BASE_URL` | Point at `erp-mock:8008` | Real SAP S/4HANA or Oracle ERP Cloud endpoints | All ERP calls hit the local mock; no real budget checks or PO creation |
