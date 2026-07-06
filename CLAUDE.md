# Procurement Agent — Beckn Protocol

Event-driven procurement assistant that translates natural-language purchase requests into validated Beckn Protocol v2.0.0 transactions. The system classifies buyer intent, extracts structured procurement parameters, validates them against live BPP catalogs, and drives the full Beckn lifecycle (`discover → select → init → confirm → status`).

## Architecture

Microservices monorepo. Two unbundled local Python services (`mcp-sidecar`, `IntentParser`) and seven dockerised containers communicate over HTTP and a Redis Pub/Sub broker. Beckn traffic is mediated by the `onix-bap` Go adapter (ED25519 signing, schema validation). Discovery is **inherently async** in Beckn v2.0.0 — `POST /discover` returns only an ACK; the catalog arrives later via webhook. We decouple the wait via Redis Pub/Sub on per-transaction channels (`beckn_results:{transaction_id}`) — see [ADR-0001](docs/architecture/decisions/0001-use-redis-pubsub-for-async-beckn-responses.md).

The IntentParser pipeline is three stages: LLM intent classification (qwen3:8b) → BecknIntent extraction (qwen3:8b/1.7b routed by complexity) → hybrid pgvector ANN + MCP sidecar fallback validation. A recovery flow handles `not_found` cases via query broadening + RFQ trigger.

## Stack

- **Python 3.11+** — FastAPI (IntentParser API), aiohttp (Bap-1 + dockerised services), Pydantic v2, asyncpg, instructor + Ollama (qwen3:8b, qwen3:1.7b), sentence-transformers (`all-MiniLM-L6-v2`), MCP SSE.
- **Go** — `onix-bap`, `onix-bpp` (`fidedocker/onix-adapter` image).
- **Node** — `sim-bpp` (local BPP simulator, replaced `fidedocker/sandbox-2.0`); Next.js 13 + Radix UI + Tailwind for the frontend.
- **Datastores** — PostgreSQL 16 + pgvector (semantic cache, audit DB), Redis 7 (Pub/Sub broker + ONIX cache).
- **LLMs** — qwen3:8b/1.7b via local Ollama for dev; Claude Sonnet 4.6 as last-resort broadening fallback (`ANTHROPIC_API_KEY` opt-in).

## Layout

```
IntentParser/         Stage 1+2+3 NL → BecknIntent pipeline (FastAPI :8001 — runs locally)
Bap-1/                Standalone BAP module + tests (LangGraph orchestration, aiohttp :8000)
services/             Dockerised microservices:
                        beckn-bap-client :8002  — Beckn protocol client (discover/select/init/confirm/status)
                        orchestrator :8004      — Pipeline state machine (4-step + compare/commit + approvals)
                        comparative-scoring :8003 — ML scoring adapter (prediction-api primary, heuristic fallback)
                        catalog-normalizer :8005 — on_discover payload → DiscoverOffering normalizer
                        data-normalizer :8006   — Central persistence layer (all DB writes)
                        analytics :8009         — Dashboard reporting queries
                        erp-adapter :8007       — SAP/Oracle ERP integration (budget gate + PO push)
                        erp-mock :8008          — Local ERP stub (SAP/Oracle/mock surfaces)
                        negotiation_engine :8004 — LangGraph automated price negotiation
                        notification-dispatcher :8010 — Kafka consumer → Slack/Teams/Email fan-out
                        sim-bpp :3002           — Local BPP simulator (replaced sandbox-2.0)
                        intention-parser :8001  — Docker wrapper for IntentParser package (Stage 1+2 only)
                        mcp-sidecar :3000       — MCP SSE bridge (runs locally, not in Docker)
                        discovery_engine :8006  — Multi-network Beckn discovery fan-out
                        frontend_demo_gateway :8005 — Demo BFF for scoring/negotiation demo flows
                        ComparativeAndScoreing/ — MLOps stack (prediction-api + training + validation)
shared/               Cross-service Pydantic models (BecknIntent, BudgetConstraints, DiscoverOffering)
database/             PostgreSQL schema (24 numbered SQL scripts), setup script, integration tests
config/               ONIX routing YAMLs (BAPCaller, BAPReceiver, BPPCaller, BPPReceiver)
docs/architecture/    Decision records (ADR-0001 = Redis Pub/Sub)
frontend/             Next.js 13 + Radix UI + Tailwind buyer-facing app
KnowledgeBase/        Obsidian vault — project context, milestones, user stories
docker-compose.yml    11-service stack on the beckn_network bridge
```

## Frequent commands

```bash
# Stack
docker compose up -d                               # full Docker stack
docker compose up -d redis onix-bap onix-bpp       # discovery infra only
docker compose logs -f beckn-bap-client            # tail one service

# Local services (run inside `conda activate infosys_project`)
cd services/mcp-sidecar && BAP_API_KEY="$BAP_API_KEY" uvicorn server:app --port 3000  # any value works in dev — export from your shell
cd IntentParser        && uvicorn api:app --port 8001 --reload

# Database
cd database && export $(grep -v '^#' .env | xargs)
python setup_database.py --create-db               # first-time
python setup_database.py                           # idempotent re-run
pytest test_database.py -v --tb=short -q

# Tests
pytest IntentParser/ -m "not integration" -v       # unit, no infra
pytest IntentParser/ -v                            # full (Ollama needed)
INTENT_PARSER_TEST_MODE=live pytest IntentParser/tests/test_async_pipeline.py -v -s
pytest Bap-1/tests/ -v -k "not integration"

# End-to-end
curl -X POST http://localhost:8001/parse/full \
  -H "Content-Type: application/json" \
  -d '{"query": "300 meters Cat6 UTP cable Mumbai 5 days"}'
```

## Conventions

- **Async-first**. Every new feature in IntentParser/services/Bap-1 ships as a coroutine. The sync wrapper in `IntentParser.core.parse_request` only exists for legacy/sync test callers and explicitly disables Stage 3.
- **Anti-corruption layer.** `shared/models.BecknIntent` is the canonical NL-derived intent; `delivery_timeline` is **int hours** (not ISO 8601), `location_coordinates` is `"lat,lon"` decimal (not city names), `budget_constraints` is typed `{max, min}` (not raw strings).
- **Pydantic v2** with `field_validator` decorators. No `@validator` (deprecated).
- **Env-driven config** lives in module-level `config.py` (`IntentParser/config.py`, `Bap-1/src/config.py`, `services/mcp-sidecar/config.py`). Never `os.getenv(...)` inline elsewhere.
- **Numbered SQL migrations** — files in `database/sql/` use a `NN_` prefix; numeric order matches FK dependency. Adding a migration → next free number; idempotent (`IF NOT EXISTS`).
- **Tests use `pytest-asyncio` with `asyncio_mode = auto`** — never decorate `async def test_*` with `@pytest.mark.asyncio`.
- **MCP tools obey a "never throw" contract** — failures return `{"found": False, ...}`, not an exception (see `services/mcp-sidecar/server.py::search_bpp_catalog`).

## What NOT to do

- **Don't POST directly to a BPP.** All Beckn traffic must go through `onix-bap:8081`. Tests enforce that `select_url` always contains `caller`.
- **Don't include the action name in ONIX routing target URLs** (`config/generic-routing-*.yaml`). ONIX appends it. `http://host:8000/bpp` + action `discover` → `http://host:8000/bpp/discover`. Including it duplicates and routes 404.
- **Don't use `Contract.status.code = "CONFIRMED"`.** Valid enum is `DRAFT | ACTIVE | CANCELLED | COMPLETE`. ONIX rejects others.
- **Don't put billing or fulfillment inline in `Contract`.** `Contract` is `additionalProperties: false`. Buyer info lives in `participants[role=buyer]`, fulfillment in `performance[]`, payment in `settlements[]`. See `Bap-1/CLAUDE.md` "wire-shape gotchas" for the full list.
- **Don't `await` the `/discover` POST in the MCP sidecar.** It's `asyncio.create_task(...)`; blocking re-introduces the deadlock ADR-0001 was written to fix.
- **Don't `time.sleep()` to flush `asyncio.create_task` side effects** (e.g. Path B cache writes). Use `await asyncio.sleep(...)`. Sync sleep blocks the event loop and the task never runs.
- **Don't reorder or renumber existing `database/sql/*.sql` files.** FK chain depends on lexicographic order. Add new migrations at the next free prefix only.
- **Don't reuse a `transaction_id`.** Beckn channels are derived from it; reuse delivers one transaction's catalog to a stale subscriber.
