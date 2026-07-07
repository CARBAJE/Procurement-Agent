# Deployment Guide

This guide covers the complete deployment topology for all phases: the current Docker Compose stack used in Phases 1–3, the host-side services that run outside Docker, the MLOps sub-stack, database migration procedure, observability setup, and the Phase 4 Kubernetes plan.

For configuration variable reference (full env var tables per service), see [Configuration Reference](CONFIGURATION.md). For the Beckn async discovery architecture, see [Architecture](ARCHITECTURE.md) and [ADR-0001](../docs/architecture/decisions/0001-use-redis-pubsub-for-async-beckn-responses.md).

---

## 1. Current Deployment: Docker Compose (Phases 1–3)

### 1.1 Stack Overview

18 containers run on the `beckn_network` Docker bridge network. Three services run on the host outside Docker (see [Section 2](#2-services-that-run-outside-docker)). All inter-container communication uses Docker DNS: containers reference each other by service name (e.g. `http://data-normalizer:8006`). Host-side services are reached from Docker containers via `host.docker.internal`.

**Two separate PostgreSQL instances:**

| Instance | Where it runs | Host port | Database name | Used by |
|---|---|---|---|---|
| Main procurement DB | Host (Docker container `procurement-postgres`, or native install) | 5432 | `procurement_agent` | data-normalizer, analytics, erp-adapter, notification-dispatcher, IntentParser |
| Negotiation DB | `postgres` service inside `beckn_network` | 55432 | `negotiation` | negotiation-engine only |

Docker containers reach the main procurement DB at `host.docker.internal:5432`. They reach the negotiation DB at `postgres:5432` via Docker DNS.

### 1.2 Container Reference

> **Note on port assignments:**
> - `orchestrator` maps host ports **8000 and 8004** to container port 8004. Port 8000 exists because `frontend/.env.local` defaults `NEXT_PUBLIC_API_BASE_URL=http://localhost:8000`.
> - `negotiation-engine` maps to host port **18004** (not 8004) to avoid collision with orchestrator. Docker-internal traffic still uses `negotiation-engine:8004`.
> - `notification-dispatcher` has **no published host port**; it is reachable only within `beckn_network`.

| Container | Image / Build context | Host port | Container port | Key env vars (docker-compose values) | Health check | Depends on |
|---|---|---|---|---|---|---|
| `intention-parser` | `./services/intention-parser` | 8001 | 8001 | `OLLAMA_URL=http://host.docker.internal:11434/v1`; `COMPLEX_MODEL=qwen3:1.7b` ⚠; `SIMPLE_MODEL=qwen3:1.7b` | HTTP `/health` | Ollama on host (soft) |
| `beckn-bap-client` | `./services/beckn-bap-client` (repo root context) | 8002 | 8002 | `BAP_ID`, `BAP_URI`, `ONIX_URL=http://onix-bap:8081`, `REDIS_URL=redis://redis:6379`, `CATALOG_NORMALIZER_URL=http://catalog-normalizer:8005` | HTTP `/health` | redis, catalog-normalizer |
| `catalog-normalizer` | `./services/catalog-normalizer` (repo root context) | 8005 | 8005 | `OLLAMA_URL=http://host.docker.internal:11434/v1` | HTTP `/health` | — |
| `comparative-scoring` | `./services/comparative-scoring` | 8003 | 8003 | `PREDICTION_API_URL=http://prediction-api:8004`, `SCORING_FALLBACK_ENABLED=true` | HTTP `/health` | — |
| `data-normalizer` | `./services/data-normalizer` (repo root context) | 8006 | 8006 | `DB_HOST=host.docker.internal`, `DB_PASSWORD` | HTTP `/health` | Host PostgreSQL (soft) |
| `analytics` | `./services/analytics` | 8009 | 8009 | `DB_HOST=host.docker.internal`, `DB_PASSWORD` | HTTP `/health` | postgres (healthy) |
| `orchestrator` | `./services/orchestrator` | **8000, 8004** | 8004 | `ERP_BUDGET_CHECK_REQUIRED=false` ⚠; `ERP_BUDGET_CHECK_ENABLED=true`; `ERP_INTERNAL_TOKEN` | HTTP `/health` | intention-parser, beckn-bap-client, comparative-scoring, data-normalizer, analytics, erp-adapter, demo-gateway, kafka |
| `erp-adapter` | `./services/erp-adapter` (repo root context) | 8007 | 8007 | `ERP_VENDORS=mock`, `ERP_INTERNAL_TOKEN`, `REDIS_URL=redis://redis:6379`, `KAFKA_BOOTSTRAP=kafka:9092` | HTTP `/health` | redis, erp-mock, kafka |
| `erp-mock` | `./services/erp-mock` (repo root context) | 8008 | 8008 | `MOCK_SCENARIO=happy`, `WEBHOOK_TARGET_URL=http://erp-adapter:8007` | HTTP `/health` | — |
| `redis` | `redis:alpine` | 6379 | 6379 | — | `redis-cli ping` | — |
| `kafka` | `apache/kafka:latest` | 9092 | 9092 | `KAFKA_AUTO_CREATE_TOPICS_ENABLE=true`; KRaft mode (no Zookeeper); cluster ID `5L6g3nShT-eMCtK--X86sw` | `kafka-broker-api-versions.sh` (interval 10 s, start_period 30 s) | — |
| `notification-dispatcher` | `./services/notification-dispatcher` (repo root context) | *(none)* | — | `KAFKA_BOOTSTRAP=kafka:9092`, `KAFKA_TOPIC=po.status.changed` | — | kafka (healthy) |
| `onix-bap` | `fidedocker/onix-adapter` (linux/amd64) | 8081 | 8081 | ONIX routing YAMLs bind-mounted from `./config` | HTTP health | redis (healthy) |
| `onix-bpp` | `fidedocker/onix-adapter` (linux/amd64) | 8082 | 8082 | ONIX routing YAMLs bind-mounted from `./config` | HTTP health | redis (healthy) |
| `sim-bpp` | `./services/sim-bpp` | 3002 | 3002 | `SIM_BPP_AUTO_ADVANCE=true` ⚠; `ONIX_BPP_CALLER=http://onix-bpp:8082/bpp/caller`; `KAFKA_BOOTSTRAP=kafka:9092` | HTTP `/health` | kafka (healthy) |
| `postgres` | `pgvector/pgvector:pg16` | **55432** | 5432 | `POSTGRES_DB=negotiation`; schema auto-init from `database/sql/20_negotiation_schema.sql` | `pg_isready` | — |
| `negotiation-engine` | `./services/negotiation_engine` | **18004** | 8004 | `NEGOTIATION_OPENAI_BASE_URL=http://host.docker.internal:8012/v1`; `REDIS_URL=redis://redis:6379/0` | HTTP `/health` | postgres (healthy), redis (healthy) |
| `demo-gateway` | `./services/frontend_demo_gateway` (repo root context) | 8015 | 8015 | `OLLAMA_BASE_URL=http://host.docker.internal:8012/v1` | HTTP `/health` | negotiation-engine (healthy), redis (healthy) |

**⚠ Notable docker-compose overrides that differ from code defaults:**

| Service | Variable | docker-compose value | Code default | Effect |
|---|---|---|---|---|
| `intention-parser` | `COMPLEX_MODEL` | `qwen3:1.7b` | `qwen3:8b` | Two-tier complexity routing is disabled in Docker; all queries use qwen3:1.7b. Full routing only works when IntentParser runs locally. |
| `sim-bpp` | `SIM_BPP_AUTO_ADVANCE` | `true` | `false` | Confirmed orders auto-advance through `ACCEPTED → PACKED → SHIPPED → OUT_FOR_DELIVERY → DELIVERED` every 5 s. Running sim-bpp locally without Docker requires setting this explicitly. |
| `orchestrator` | `ERP_BUDGET_CHECK_REQUIRED` | `false` | `true` | Budget gate is **fail-open** in the Docker stack: ERP connectivity errors do not block `/commit`. Set `true` for production to make it fail-closed. |

### 1.3 Key Bind Mounts

| Container | Host path | Container path | Purpose |
|---|---|---|---|
| `intention-parser` | `./IntentParser` | `/app/IntentParser` | Live-mount IntentParser package |
| `intention-parser` | `./shared` | `/app/shared` | Shared Pydantic models |
| `catalog-normalizer` | `./CatalogNormalizer` | `/app/CatalogNormalizer` | Live-mount CatalogNormalizer package |
| `catalog-normalizer` | `./shared` | `/app/shared` | Shared Pydantic models |
| `data-normalizer` | `./DataNormalizer` | `/app/DataNormalizer` | Live-mount DataNormalizer library |
| `data-normalizer` | `./shared` | `/app/shared` | Shared Pydantic models |
| `sim-bpp` | `./services/sim-bpp/catalog.json` | `/app/catalog.json` | Hot-reload BPP catalog without rebuilding the container |
| `onix-bap` | `./config` | `/app/config` | ONIX routing YAML files |
| `onix-bpp` | `./config` | `/app/config` | ONIX routing YAML files |
| `postgres` | `./database/sql/20_negotiation_schema.sql` | `/docker-entrypoint-initdb.d/01_negotiation.sql` | Auto-init negotiation schema on first start |
| `postgres` | `postgres_data` (named volume) | `/var/lib/postgresql/data` | Negotiation DB persistence across restarts |

### 1.4 Common Operations

**Start the full stack:**

```bash
docker compose up -d
```

**Start only Beckn discovery infrastructure (fastest for IntentParser and BAP development):**

```bash
docker compose up -d redis onix-bap onix-bpp sim-bpp
```

**Tail logs for a single service:**

```bash
docker compose logs -f beckn-bap-client
```

**Restart and rebuild a single container:**

```bash
docker compose up -d --build catalog-normalizer
```

**Teardown — stop all containers and remove them, keep named volumes (preserves negotiation DB data):**

```bash
docker compose down
```

**Full teardown including all volumes (destructive — deletes negotiation DB data):**

```bash
docker compose down -v
```

### 1.5 Deployment Topology Diagram

```mermaid
flowchart TD
    subgraph HOST["Host Machine"]
        OLLAMA["Ollama :11434\nqwen3:8b · qwen3:1.7b"]
        PG_NATIVE["PostgreSQL 16 :5432\nprocurement_agent DB"]
        IP_LOCAL["IntentParser :8001\nStage 1+2+3 — local only"]
        MCP["mcp-sidecar :3000\nlocal"]
        PROXY["claude_openai_proxy :8012\nlocal — wraps claude CLI"]
        FE["frontend :3000\nnpm run dev"]
        KEYCLOAK["Keycloak / Phase Two\nexternal OIDC provider"]
    end

    subgraph DOCKER["beckn_network (Docker Bridge)"]
        ORCH["orchestrator :8004\nhost: 8000 + 8004"]
        IP_DOCKER["intention-parser :8001\nStage 1+2 only"]
        BAP["beckn-bap-client :8002"]
        SCORE["comparative-scoring :8003"]
        CN["catalog-normalizer :8005"]
        DN["data-normalizer :8006"]
        ANALYTICS["analytics :8009"]
        ERP_A["erp-adapter :8007"]
        ERP_M["erp-mock :8008"]
        REDIS["redis :6379"]
        KAFKA["kafka :9092"]
        ONIX_BAP["onix-bap :8081"]
        ONIX_BPP["onix-bpp :8082"]
        SIM_BPP["sim-bpp :3002"]
        ND["notification-dispatcher\nno host port"]
        NEG["negotiation-engine :8004\nhost: 18004"]
        DGW["demo-gateway :8015"]
        PG_DOCKER["postgres :5432\nhost: 55432 — negotiation DB"]
    end

    FE -->|"NEXT_PUBLIC_API_BASE_URL\nhttp://localhost:8000"| ORCH
    FE -->|OIDC auth| KEYCLOAK
    ORCH --> IP_DOCKER
    ORCH --> BAP
    ORCH --> SCORE
    ORCH --> DN
    ORCH --> DGW
    DGW --> NEG
    DGW -->|"host.docker.internal:8012"| PROXY
    NEG -->|"host.docker.internal:8012"| PROXY
    NEG -->|Redis on_select channel| REDIS
    BAP -->|signing + routing| ONIX_BAP
    ONIX_BAP -->|Beckn actions| ONIX_BPP
    ONIX_BPP -->|webhook callbacks| SIM_BPP
    BAP -->|on_discover → publish beckn_results:{txn_id}| REDIS
    MCP -->|subscribe beckn_results:{txn_id}| REDIS
    IP_LOCAL -->|MCP SSE| MCP
    IP_DOCKER -->|"host.docker.internal:11434"| OLLAMA
    CN -->|"host.docker.internal:11434"| OLLAMA
    DN -->|"host.docker.internal:5432"| PG_NATIVE
    ANALYTICS -->|"host.docker.internal:5432"| PG_NATIVE
    ERP_A -->|"host.docker.internal:5432"| PG_NATIVE
    SIM_BPP -->|po.status.changed| KAFKA
    KAFKA -->|consume| ND
    NEG -->|AsyncPostgresSaver| PG_DOCKER
```

---

## 2. Services That Run Outside Docker

Three services run on the host and are not in `docker-compose.yml`. Docker containers reach them via `host.docker.internal`. All three require the `infosys_project` conda environment.

```bash
conda activate infosys_project
```

### 2.1 IntentParser API (`:8001`)

The full three-stage pipeline — Stage 1 (LLM intent classification) → Stage 2 (BecknIntent extraction) → Stage 3 (pgvector ANN + mcp-sidecar BPP validation) — only operates when IntentParser runs locally. The `intention-parser` Docker container runs only Stages 1+2, and collapses both model tiers to qwen3:1.7b via the `COMPLEX_MODEL` override.

```bash
# Terminal 1
conda activate infosys_project
cd IntentParser
uvicorn api:app --port 8001 --reload
```

Required env vars:

| Variable | Purpose |
|---|---|
| `OLLAMA_URL` | Ollama base URL; default `http://localhost:11434/v1` |
| `COMPLEX_MODEL` | Large model for Stage 1 + complex Stage 2; default `qwen3:8b` |
| `SIMPLE_MODEL` | Small model for short queries; default `qwen3:1.7b` |
| `DB_HOST` | PostgreSQL host for Stage 3 pgvector cache; default `localhost` |
| `DB_PASSWORD` | PostgreSQL password; empty is unsafe in production |
| `ANTHROPIC_API_KEY` | Optional. Enables Claude Sonnet 4.6 as Stage 3 broadening fallback. Without it Stage 3 uses regex-only broadening. |

Pull required Ollama models before first run:

```bash
ollama pull qwen3:8b
ollama pull qwen3:1.7b
```

### 2.2 MCP Sidecar (`:3000`)

The mcp-sidecar implements the Redis Pub/Sub subscriber side of [ADR-0001](../docs/architecture/decisions/0001-use-redis-pubsub-for-async-beckn-responses.md). It subscribes to `beckn_results:{txn_id}` **before** firing the `/discover` POST so it never misses the callback. All failures return `{"found": false, "items": [], "probe_latency_ms": elapsed}` — the service never throws (see [Configuration Reference](CONFIGURATION.md) for full contract).

```bash
# Terminal 2
conda activate infosys_project
cd services/mcp-sidecar
export BAP_API_KEY="any-value-in-dev"
uvicorn server:app --port 3000
```

> **Important:** `BAP_API_KEY`, `REDIS_URL`, and `REDIS_RESULT_TIMEOUT` are read via `os.getenv()` in `bap_client.py`, not through the Pydantic Settings model. They must be present as real process environment variables, not only in a `.env` file.

| Variable | Default | Notes |
|---|---|---|
| `BAP_API_KEY` | *(none)* | **Mandatory.** Service refuses to start without it. Any non-empty string works in dev. |
| `REDIS_URL` | `redis://localhost:6379` | Must be a real env var, not only `.env`. |
| `REDIS_RESULT_TIMEOUT` | `15` | Seconds to wait on the Redis channel before returning `found: false`. This is the primary latency ceiling for discovery probes. Must be a real env var. |
| `BAP_CLIENT_URL` | `http://localhost:8002` | URL of beckn-bap-client's `/discover` endpoint. |
| `RANKING_MIN_SIMILARITY` | `0.30` | Cosine similarity floor; items below this score are filtered from results. |

### 2.3 Claude OpenAI Proxy (`:8012`)

A FastAPI service that wraps the host-installed `claude` CLI as an OpenAI-compatible `/v1/chat/completions` endpoint. Required by `negotiation-engine` and `demo-gateway` (both configured with `NEGOTIATION_OPENAI_BASE_URL=http://host.docker.internal:8012/v1`). It must bind to `0.0.0.0` (not `127.0.0.1`) so Docker bridge containers can reach it via `host.docker.internal:8012`.

**Development (loopback only — does not serve Docker containers):**

```bash
# Terminal 3
export CLAUDE_PROXY_KEY="any-dev-string"
uvicorn services.claude_openai_proxy.main:app --host 127.0.0.1 --port 8012
```

**Persistent with Docker access (systemd user service — recommended):**

```bash
cp services/claude_openai_proxy/claude-proxy.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now claude-proxy

# Allow the service to persist after logout (one-time, requires sudo):
sudo loginctl enable-linger $USER

# Tail logs:
journalctl --user -u claude-proxy -f
```

The systemd unit binds to `0.0.0.0:8012`. A UFW rule documented in `claude-proxy.service` restricts access to loopback plus the Docker subnet `172.16.0.0/12`.

| Variable | Default | Notes |
|---|---|---|
| `CLAUDE_PROXY_BINARY_PATH` | `/home/carbaje/.local/bin/claude` | **Must be updated per machine.** |
| `CLAUDE_PROXY_KEY` | `""` (auth disabled) | Empty disables auth with a startup warning. |
| `CLAUDE_PROXY_HOST` | `127.0.0.1` | Set `0.0.0.0` for Docker bridge access (the systemd unit sets this). |
| `CLAUDE_PROXY_MAX_CONCURRENCY` | `2` | Max concurrent `claude -p` subprocesses; excess requests queue. |
| `CLAUDE_PROXY_TIMEOUT_S` | `120.0` | Hard timeout per request; CLI subprocess is killed if exceeded. |
| `CLAUDE_PROXY_DISABLE_TOOLS` | `true` | Disallows interactive tools in `-p` mode to prevent permission hangs. |

**OpenAI → Claude model mapping:**

| OpenAI name received | Claude alias used |
|---|---|
| `gpt-4o` | `sonnet` |
| `gpt-4o-mini` | `haiku` |
| `gpt-4-turbo`, `gpt-4` | `sonnet`, `opus` |
| `gpt-3.5-turbo` | `haiku` |
| `claude-3-5-sonnet` | `sonnet` |
| Any `claude-*` prefix | passed through unchanged |

**Known limitations:** `temperature`, `top_p`, and `max_tokens` are accepted in requests but silently ignored — the Claude CLI exposes no sampling knobs. Each request bills the host's Claude account and incurs a ~1–3 s CLI cold start.

---

## 3. MLOps Sub-Stack (ComparativeAndScoreing)

The MLOps stack lives in a separate Compose file and runs independently of the main stack.

**File:** `services/ComparativeAndScoreing/docker-compose.mlops.yaml`

| Service | Host port | Purpose |
|---|---|---|
| `mlflow-db` | — (internal) | PostgreSQL backend for MLflow metadata |
| `mlflow-server` | 5000 | MLflow tracking server and model registry |
| `prediction-api` | 8004 | RankNet inference endpoint; falls back to static weights when no Production model is registered |
| `training-pipeline` | — | Batch CLI: builds training pairs, trains RankNet, auto-promotes to `Staging` if NDCG@5 ≥ 0.85 |
| `validation-service` | — | Batch CLI: weekly drift check; exits 1 if degradation > `NDCG_DRIFT_THRESHOLD` (default 0.05) |

**Start the inference API and MLflow tracking server:**

```bash
docker compose -f services/ComparativeAndScoreing/docker-compose.mlops.yaml \
  up -d mlflow-db mlflow-server prediction-api
```

**Run a training cycle (`training` profile):**

```bash
docker compose -f services/ComparativeAndScoreing/docker-compose.mlops.yaml \
  --profile training up training-pipeline
```

Auto-promotes to `Staging` when NDCG@5 ≥ 0.85 (`AUTO_PROMOTE_NDCG=0.85`).

**Run the weekly drift check (`validation` profile):**

```bash
docker compose -f services/ComparativeAndScoreing/docker-compose.mlops.yaml \
  --profile validation up validation-service
```

**Activating the ML scoring path:**

On first start there is no `Production` model in MLflow. `prediction-api` falls back to static weights `[0.4, 0.3, 0.3]` (price / speed / risk). To enable ML scoring:

```bash
# 1. After training completes, promote the best version to Production:
mlflow models transition-stage \
  --name ProcurementRanker --version 1 \
  --to-stage Production --archive-existing-versions

# 2. Hot-reload without restarting the container:
curl -X POST http://localhost:8004/reload
```

Set `ALLOW_FALLBACK_WEIGHTS=false` to disable the heuristic fallback for canary deployments where ML failures must surface rather than silently degrade.

---

## 4. Applying Database Migrations

The main `procurement_agent` database runs on the host (not inside the main Docker Compose stack). Docker containers reach it via `host.docker.internal:5432`.

### 4.1 First-Time Setup

**Provision the PostgreSQL container (Windows / Docker Desktop recommended):**

```bash
docker run -d \
  --name procurement-postgres \
  -e POSTGRES_USER=postgres \
  -e POSTGRES_PASSWORD=postgres123 \
  -e POSTGRES_DB=procurement_agent \
  -p 5432:5432 \
  pgvector/pgvector:pg16
```

**Apply all 24 SQL migrations:**

```bash
cd database
export $(grep -v '^#' .env | xargs)
python setup_database.py --create-db
```

### 4.2 Adding New Migrations

Migrations in `database/sql/` run in lexicographic order. This order encodes FK dependency: always use the next available numeric prefix. Never reorder or renumber existing files — the FK chain depends on lexicographic execution order.

```bash
# After adding a new NN_*.sql file:
cd database
python setup_database.py --continue-on-exists
```

`--continue-on-exists` treats PostgreSQL "already exists" errors as SKIP rather than FAIL, making re-runs safe.

### 4.3 setup_database.py Flags

| Flag | Effect |
|---|---|
| *(none)* | Run all 24 SQL scripts against the existing database |
| `--create-db` | Create `DB_NAME` if it does not exist (requires CREATEDB privilege) |
| `--drop-all` | DROP all tables and ENUM types CASCADE, then recreate (destructive) |
| `--continue-on-exists` | Treat "already exists" errors as SKIP — use for idempotent re-runs |

### 4.4 Verify Schema

```bash
pytest test_database.py -v --tb=short -q
# 67 tests: Connection, Extensions, EnumTypes, Tables, Indexes,
# WorkflowRows, EndToEndQuery, Constraints
```

### 4.5 Key Migrations

| File | Effect |
|---|---|
| `00_extensions_and_types.sql` | `uuid-ossp`, `pgcrypto`, `vector` extensions; 20 ENUM types |
| `15_agent_memory_vectors.sql` | Creates `agent_memory_vectors` with `vector(3072)` |
| `18_bpp_catalog_semantic_cache.sql` | Standalone vector store for Stage 3 BPP semantic cache (`vector(384)`) |
| `19b_erp_sync_records_outbox.sql` | Adds outbox columns to `erp_sync_records` for async PO push |
| `20_negotiation_schema.sql` | Negotiation-engine tables (also auto-init'd in the `postgres` Docker service) |
| `22_agent_memory_vector_dim.sql` | Alters `agent_memory_vectors` from `vector(3072)` to `vector(384)`; adds `all-MiniLM-L6-v2` to `embedding_model_type` ENUM |

> **Known ENUM gap:** The `embedding_model_type` ENUM defined in `00_extensions_and_types.sql` includes only `text-embedding-3-large` and `e5-large-v2`. Migration `22_agent_memory_vector_dim.sql` adds `all-MiniLM-L6-v2`. The value `BAAI/bge-small-en-v1.5` — used by the data-normalizer memory service — is absent from all migrations. Any INSERT that stores this value in a column typed `embedding_model_type` will fail with a PostgreSQL type error.

### 4.6 Root `.env` Template

```bash
cp .env.example .env
```

```env
# DB_HOST options:
#   localhost          — when PostgreSQL is in a named Docker container visible on host
#   host.docker.internal — when PostgreSQL on host must be reached by Docker containers
DB_HOST=host.docker.internal
DB_PORT=5432
DB_NAME=procurement_agent
DB_USER=postgres
DB_PASSWORD=postgres123

# Required for claude_openai_proxy (negotiation demo):
CLAUDE_PROXY_BINARY_PATH=/home/<your-user>/.local/bin/claude
CLAUDE_PROXY_KEY=                  # any non-empty string enables auth
```

---

## 5. Monitoring and Observability

### 5.1 Service Health Endpoints

All FastAPI services expose a `GET /health` endpoint that returns HTTP 200 when the service is up. The `analytics` service returns HTTP 503 (not mock data) when the DB connection pool is unavailable.

```bash
# Spot-check all running services:
curl -s http://localhost:8001/health   # intention-parser
curl -s http://localhost:8002/health   # beckn-bap-client
curl -s http://localhost:8003/health   # comparative-scoring
curl -s http://localhost:8004/health   # orchestrator
curl -s http://localhost:8005/health   # catalog-normalizer
curl -s http://localhost:8006/health   # data-normalizer
curl -s http://localhost:8007/health   # erp-adapter
curl -s http://localhost:8009/health   # analytics
curl -s http://localhost:3002/health   # sim-bpp
```

### 5.2 erp-adapter Prometheus Metrics

erp-adapter exposes a Prometheus-format metrics endpoint with 9 series:

```bash
curl http://localhost:8007/metrics
```

Tracked series include: budget check latency histogram, outbox queue depth, outbox retry counts, circuit breaker state per vendor, and webhook HMAC validation pass/fail counts. This endpoint is the primary integration point for the Phase 4 Prometheus scrape config.

### 5.3 Log Streaming

```bash
# Single service (follow mode):
docker compose logs -f beckn-bap-client

# Multiple services:
docker compose logs -f orchestrator beckn-bap-client data-normalizer

# Last 100 lines without following:
docker compose logs --tail=100 orchestrator

# For the local IntentParser process, logs go to the terminal where uvicorn is running.
```

> **Never set `LOG_PAYLOADS=true` on erp-adapter in production.** This logs full PO and budget payloads containing PII and financial data.

### 5.4 Phase 4: Prometheus + Grafana (Planned)

Phase 4 will add a Prometheus scrape job targeting the erp-adapter `/metrics` endpoint plus OpenTelemetry collectors for all FastAPI services. A Grafana deployment will provide dashboards for procurement pipeline latency (P95 < 5 s acceptance criterion), BPP discovery success rate, and ERP outbox backlog depth. LangSmith tracing for LangGraph negotiation flows will be enabled via `LANGCHAIN_TRACING_V2=true` on `negotiation-engine`.

The `audit_trail_events` table already has a `splunk_indexed` boolean column and a `retention_until` timestamp placeholder for the Phase 4 SIEM and retention-enforcement CronJob.

---

## 6. Phase 4: Kubernetes (Planned)

All items in this section are deferred from Phases 1–3 and not yet implemented. Phase 4 targets production readiness on a managed Kubernetes cluster (EKS / AKS / GKE).

### 6.1 Container Orchestration

- **Helm chart** with parameterised `values.yaml` for dev / staging / production.
- **ArgoCD GitOps:** chart changes committed to `main` trigger a cluster sync automatically.
- Docker Compose `depends_on` is replaced by Kubernetes readiness probes and init containers for all 18 services.

### 6.2 CI/CD Pipeline (GitHub Actions)

```
lint → unit-test → build → push image → Helm deploy
```

| Stage | Detail |
|---|---|
| `lint` | Python ruff + mypy; Go vet; Node ESLint |
| `unit-test` | `pytest IntentParser/ -m "not integration"` and `pytest Bap-1/tests/ -k "not integration"` |
| `build` | Docker Buildx multi-arch images |
| `trivy` | Image scanning; HIGH/CRITICAL CVEs block deploy |
| `helm deploy (staging)` | Triggered on every merge to `main` |
| `helm deploy (production)` | Triggered on tagged releases only |

### 6.3 Infrastructure Components

| Component | Technology | Notes |
|---|---|---|
| API Gateway | Kong | Replaces Docker DNS for external-facing routes; enforces Keycloak JWT on every route; blocks `POST /confirm` for the `requester` role |
| Event streaming | Kafka StatefulSet (KRaft, replication ≥ 3, `acks=all`) | Replaces the current single-broker KRaft container; enables `KAFKA_BOOTSTRAP` across all services that currently disable it |
| Vector store | Qdrant StatefulSet | Spec only — not yet implemented; current deployment uses pgvector exclusively |
| LLM inference | Managed Ollama or cluster-hosted model serving | Replaces `host.docker.internal:11434`; intent-parser and catalog-normalizer point at the cluster endpoint |
| Secret management | Kubernetes Secrets + KMS | Replaces all `_CHANGE_ME` dev values; see [Section 6.4](#64-secrets-that-must-change-before-production) |
| Observability | Prometheus + Grafana + OpenTelemetry + LangSmith | LangSmith tracing enabled via `LANGCHAIN_TRACING_V2=true` on negotiation-engine |
| SIEM | Splunk exporter | `splunk_indexed` column in `audit_trail_events` is the integration hook |
| Retention | Nightly CronJob | `retention_until` timestamp in `audit_trail_events` drives deletion/archival |
| mTLS | SSL context hook in erp-adapter | Hook is wired but not activated in dev |

### 6.4 Secrets That Must Change Before Production

The following variables have insecure defaults that are publicly known. They must be replaced in Kubernetes Secrets (backed by KMS) before any production deployment.

| Variable | Service | Risk if unchanged |
|---|---|---|
| `NEXTAUTH_SECRET` | frontend | Session JWTs are unsigned; any token is accepted |
| `KEYCLOAK_CLIENT_SECRET` | frontend | OIDC flow breaks; no user can authenticate |
| `KEYCLOAK_ISSUER` | frontend | Points at Phase Two dev tenant; auth goes to the wrong realm |
| `ERP_INTERNAL_TOKEN` | orchestrator, erp-adapter | Default `dev-internal-token-CHANGE_ME` is public; any caller can hit `/api/v1/*` on erp-adapter |
| `SELLER_WEBHOOK_HMAC_SECRET` | orchestrator | Default `dev-seller-hmac-CHANGE_ME` is public; forged seller webhooks will be accepted |
| `SAP_WEBHOOK_HMAC_SECRET` | erp-adapter, erp-mock | Default is public; forged SAP webhooks accepted |
| `ORACLE_WEBHOOK_HMAC_SECRET` | erp-adapter, erp-mock | Default is public; forged Oracle webhooks accepted |
| `SAP_CLIENT_SECRET` | erp-adapter | Default `mock-sap-secret` is public; applies when `ERP_VENDORS=sap` |
| `ORACLE_CLIENT_SECRET` | erp-adapter | Default `mock-oracle-secret` is public; applies when `ERP_VENDORS=oracle` |
| `DB_PASSWORD` | data-normalizer, analytics, erp-adapter, notification-dispatcher | Default `postgres123` is trivial; grants full DB access |
| `CLAUDE_PROXY_KEY` | claude_openai_proxy | Auth is disabled when empty; any client can trigger Claude CLI invocations that bill the host account |
| `CLAUDE_PROXY_BINARY_PATH` | claude_openai_proxy | Hardcoded to `/home/carbaje/.local/bin/claude`; fails on every other machine |
| `BAP_ID` | beckn-bap-client | Default `bap.example.com` is a placeholder; must be the registered BAP identifier on the target Beckn network |
| `BAP_URI` | beckn-bap-client | Default is `localhost`; must be a publicly reachable URL for ONIX to route `on_*` callbacks correctly |

### 6.5 Phase 4 Acceptance Criteria

All six must hold simultaneously before Phase 4 is considered complete:

1. P95 agent response latency < 5 seconds under representative load
2. OWASP Top 10 penetration test signed off
3. Integration test coverage ≥ 80 %
4. Evaluation suite accuracy ≥ 85 % (intent parsing + comparison quality)
5. Helm chart deploys cleanly to the target Kubernetes cluster
6. Documentation package complete

---

## Appendix: Orphaned Service — discovery_engine

`services/discovery_engine/` contains a standalone multi-network Beckn discovery fan-out implementation. It is **absent from `docker-compose.yml`** and **not called by any other service**. Its documented port (8006) conflicts with `data-normalizer`. Its architectural status is undocumented — it may be a planned replacement for `beckn-bap-client`'s single-gateway discovery, a dead branch, or a future integration point.

Features it provides: concurrent fan-out to N Beckn network gateways via `asyncio.gather`, per-network circuit breakers (3 failures, 30 s recovery), result deduplication by `provider_id:item_id:currency` with geo-proximity merge at 0.5 km, always HTTP 200 even on partial failures.

To evaluate it standalone (use port 8011 to avoid conflict with data-normalizer):

```bash
export DISCOVERY_NETWORKS_JSON='[{"name":"main","base_url":"http://localhost:8002","timeout_s":5.0}]'
cd services/discovery_engine
uvicorn src.main:app --host 0.0.0.0 --port 8011
```
