# Troubleshooting Guide

This guide is for developers who need to diagnose and fix problems in the Procurement Agent on Beckn Protocol system. For architecture context see [ARCHITECTURE.md](ARCHITECTURE.md). For deployment setup see [DEPLOYMENT.md](DEPLOYMENT.md).

---

## 1. Service Health Check

### 1.1 Health Endpoints

The table below covers every service in the stack. Three services run on the host outside Docker (marked **local**); the rest are addressed via their published host ports.

| Service | Health URL | Expected HTTP status | Key fields in response | Notes |
|---|---|---|---|---|
| orchestrator | `http://localhost:8000/health` | 200 | — | Dual-mapped to host ports 8000 and 8004 |
| beckn-bap-client | `http://localhost:8002/health` | 200 | — | — |
| comparative-scoring | `http://localhost:8003/health` | 200 | — | ML path active only when prediction-api is up |
| catalog-normalizer | `http://localhost:8005/health` | 200 | — | — |
| data-normalizer | `http://localhost:8006/health` | 200 | — | — |
| erp-adapter | `http://localhost:8007/readyz` | 200 | `circuit_breakers`, `db`, `redis` | Only confirmed `/readyz` endpoint in the stack; reports per-vendor circuit state |
| erp-mock | `http://localhost:8008/health` | 200 | — | Default `ERP_VENDORS=mock` |
| analytics | `http://localhost:8009/health` | 200 | — | Returns 503 when PostgreSQL is unavailable |
| negotiation-engine | `http://localhost:18004/readyz` | 200 | — | Host port 18004; container port 8004 |
| demo-gateway | `http://localhost:8015/health` | 200 | — | Required for autonomous negotiation |
| sim-bpp | `http://localhost:3002/health` | 200 | — | — |
| onix-bap | `http://localhost:8081/health` | 200 | — | ONIX Go adapter; schema validator pinned to `d43ec30d` |
| onix-bpp | `http://localhost:8082/health` | 200 | — | — |
| mcp-sidecar | `http://localhost:3000/health` | 200 | `status` | **local** — must be started manually |
| IntentParser | `http://localhost:8001/health` | 200 | — | **local** for Stage 1+2+3; Docker wrapper is Stage 1+2 only |
| claude_openai_proxy | `http://localhost:8012/health` | 200 | — | **local** — required for negotiation demo flows |
| redis | `redis-cli -p 6379 PING` | `PONG` | — | Via Docker: `docker exec $(docker compose ps -q redis) redis-cli PING` |
| kafka | internal healthcheck only | — | — | `kafka-broker-api-versions.sh` run inside container |

### 1.2 Check All Docker Services at Once

```bash
# Show container names, status, and health from the repo root
docker compose ps

# Spot-check every HTTP service in one pass (host-accessible ports only)
for entry in \
    "orchestrator:8000" \
    "beckn-bap-client:8002" \
    "comparative-scoring:8003" \
    "catalog-normalizer:8005" \
    "data-normalizer:8006" \
    "erp-adapter:8007/readyz" \
    "erp-mock:8008" \
    "analytics:8009" \
    "sim-bpp:3002" \
    "demo-gateway:8015" \
    "negotiation-engine:18004/readyz" \
    "mcp-sidecar:3000" \
    "intention-parser:8001"; do
  name="${entry%%:*}"
  rest="${entry#*:}"
  port="${rest%%/*}"
  path="${rest#*/}"
  [ "$path" = "$rest" ] && path="health"
  code=$(curl -s -o /dev/null -w "%{http_code}" "http://localhost:${port}/${path}" 2>/dev/null || echo "UNREACHABLE")
  printf "%-30s HTTP %s\n" "$name" "$code"
done
```

---

## 2. Common Issues

### 2.1 Natural Language Parsing

#### Stage 3 returns `"found": false` for every query

**Symptom.** Every call to `/parse/full` returns `validation_status: "not_found"` or `mcp_validated: false` regardless of the search term.

**Cause.** The mcp-sidecar process is not running, or its Redis connection is broken.

**Diagnosis.**
```bash
# 1. Confirm the process is listening
curl http://localhost:3000/health

# 2. If down, start it
conda activate infosys_project
cd services/mcp-sidecar
export BAP_API_KEY="dev-key"
export REDIS_URL="redis://localhost:6379"   # must be a real env var, not just in .env
uvicorn server:app --port 3000

# 3. Verify Redis is reachable from the sidecar's perspective
redis-cli -u redis://localhost:6379 PING
```

**Note.** `REDIS_URL` and `REDIS_RESULT_TIMEOUT` must be exported shell variables, not merely set in a `.env` file, because `bap_client.py` reads them via `os.getenv()` at import time.

---

#### qwen3 model error / LLM call timeout

**Symptom.** Stage 1 or Stage 2 returns an error such as `OllamaRequestError` or a timeout; BecknIntent fields are populated with `null`.

**Cause.** Ollama is not running, the model has not been pulled, or the `OLLAMA_BASE_URL` env var points to the wrong host.

**Diagnosis and fix.**
```bash
# Check Ollama is responding
curl http://localhost:11434/api/tags

# Pull required models (first-time or after image prune)
ollama pull qwen3:8b
ollama pull qwen3:1.7b

# If running IntentParser inside Docker, the container calls host Ollama via
# host.docker.internal:11434. Verify the bridge is reachable from inside the container:
docker exec $(docker compose ps -q intention-parser) \
  curl -s http://host.docker.internal:11434/api/tags
```

**Note (Docker vs local).** The `intention-parser` Docker container overrides `COMPLEX_MODEL=qwen3:1.7b` (see `docker-compose.yml`), collapsing both routing branches to the 1.7b model. The full two-tier routing (`qwen3:8b` for complex queries) only operates when IntentParser is run locally outside Docker. If quality on complex queries is under investigation, use the local process.

---

#### BecknIntent fields are null after Stage 2

**Symptom.** `/parse/full` succeeds with HTTP 200 but critical fields such as `quantity`, `delivery_timeline`, or `location_coordinates` are `null`.

**Cause.** Stage 2 LLM extraction failed silently; `instructor` exhausted `max_retries=3` and returned a partially populated model.

**Diagnosis.**
```bash
# Enable verbose logging
INTENT_PARSER_TEST_MODE=live uvicorn api:app --port 8001 --reload

# Re-run the failing query with full logging
curl -X POST http://localhost:8001/parse/full \
  -H "Content-Type: application/json" \
  -d '{"query": "<your query here>"}'
```

Watch the log output for `instructor` retry attempts. Common causes: the query is ambiguous (LLM cannot extract a numeric quantity), or `delivery_timeline` unit confusion (hours vs days). The anti-corruption layer normalises `delivery_timeline` to **integer hours** and `location_coordinates` to `"lat,lon"` decimal strings — check that Stage 2 output conforms before passing to Stage 3.

---

#### Stage 3 recovery flow does not notify the buyer or trigger an RFQ

**Expected behaviour.** When Stage 3 returns `not_found` after query broadening, the recovery chain calls `log_unmet_demand`, `notify_buyer_no_stock`, and `trigger_open_rfq_flow`.

**Current status.** All three functions in `IntentParser/recovery.py` are logger-only stubs. They print to stdout (`UNMET_DEMAND`, `BUYER_NOTIFY`, `OPEN_RFQ` prefixes) and do not call any external service. This is a known limitation with no assigned owner. See [Known Limitations](#3-known-limitations-expected-behavior).

---

### 2.2 Beckn Discovery

#### `on_discover` never arrives — timeout after `REDIS_RESULT_TIMEOUT`

**Symptom.** The mcp-sidecar waits the full 15 seconds and returns `{"found": false, "items": [], "probe_latency_ms": 15000}`. The orchestrator path returns an empty offerings list.

**Cause A — Redis Pub/Sub not working.**
```bash
# Open a subscriber in one terminal to watch the channel
redis-cli SUBSCRIBE beckn_results:test

# Fire a discovery in another terminal
curl -X POST http://localhost:8002/discover \
  -H "Content-Type: application/json" \
  -d '{"transaction_id":"test","item":"Cat6 cable"}'

# If nothing appears on the subscriber within 10 s, the on_discover callback
# is not reaching Redis. Check the beckn-bap-client log:
docker compose logs -f beckn-bap-client
```

**Cause B — `on_discover` routing misconfigured.**
Check `config/generic-routing-BAPReceiver.yaml`. The `target` URL must **not** include the action name — ONIX appends it automatically. Correct: `http://beckn-bap-client:8002`. Wrong: `http://beckn-bap-client:8002/on_discover` (causes a 404 double-path error).

**Cause C — Redis unavailable at the moment `on_discover` fires.**
If Redis was unreachable when the `/on_discover` webhook arrived, the handler logs a warning and falls back to the `CallbackCollector` queue only. The mcp-sidecar has no retry; it times out after `REDIS_RESULT_TIMEOUT` seconds.

---

#### ONIX routing returns 404 on Beckn actions

**Symptom.** `docker compose logs onix-bap` shows 404 responses when routing `discover`, `select`, `init`, or `confirm`.

**Cause.** The action name is included in the target URL in a routing YAML file. ONIX appends the action name automatically; including it in the YAML doubles the path.

**Fix.** Open the relevant file in `config/` and remove the trailing action from the `target` field.

```yaml
# WRONG — results in http://host:8002/on_discover/on_discover
target: http://beckn-bap-client:8002/on_discover

# CORRECT — ONIX appends /on_discover itself
target: http://beckn-bap-client:8002
```

---

#### Schema validation failure at ONIX — Beckn message rejected

**Symptom.** `docker compose logs onix-bap` shows a schema validation error for a `Contract` field or a `status.code` value.

**Common causes and fixes.**

| Mistake | Fix |
|---|---|
| `Contract.status.code = "CONFIRMED"` | Use `DRAFT`, `ACTIVE`, `CANCELLED`, or `COMPLETE` |
| Billing address placed directly inside `Contract` | Move to `participants[role=buyer]` |
| Fulfillment placed directly inside `Contract` | Move to `performance[]` |
| Payment placed directly inside `Contract` | Move to `settlements[]` |
| Action name appended to routing `target` URL | Remove it (see previous item) |

The ONIX schema validator is pinned to commit `d43ec30d`. Do not upgrade the `fidedocker/onix-adapter` image before running an end-to-end signing test — later commits introduced a `$ref` resolution bug in `SignatureHeader` / `AckSignatureHeader`.

---

#### sim-bpp returns zero results for multi-noun queries

**Symptom.** Discovery returns an empty `on_discover` catalog for queries containing two product categories (e.g. `"office supplies and networking cable"`).

**Cause.** sim-bpp tokenises the query and applies AND-logic: every non-filler token must match at least one item. No single item matches tokens from two unrelated categories simultaneously.

**Workaround.** Issue one discovery per product category, or edit `services/sim-bpp/catalog.json` (bind-mounted at runtime — no container rebuild needed) to add an item that matches the combined tokens.

---

### 2.3 Database

#### Migration fails with FK violation

**Symptom.** `python setup_database.py` exits with a PostgreSQL FK constraint error midway through applying migrations.

**Cause.** Migration files were reordered. The 24 SQL scripts in `database/sql/` must execute in lexicographic order because FK dependencies follow the numeric prefix chain.

**Fix.** Restore the original filenames and ordering. Do not renumber existing files — add new migrations at the next free prefix only.

```bash
ls database/sql/ | sort   # verify lexicographic order looks correct
python setup_database.py --continue-on-exists
```

---

#### pgvector extension missing

**Symptom.** `CREATE EXTENSION IF NOT EXISTS vector` error during schema setup, or `column "embedding" is of type vector but expression is of type text` errors at runtime.

**Fix.** The extension must be installed in the `procurement_agent` database.

```bash
docker exec -it procurement-postgres \
  psql -U postgres -d procurement_agent \
  -c "CREATE EXTENSION IF NOT EXISTS vector;"
```

Verify the `pgvector/pgvector:pg16` image is used — the standard `postgres:16` image does not include the vector extension.

---

#### `agent_memory_vectors` inserts fail with "invalid input value for enum"

**Symptom.** The data-normalizer returns `{"stored": false}` for all memory writes, and PostgreSQL logs show `invalid input value for enum embedding_model_type`.

**Root cause.** The base ENUM in `database/sql/00_extensions_and_types.sql` defines only `text-embedding-3-large` and `e5-large-v2`. Migration `22_agent_memory_vector_dim.sql` adds `all-MiniLM-L6-v2`, but `BAAI/bge-small-en-v1.5` (used by the data-normalizer memory service) is absent from all migration files.

**Fix.** Apply migration 22 if not already applied, then manually add the missing value:

```bash
docker exec -it procurement-postgres \
  psql -U postgres -d procurement_agent \
  -c "ALTER TYPE embedding_model_type ADD VALUE IF NOT EXISTS 'BAAI/bge-small-en-v1.5';"
```

Similarly, `ai_provider_type` lacks `ollama`. Add it if model governance inserts are failing:

```bash
docker exec -it procurement-postgres \
  psql -U postgres -d procurement_agent \
  -c "ALTER TYPE ai_provider_type ADD VALUE IF NOT EXISTS 'ollama';"
```

---

#### `agent_memory_vectors` table empty after confirmed orders

**Symptom.** Supplier memory appears absent in subsequent procurements; similarity scores are not improving.

**Cause.** The orchestrator fires memory writes as `asyncio.create_task(_persist_memory(...))` and never awaits them. If the data-normalizer is temporarily unavailable, or if the fastembed ONNX model call fails inside `POST /normalize/memory/write`, the failure is logged at DEBUG level and silently dropped. The `{"stored": false}` response from data-normalizer is not retried.

**Diagnosis.**
```bash
# Check orchestrator for _persist_memory errors
docker compose logs orchestrator | grep "_persist_memory\|memory.*error\|stored.*false"

# Verify data-normalizer is healthy and can reach the DB
curl http://localhost:8006/health
```

---

### 2.4 ERP Integration

#### Budget check always denies

**Symptom.** Every `/confirm` request is blocked with a budget-check failure, even for low-value orders.

**Diagnosis.**
```bash
# Check which ERP scenario is active
docker compose exec erp-mock env | grep ERP_MOCK_SCENARIO

# Switch to the happy path
curl -X POST http://localhost:8008/mock/scenario \
  -H "Content-Type: application/json" \
  -d '{"scenario": "happy"}'
```

Also verify the fail-open/fail-closed setting. The Docker stack defaults to `ERP_BUDGET_CHECK_REQUIRED=false` (fail-open), meaning a budget check error should allow the confirm to proceed. If `ERP_BUDGET_CHECK_REQUIRED=true` is set and the erp-adapter cannot reach the ERP endpoint within 800 ms, the confirm is blocked regardless.

```bash
docker compose exec orchestrator env | grep ERP_BUDGET_CHECK_REQUIRED
```

---

#### Circuit breaker is OPEN

**Symptom.** `GET /readyz` on erp-adapter returns a circuit breaker state of `1` (OPEN) for a vendor. All budget checks and PO syncs for that vendor fail immediately.

**Diagnosis.**
```bash
# Check per-vendor Prometheus gauge
curl -s http://localhost:8007/metrics | grep erp_circuit_state
# 0 = CLOSED, 1 = OPEN, 2 = HALF_OPEN
```

The breaker enters OPEN after `BREAKER_FAIL_MAX` (default 5) consecutive failures, and auto-probes to HALF_OPEN after `BREAKER_RESET_TIMEOUT_SECS` (default 60 seconds). `VendorPermanentError` (e.g. `INSUFFICIENT_FUNDS`) does not increment the failure counter.

**Fix.** Restart the erp-adapter container to reset all breakers to CLOSED immediately, or wait 60 seconds for the auto-probe.

```bash
docker compose restart erp-adapter
```

---

#### PO stuck in outbox / DLQ

**Symptom.** A purchase order was confirmed but has not appeared in the ERP system. Retries have stopped.

**Diagnosis.**
```bash
# Inspect outbox row state and last error
docker exec -it procurement-postgres \
  psql -U postgres -d procurement_agent \
  -c "SELECT id, status, last_error, next_attempt_at FROM erp_sync_records
      WHERE status IN ('DLQ','failed') ORDER BY updated_at DESC LIMIT 10;"
```

**Fix.** Trigger a manual replay for a specific sync record:
```bash
curl -X POST http://localhost:8007/api/v1/admin/outbox/<sync_id>/replay
```

**Note.** If the `erp_sync_records` table does not exist (schema not applied), erp-adapter falls back to `InMemoryOutboxRepo` at startup. POs are not durable in this mode — a service restart loses all pending sync records. Apply the database migrations and restart the service.

---

#### ERP cancellation silently drops for SAP / Oracle

**Expected behaviour.** `PATCH /cancel` on the orchestrator should cancel the PO in the ERP system.

**Current status.** `SAPS4HanaAdapter.cancel_po` and `OracleERPCloudAdapter.cancel_po` raise `NotImplementedError`. Because the orchestrator calls `_cancel_erp_record()` as a fire-and-forget task, this exception is swallowed. The PO status is patched to `cancelled` in local PostgreSQL only; SAP and Oracle are never notified. This is a known Phase 4 gap — `ERP_VENDORS=mock` is the only fully functional configuration for cancellation.

---

### 2.5 Frontend

#### Analytics page shows no data / blank dashboard

**Symptom.** The analytics page is blank or displays a "database unavailable" error banner.

**Cause.** The `analytics` service returns `HTTP 503` for all three endpoints (`/analytics`, `/business-impact`, `/benchmark`) when it cannot acquire a PostgreSQL connection pool. There is no stale-data cache and no fallback mock.

**Fix.** Verify that `procurement-postgres` is running and accepting connections:

```bash
docker ps --filter "name=procurement-postgres"
docker exec -it procurement-postgres \
  psql -U postgres -d procurement_agent -c "SELECT 1;"
```

Then restart the analytics container to force connection pool re-initialisation:
```bash
docker compose restart analytics
```

---

#### WebSocket order tracking not updating

**Symptom.** The order tracking page shows "Polling every 30s" instead of live updates, or status does not advance after a confirmed order.

**Cause.** The orchestrator's session state is an in-process Python `dict`. Restarting the orchestrator container drops all active sessions. The frontend's `StatusPoller.tsx` falls back to 30-second HTTP polling when the Kafka consumer loop is unavailable.

**Fix.** Reload the page to start a new session. If Kafka is down, notifications from sim-bpp auto-advance events (`SIM_BPP_AUTO_ADVANCE=true`) are silently dropped because sim-bpp cannot publish to the `po.status.changed` topic.

```bash
# Verify Kafka is running and the topic exists
docker compose logs kafka | tail -20
docker exec $(docker compose ps -q kafka) \
  kafka-topics.sh --bootstrap-server localhost:9092 --list
```

---

#### Keycloak login fails / frontend refuses to start

**Symptom.** The Next.js frontend crashes at startup with a missing env var error, or the login page redirects loop.

**Cause.** The frontend uses only `KeycloakProvider` — there are no stub credentials. All three required env vars (`KEYCLOAK_CLIENT_ID`, `KEYCLOAK_CLIENT_SECRET`, `KEYCLOAK_ISSUER`) use the non-null assertion operator and throw at runtime if absent.

**Minimum `frontend/.env.local` required:**
```
KEYCLOAK_CLIENT_ID=procurement-frontend
KEYCLOAK_CLIENT_SECRET=<client secret from Phase Two / Keycloak admin>
KEYCLOAK_ISSUER=https://<realm-host>/auth/realms/procurement-agent
NEXTAUTH_URL=http://localhost:3000
NEXTAUTH_SECRET=<any random string>
```

The working tenant used during development is Phase Two (`phasetwo.io`) at `euc1.auth.ac/auth/realms/procurement-agent`. No Keycloak container is defined in `docker-compose.yml` — a live external IdP is required in all environments including local dev. See [DEPLOYMENT.md](DEPLOYMENT.md) for the required realm and client configuration.

---

### 2.6 Supplier Selection Explanation (SelectionExplanationCard)

#### Symptom: "Could not generate explanation — ensure the IntentParser is running" message

**Cause 1 — `intention-parser` container is not running.**
```bash
docker compose up -d intention-parser
# Verify:
curl http://localhost:8001/health
# Expected: {"status": "ok"}
```

**Cause 2 — Container is running but `/explain-selection` returns 404.**

The running image predates Phase 4 and does not include the new handler endpoint.
```bash
docker compose build intention-parser && docker compose up -d intention-parser
```

**Cause 3 — Ollama is not running or `qwen3:1.7b` is not pulled.**
```bash
# Start Ollama if not already running
ollama serve

# Pull the required model
ollama pull qwen3:1.7b

# Verify the model appears in the list
curl http://localhost:11434/api/tags
# Check that "qwen3:1.7b" is present in the response
```

**Cause 4 — `OLLAMA_URL` misconfigured in the container.**

The `intention-parser` container must reach Ollama on the host via the Docker bridge:
- macOS / Windows: `http://host.docker.internal:11434/v1`
- Linux Docker bridge: `http://172.17.0.1:11434/v1`

```bash
# Check the value currently in use
docker compose exec intention-parser env | grep OLLAMA
```

---

#### Symptom: Explanation is cut off mid-sentence

Ollama returned the maximum token count (350) before completing the sentence. This is uncommon with `qwen3:1.7b` on a 2–3 sentence prompt. If it recurs, check whether the offerings list contains unusually long provider or item names that inflate the prompt past the effective context.

---

#### Symptom: Explanation contains `<think>…</think>` XML tags in the UI

The `re.sub` strip in `handler.py` did not fire — the regex produced an empty match.

**Immediate fix:**
```bash
docker compose restart intention-parser
```

**Verify** the handler contains the correct regex:
```python
re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL)
```

---

#### Symptom: Clicking "Cancel" navigates away without showing the confirmation modal

**Cause.** The browser is running a cached build from before Phase 4 that has the old `onClick={() => router.push("/request/new")}` Cancel button.

**Fix.** Hard-refresh the browser (`Ctrl+Shift+R` / `Cmd+Shift+R`) to clear the Next.js module cache, or restart the dev server:
```bash
npm run dev
```

**Verify.** With the Phase 4 build, clicking Cancel while in `awaiting_selection` or `awaiting_approval` stages should show a modal titled "Cancel this request?" with "Stay on page" and "Yes, cancel request" buttons.

---

### 2.7 Negotiation Engine

#### Negotiation connection refused — `http://localhost:8012`

**Symptom.** `POST /negotiate` or `POST /api/demo/negotiate/{thread_id}/supplier-respond` fails with `Connection refused` at `host.docker.internal:8012`.

**Cause.** The `claude_openai_proxy` service is not running. This service wraps the local `claude` CLI as an OpenAI-compatible endpoint and is a hard dependency for both `negotiation-engine` and `demo-gateway`. It is not in `docker-compose.yml` and must be started manually on the host.

**Fix.**
```bash
# Development (loopback only)
export CLAUDE_PROXY_KEY="dev-key"
uvicorn services.claude_openai_proxy.main:app --host 0.0.0.0 --port 8012

# Persistent (systemd — required for Docker bridge access)
cp services/claude_openai_proxy/claude-proxy.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now claude-proxy
journalctl --user -u claude-proxy -f
```

Prerequisite: the `claude` CLI must be installed and authenticated on the host. Default binary path: `CLAUDE_PROXY_BINARY_PATH=/home/<user>/.local/bin/claude`.

The `negotiation-engine` `/readyz` probe does not check connectivity to the proxy, so the container may report healthy even when this dependency is missing.

---

#### Negotiation stuck waiting for `on_select`

**Symptom.** The LangGraph negotiation graph stalls in the `waiting_on_select` state and never advances.

**Cause.** The `beckn-bap-client`'s `on_select` handler is not publishing to Redis after receiving the BPP callback. The negotiation engine subscribes to a Redis channel and blocks until that message arrives.

**Diagnosis.**
```bash
# Watch the Redis channel the engine is waiting on
# (substitute the actual transaction_id from the negotiation result)
redis-cli SUBSCRIBE beckn_results:<transaction_id>

# Check that on_select events are arriving at beckn-bap-client
docker compose logs -f beckn-bap-client | grep "on_select"
```

---

#### LangGraph checkpoint error on negotiation-engine startup

**Symptom.** `negotiation-engine` logs `AsyncPostgresSaver` errors or raises on first `/negotiate` request.

**Cause.** The LangGraph `AsyncPostgresSaver` requires the negotiation schema tables defined in `database/sql/20_negotiation_schema.sql`. These are auto-applied to the dedicated `postgres` Docker service at startup, but if the `postgres` service was not healthy when the negotiation engine first connected, the tables may not exist.

**Fix.** Restart the `postgres` Docker service (not the host PostgreSQL), then restart `negotiation-engine`:

```bash
docker compose restart postgres
docker compose restart negotiation-engine
```

With `MemorySaver` (in-memory fallback), all negotiation state is lost on restart and cannot be resumed. `AsyncPostgresSaver` requires the `NEGOTIATION_POSTGRES_DSN` environment variable to be set.

---

## 3. Known Limitations (Expected Behavior)

The behaviours below are by design or are deferred to Phase 4. Do not attempt to work around them without understanding the rationale.

| Behaviour | Why it happens | Workaround |
|---|---|---|
| `analytics` returns HTTP 503 when PostgreSQL is down | The service has no stale-data cache or fallback mock by design; all three analytics endpoints require a live DB connection. | Restore PostgreSQL, then `docker compose restart analytics`. No partial degradation mode exists. |
| All orchestrator sessions lost on container restart | Compare/commit state, pending approvals, ERP state cache, and order enrichments are stored in five module-level Python `dict` objects (`_sessions`, `_pending_approvals`, `_erp_state_cache`, `_order_enrichments`, `_run_id_index`). No Redis-backed or DB-backed session store is wired. TTL is 1800 s. | Reload the frontend page to start a new session after any orchestrator restart. Phase 4 will move sessions to Redis. |
| Kafka-dependent notifications not delivered | `notification-dispatcher` will not start its consumer loop if `KAFKA_BOOTSTRAP` is empty or unreachable. sim-bpp auto-advance state transitions are silently dropped. erp-adapter webhook fan-out events are discarded. | Verify Kafka is healthy: `docker compose ps kafka`. The Kafka KRaft broker in `docker-compose.yml` requires a 30 s start_period before its healthcheck clears. |
| `negotiate` event type never written to `audit_trail_events` | `_run_autonomous_negotiation` in `workflow.py` contains zero `_persist_audit` calls. Negotiation outcomes are appended to `result["messages"]` in memory only. | For compliance audit reconstruction, extract negotiation outcomes from orchestrator logs manually. This is a tracked SOX 404 gap (see analysis `22_problems_detected.md` §1.9). |
| IntentParser Docker container always uses qwen3:1.7b | `docker-compose.yml` overrides `COMPLEX_MODEL=qwen3:1.7b`, collapsing the two-tier complexity routing. The larger qwen3:8b model is only invoked when IntentParser runs locally outside Docker. | Run IntentParser locally via `conda activate infosys_project && cd IntentParser && uvicorn api:app --port 8001 --reload` to activate the full routing. |
| discovery_engine multi-network fan-out never runs | `services/discovery_engine/` is a complete implementation but has no entry in `docker-compose.yml` and is not called by any service. The only operational discovery path is through `beckn-bap-client`. | If multi-network search is needed, run `discovery_engine` standalone on port 8011 (use 8011 to avoid conflict with `data-normalizer:8006`). |
| catalog-normalizer UNKNOWN format returns empty offerings when Ollama is down | The LLM fallback in `CatalogNormalizer/llm_fallback.py` wraps the Ollama call in a top-level `try/except`. Any Ollama failure returns `[]` with HTTP 200 and no error surface. | Ensure Ollama is running and `NORMALIZER_MODEL=qwen3:1.7b` is pulled. |
| ERP PO cancellation silently dropped for SAP / Oracle | `cancel_po` raises `NotImplementedError` in both production adapters; fire-and-forget call swallows the error. | Use `ERP_VENDORS=mock` for cancellation testing. Production SAP/Oracle cancellation is a Phase 4 item. |
| Bap-1/ is reference code, not the production BAP | `Bap-1/src/server.py` runs a standalone FastAPI server on port 8000 with its own CLAUDE.md and 129 tests. It is not wired into `docker-compose.yml` and is not called by any production service. | The production BAP functions live in: `beckn-bap-client` (protocol), `orchestrator` (pipeline), `data-normalizer` (persistence). Do not extend Bap-1 for production features. |

---

## 4. Useful Debug Commands

### 4.1 Docker Logs and Containers

```bash
# Tail a specific service log
docker compose logs -f orchestrator
docker compose logs -f beckn-bap-client
docker compose logs -f negotiation-engine

# Show all container statuses and health
docker compose ps

# Restart a single service
docker compose restart catalog-normalizer

# Rebuild and restart a single container (picks up code changes)
docker compose up -d --build catalog-normalizer

# Open a shell in a running container
docker exec -it $(docker compose ps -q orchestrator) /bin/bash
```

---

### 4.2 Redis

```bash
# Verify Redis is responding
docker exec $(docker compose ps -q redis) redis-cli PING

# Watch a Beckn discovery callback channel in real time
# Replace <txn_id> with the transaction_id from your /discover call
redis-cli SUBSCRIBE beckn_results:<txn_id>

# List all active beckn_results channels
redis-cli --scan --pattern 'beckn_results:*'

# Flush all Pub/Sub channels (dev only — drops all in-flight callbacks)
docker exec $(docker compose ps -q redis) redis-cli FLUSHDB
```

---

### 4.3 PostgreSQL

```bash
# Connect to the main procurement_agent database
docker exec -it procurement-postgres \
  psql -U postgres -d procurement_agent

# List all tables
\dt

# Check for ENUM types (useful when debugging embedding_model_type inserts)
SELECT enumlabel FROM pg_enum
  JOIN pg_type ON pg_enum.enumtypid = pg_type.oid
  WHERE pg_type.typname = 'embedding_model_type';

# Inspect audit trail for a specific transaction
SELECT event_type, event_timestamp, actor_id, outcome
FROM audit_trail_events
WHERE transaction_id = '<your_txn_id>'
ORDER BY event_timestamp;

# Find the last 10 failed ERP sync records
SELECT id, status, last_error, next_attempt_at
FROM erp_sync_records
WHERE status IN ('DLQ', 'failed')
ORDER BY updated_at DESC
LIMIT 10;

# Replay a dead-letter outbox record
curl -X POST http://localhost:8007/api/v1/admin/outbox/<sync_id>/replay

# Verify pgvector extension and vector index on bpp_catalog_semantic_cache
SELECT relname, amname FROM pg_class
  JOIN pg_am ON pg_class.relam = pg_am.oid
  WHERE relname LIKE '%bpp_catalog%';

# Check agent memory vector count
SELECT COUNT(*), embedding_model FROM agent_memory_vectors GROUP BY embedding_model;
```

---

### 4.4 ERP / Mock Control

```bash
# Switch erp-mock to the happy path (budget checks pass)
curl -X POST http://localhost:8008/mock/scenario \
  -H "Content-Type: application/json" \
  -d '{"scenario": "happy"}'

# Switch to the sad path (budget checks deny)
curl -X POST http://localhost:8008/mock/scenario \
  -H "Content-Type: application/json" \
  -d '{"scenario": "insufficient_funds"}'

# Read per-vendor circuit breaker state from Prometheus
curl -s http://localhost:8007/metrics | grep erp_circuit_state

# erp-adapter readiness probe (reports db, redis, circuit states)
curl http://localhost:8007/readyz
```

---

### 4.5 IntentParser End-to-End Smoke Test

```bash
# Full three-stage parse (requires local IntentParser and mcp-sidecar)
curl -X POST http://localhost:8001/parse/full \
  -H "Content-Type: application/json" \
  -d '{"query": "300 meters Cat6 UTP cable Mumbai 5 days"}'

# Stage 1 only (intent classification)
curl -X POST http://localhost:8001/parse/classify \
  -H "Content-Type: application/json" \
  -d '{"query": "300 meters Cat6 UTP cable Mumbai 5 days"}'

# Stage 2 only (BecknIntent extraction — no validation)
curl -X POST http://localhost:8001/parse/intent \
  -H "Content-Type: application/json" \
  -d '{"query": "300 meters Cat6 UTP cable Mumbai 5 days"}'
```

---

### 4.6 Beckn Protocol / ONIX

```bash
# Check onix-bap routing config is loaded
docker compose logs onix-bap | grep "loaded\|config\|error"

# Fire a raw discover directly to onix-bap (bypasses beckn-bap-client signing)
# Use only for schema debugging — never POST directly to a BPP
curl -X POST http://localhost:8081/discover \
  -H "Content-Type: application/json" \
  -d @<your_beckn_discover_payload.json>

# Watch ONIX routing activity
docker compose logs -f onix-bap | grep -E "route|404|error|action"
```

---

### 4.7 MLOps / Comparative Scoring

```bash
# Start the MLOps sub-stack (separate compose file)
docker compose -f services/ComparativeAndScoreing/docker-compose.mlops.yaml \
  up -d mlflow-db mlflow-server prediction-api

# Check prediction-api is using ML model (not static fallback weights)
curl http://localhost:8004/health

# Hot-reload after promoting a new model to Production in MLflow
curl -X POST http://localhost:8004/reload

# Run a scoring request directly
curl -X POST http://localhost:8003/score \
  -H "Content-Type: application/json" \
  -d '{"offerings": [{"provider_id": "p1", "price": 100, "delivery_hours": 48}]}'
```
