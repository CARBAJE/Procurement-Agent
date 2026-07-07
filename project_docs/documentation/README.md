# Procurement Agent

The Procurement Agent is an event-driven agentic AI system built for corporate buyers. It accepts natural-language purchase requests — such as `"300 meters Cat6 UTP cable Mumbai 5 days"` — classifies intent, extracts structured procurement parameters via a three-stage LLM pipeline, discovers matching suppliers on a Beckn Protocol v2.0.0 network, scores and ranks their offers using an ML model with agent memory, optionally negotiates price autonomously via a LangGraph state machine, obtains ERP budget approval, and drives the full Beckn lifecycle (`discover → select → init → confirm → status`). Every decision is persisted to an auditable PostgreSQL database with 7-year retention. The buyer interacts through a Next.js 13 dashboard without writing code or issuing protocol calls directly.

---

## Quick Start

1. **Provision the database.** Install PostgreSQL 16 with the pgvector extension natively on the host, then run `cd database && python setup_database.py` to apply the 24 numbered SQL migrations. See [Installation Guide](INSTALLATION.md) for required environment variables and the exact Conda environment setup.

2. **Start the Docker stack.** Bring up all 18 containerised services:

   ```bash
   docker compose up -d
   ```

   Verify Beckn routing is live by checking `docker compose logs -f beckn-bap-client`.

3. **Start the three host-side processes.** These are not Dockerised and must be started manually in the `conda activate infosys_project` environment:

   ```bash
   # MCP sidecar — required for IntentParser Stage 3 validation
   cd services/mcp-sidecar
   BAP_API_KEY="any-value" uvicorn server:app --port 3000

   # Frontend
   cd frontend && npm run dev   # http://localhost:3000

   # Claude OpenAI proxy — required for negotiation demo flows
   export CLAUDE_PROXY_KEY=your-key
   uvicorn services.claude_openai_proxy.main:app --host 0.0.0.0 --port 8012
   ```

   Open `http://localhost:3000` and authenticate via the Phase Two Keycloak tenant. See [Installation Guide](INSTALLATION.md) for all required environment variables.

---

## Architecture Overview

The system has five logical layers. Two processes run on the host workstation outside Docker (mcp-sidecar and frontend); 18 containers communicate over the `beckn_network` Docker bridge.

```mermaid
flowchart TD
    subgraph Presentation["Presentation Layer"]
        FE["frontend :3000\nNext.js 13 + Tailwind"]
    end

    subgraph Orchestration["Orchestration Layer"]
        ORCH["orchestrator :8000/:8004\nFastAPI + LangGraph"]
        DG["demo-gateway :8015\nFrontend BFF"]
    end

    subgraph Core["Core Services"]
        IP["intention-parser :8001\nIntentParser pipeline"]
        BAP["beckn-bap-client :8002\nBeckn lifecycle"]
        CN["catalog-normalizer :8005\nFormat detection"]
        CS["comparative-scoring :8003\nRankNet / heuristic"]
        DN["data-normalizer :8006\nSole DB write path"]
        ERP["erp-adapter :8007\nBudget gate + PO push"]
        ANA["analytics :8009\nSpend + KPI queries"]
        NE["negotiation-engine :18004\nLangGraph state machine"]
        ND["notification-dispatcher :8010\nKafka consumer"]
    end

    subgraph Protocol["Protocol Adapters"]
        ONIX_BAP["onix-bap :8081\nGo ED25519 signing"]
        ONIX_BPP["onix-bpp :8082\nGo BPP-side adapter"]
        SIMBPP["sim-bpp :3002\nNode.js BPP simulator"]
        MCP["mcp-sidecar :3000\nMCP SSE — host only"]
    end

    subgraph Persistence["Persistence Layer"]
        PG[("PostgreSQL :5432\nnative host\n+ pgvector")]
        REDIS[("Redis :6379\nPub/Sub + ONIX cache")]
        KAFKA[("Kafka :9092\nKRaft mode")]
        NEGPG[("PostgreSQL :55432\nnegotiation DB only")]
    end

    subgraph Host["Host-Only Services"]
        PROXY["claude_openai_proxy :8012\nOpenAI-compat CLI bridge"]
    end

    FE -->|wizard API| ORCH
    ORCH --> IP
    ORCH --> BAP
    ORCH --> CS
    ORCH --> DN
    ORCH --> ERP
    ORCH --> DG
    DG --> NE
    NE --> PROXY
    DG --> PROXY
    BAP -->|discover / select / init\n/ confirm / status| ONIX_BAP
    ONIX_BAP --> ONIX_BPP
    ONIX_BPP --> SIMBPP
    SIMBPP -->|on_discover callback| ONIX_BPP
    ONIX_BPP -->|on_* callbacks| BAP
    BAP -->|raw on_discover payload| CN
    IP -->|MCP SSE| MCP
    MCP --> BAP
    BAP -->|PUBLISH beckn_results:{txn_id}| REDIS
    MCP -->|SUBSCRIBE beckn_results:{txn_id}| REDIS
    NE -->|SUBSCRIBE beckn_on_select_results| REDIS
    ORCH --> ANA
    ERP --> KAFKA
    SIMBPP --> KAFKA
    KAFKA --> ND
    DN --> PG
    NE --> NEGPG
    ERP --> PG
    ANA --> PG
```

> The `on_discover` split-routing rule is the critical wiring detail: ONIX routes `on_discover` directly to `http://beckn-bap-client:8002/on_discover` (which publishes to Redis), while all other `on_*` callbacks route to `http://beckn-bap-client:8002/bap/receiver/{action}`. See [Architecture](ARCHITECTURE.md) for the full ADR-0001 explanation.

---

## Key Features

### NL Procurement

- **Three-stage intent pipeline** — Stage 1 classifies procurement intent (qwen3:8b/1.7b); Stage 2 extracts a canonical `BecknIntent` with typed `delivery_timeline` (int hours), `location_coordinates` ("lat,lon"), and `budget_constraints ({max, min})`; Stage 3 validates against a live Beckn catalog via pgvector ANN + MCP sidecar probe.
- **Complexity routing** — queries over 120 characters, containing two or more numeric tokens, or matching procurement keywords are routed to the larger model; simpler queries use qwen3:1.7b for speed.
- **Three execution modes** — `advisory` (surface ranked options for manual selection), `hitl` (recommend then await human approval), and `autonomous` (auto-commit within approval threshold); controlled by `PROCUREMENT_EXECUTION_MODE`.

### Beckn Protocol

- **Full lifecycle** — `discover → select → init → confirm → status` mediated by the onix-bap Go adapter with ED25519 signing; no service ever POSTs directly to a BPP.
- **Async discovery decoupling** (ADR-0001) — Redis Pub/Sub on `beckn_results:{transaction_id}` channels prevents the asyncio event loop from deadlocking on the ACK-only `POST /discover` response.
- **Local BPP simulator** — sim-bpp (Node.js, port 3002) replaces the fixed `fidedocker/sandbox-2.0` catalog; hot-reloads `catalog.json`, supports AND-token matching, and auto-advances fulfillment states (ACCEPTED → PACKED → SHIPPED → DELIVERED) publishing each transition to Kafka.

### Comparison and Negotiation

- **Catalog normalisation** — detects five payload variants (BECKN_V2_FLAT_RESOURCES, LEGACY_PROVIDERS_ITEMS, BPP_CATALOG_V1, ONDC_CATALOG, UNKNOWN) with rule-based mappers and an Ollama qwen3:1.7b LLM fallback for unknown formats.
- **ML comparative scoring** — RankNet/LambdaRank `nn.Linear(3,1)` model (price, delivery speed, risk) with a min-price heuristic fallback when the MLOps sub-stack is not running.
- **Automated negotiation** — LangGraph state machine with five category discount profiles, three Pydantic-enforced guardrail layers, a hard 20% maximum discount cap, and durable PostgreSQL checkpointing; HITL interrupt support via Redis async resume.

### ERP Integration

- **Synchronous budget gate** — `POST /api/v1/budget/check` must return within 800 ms; fail-closed by default; supports SAP, Oracle, and mock adapters via a six-method Protocol interface.
- **Asynchronous PO push** — PostgreSQL outbox pattern (`erp_sync_records`, `FOR UPDATE SKIP LOCKED`) with exponential backoff (5 s → 3600 s) and dead-letter replay; Kafka migration path reserved via `kafka_offset` column.
- **Dual-HMAC webhook rotation** — inbound vendor webhooks authenticated against current and next HMAC-SHA256 secrets simultaneously for zero-downtime key rotation; per-vendor circuit breakers via pybreaker.

### Memory and Learning

- **Agent memory store** — confirmed orders are embedded with BAAI/bge-small-en-v1.5 (384-dim ONNX) and inserted into `agent_memory_vectors` (pgvector HNSW cosine) as a fire-and-forget task post-confirm.
- **Time-decayed loyalty bonus** — before scoring, the orchestrator retrieves the top-3 past transactions for the current item category and applies a loyalty delta `0.03 * exp(-days * ln(2) / 90)` capped at ±0.10; visible in the frontend Agent Reasoning panel.

### Notifications

- **Multi-channel fan-out** — Kafka `po.status.changed` consumer dispatches Slack Block Kit messages, MS Teams Adaptive Cards, and Jinja2 HTML emails (STARTTLS) in parallel; channel failures are isolated via `asyncio.gather(return_exceptions=True)`.
- **Status-based routing** — `confirmed` and `delivered` trigger all three channels; `shipped` triggers Slack and Teams only; other states are dropped.

---

## Documentation Index

| Document | Purpose |
|---|---|
| [README.md](README.md) | Project front door — quick start, architecture overview, feature summary |
| [PROJECT_OVERVIEW.md](PROJECT_OVERVIEW.md) | Problem statement, solution summary, target users, project scope, design principles, and tech-choice rationale |
| [ARCHITECTURE.md](ARCHITECTURE.md) | Detailed architecture: five logical layers, ADR-0001 Redis Pub/Sub, IntentParser pipeline, LangGraph state machines, full happy-path sequence diagram |
| [SYSTEM_DESIGN.md](SYSTEM_DESIGN.md) | Service boundaries, design decisions, ADR-0001 rationale, spec deviations (pgvector, qwen3, sim-bpp, PostgreSQL outbox) |
| [COMPONENTS.md](COMPONENTS.md) | Per-component reference: all 18 Docker containers + 3 host processes, ports, responsibilities, key files |
| [DATA_FLOW.md](DATA_FLOW.md) | Seven major data flows with Mermaid sequence diagrams: NL→Beckn, discovery, scoring, negotiation, ERP, audit, memory |
| [INSTALLATION.md](INSTALLATION.md) | Step-by-step setup: Conda environment, PostgreSQL native install, Docker Compose, host-side processes, required environment variables |
| [ENVIRONMENT.md](ENVIRONMENT.md) | Full environment variable reference with defaults and required/optional flags for every service |
| [CONFIGURATION.md](CONFIGURATION.md) | ONIX routing YAMLs, Docker Compose overrides, multi-service configuration patterns |
| [DATABASE.md](DATABASE.md) | Database schema: 24 SQL migrations, vector tables, Redis channels, known schema deviations |
| [API_REFERENCE.md](API_REFERENCE.md) | HTTP API surface: all endpoints, request/response schemas, and error codes for every service |
| [SECURITY.md](SECURITY.md) | Authentication model, Beckn ED25519 signing, HMAC webhook rotation, input validation, secrets management |
| [DEPLOYMENT.md](DEPLOYMENT.md) | Docker Compose deployment guide, environment configuration, production considerations |
| [TESTING.md](TESTING.md) | Test framework, test suites by scope, infrastructure requirements, coverage gaps |
| [DEVELOPMENT_GUIDE.md](DEVELOPMENT_GUIDE.md) | Coding conventions, async patterns, adding services and DB tables, IntentParser and LangGraph internals, known problems |
| [CONTRIBUTING.md](CONTRIBUTING.md) | Git workflow, branch naming, pre-submission checklist, documentation standards, PR review criteria |
| [TROUBLESHOOTING.md](TROUBLESHOOTING.md) | Diagnostic runbooks: NL parsing, Beckn discovery, database, ERP integration, frontend, negotiation engine |
| [GLOSSARY.md](GLOSSARY.md) | Alphabetical definitions of all domain terms, architectural concepts, and database identifiers |

---

## Tech Stack Summary

| Layer | Technology | Notes |
|---|---|---|
| **UI** | Next.js 13.5.6, React 18, Tailwind CSS 3.4.1, shadcn/ui, Radix UI | TypeScript strict mode; Keycloak OIDC auth via next-auth 4; recharts for analytics |
| **Orchestration** | FastAPI + LangGraph (orchestrator :8000/:8004) | aiohttp HTTP client; fire-and-forget persistence via `asyncio.create_task`; 5-second data-normalizer timeout |
| **NL Intent Parsing** | qwen3:8b / qwen3:1.7b via local Ollama, instructor, FastAPI (IntentParser :8001) | Complexity-routed; Docker stack collapses both tiers to qwen3:1.7b |
| **Beckn Protocol** | onix-bap / onix-bpp Go adapters (`fidedocker/onix-adapter`), ED25519 signing | Pinned to commit `d43ec30d`; DeDi registry bypassed via `targetType: url` |
| **BPP Simulator** | sim-bpp Node.js :3002 | Hot-reload `catalog.json`; AND-token matching; auto-advance lifecycle |
| **MCP Sidecar** | Python FastMCP, MCP SSE protocol :3000 | Host-only (not Dockerised); sentence-transformers `all-MiniLM-L6-v2` |
| **LLM Fallback** | Claude Sonnet 4.6 (`anthropic` SDK) | Stage 3 broadening only; opt-in via `ANTHROPIC_API_KEY` |
| **LLM Proxy** | claude_openai_proxy FastAPI :8012 (host-only) | Wraps Claude Code CLI as OpenAI-compatible endpoint; required by negotiation-engine and demo-gateway |
| **Negotiation** | LangGraph, langchain-openai, langgraph-checkpoint-postgres | Three guardrail layers; 20% hard discount cap; AsyncPostgresSaver checkpointing |
| **Scoring ML** | PyTorch `nn.Linear(3,1)`, RankNet/LambdaRank, MLflow | Optional MLOps sub-stack (`docker-compose.mlops.yaml`); heuristic fallback active when not running |
| **Primary datastore** | PostgreSQL 16 + pgvector 0.7.0, asyncpg | Runs natively on host (not a Docker container); reached at `host.docker.internal:5432` |
| **Vector search** | pgvector HNSW cosine, `vector(384)` | Two tables: `agent_memory_vectors` (BAAI/bge-small-en-v1.5) and `bpp_catalog_semantic_cache` (all-MiniLM-L6-v2) |
| **Async broker** | Redis 7 Pub/Sub | Channels: `beckn_results:{txn_id}`, `beckn_on_select_results`; also ONIX routing cache |
| **Event streaming** | Apache Kafka KRaft mode :9092 | `po.status.changed` topic; used by orchestrator, erp-adapter, sim-bpp, notification-dispatcher |
| **ERP** | erp-adapter FastAPI :8007, erp-mock :8008 | SAP + Oracle + mock adapters; pybreaker circuit breakers; prometheus-client metrics |
| **Container runtime** | Docker Compose 18 services on `beckn_network` bridge | Phase 4 target: Kubernetes EKS/AKS + Helm + ArgoCD |

---

## Project Status

This project was built during a 16-week Infosys InStep internship as a reference implementation of a Beckn Application Platform (BAP) for enterprise procurement.

| Phase | Weeks | Theme | Status |
|---|---|---|---|
| 1 | 1–4 | Foundation and Protocol Integration — ONIX adapter, NL intent parser (Stages 1+2), LangGraph framework, Beckn sandbox | Complete |
| 2 | 5–8 | Core Intelligence and Transaction Flow — six microservices extracted, catalog normaliser, data normaliser, comparative scoring, full Beckn lifecycle (init + confirm + status) | Complete |
| 3 | 9–12 | Advanced Intelligence and Enterprise Features — agent memory (pgvector RAG), audit trail (SOX 404), ERP integration, negotiation engine, analytics dashboard | Complete (current branch: `phase3`) |
| 4 | 13–16 | Hardening and Production Readiness — Kubernetes Helm chart, OWASP pen test, CI/CD pipeline, Kafka event bus for audit and ERP, observability stack (LangSmith, Splunk) | Not started |

**Current deployment model:** single developer workstation running Docker Compose. No cloud or Kubernetes infrastructure is deployed. The `phase3` branch is the integration branch for all completed work.

**Intended use:** Infosys InStep pilot. The target market is enterprise procurement software clients; productisation planning targets 15–20 enterprise deployments at $2–5 M each.

**Phase 4 deferrals that affect current operation:**

- Kafka is deployed but used only for `po.status.changed` events; audit writes and ERP sync use PostgreSQL directly with `kafka_offset` placeholder columns reserved for migration.
- `retention_until` timestamps are set on all audit rows but no automated deletion job exists.
- The `claude_openai_proxy` service is absent from `docker-compose.yml`; negotiation and demo flows fail silently if it is not started manually on the host.
- The `discovery_engine` service is fully implemented but has no `docker-compose.yml` entry and no callers (orphaned multi-network fan-out).
