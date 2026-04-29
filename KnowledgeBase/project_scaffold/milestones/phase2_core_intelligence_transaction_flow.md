---
tags: [milestone, phase-2, intelligence, transaction-flow, comparison, approval, weeks-5-8]
cssclasses: [procurement-doc, milestone-doc]
status: "#processed"
related: ["[[comparison_scoring_engine]]", "[[beckn_bap_client]]", "[[approval_workflow]]", "[[real_time_tracking]]", "[[frontend_react_nextjs]]", "[[catalog_normalizer]]", "[[data_normalizer]]", "[[microservices_architecture]]", "[[phase1_foundation_protocol_integration]]", "[[phase3_advanced_intelligence_enterprise_features]]"]
---

# Phase 2: Core Intelligence & Transaction Flow (Weeks 5–8)

> [!milestone] Phase Objective
> Build the comparison engine, complete the Beckn transaction lifecycle, and deliver a **functional end-to-end procurement workflow** that a real user can operate. By end of Week 8, a user can submit a request, see ranked seller recommendations with explanations, approve or reject, and track order delivery in real-time — the full loop minus negotiation and memory.

## Milestones & Deliverables

| Milestone                                        | Deliverable                                           | Skills Required                  | Acceptance Criteria                                                    |
| ------------------------------------------------ | ----------------------------------------------------- | -------------------------------- | ---------------------------------------------------------------------- |
| Full Transaction Flow                            | `/init`, `/confirm`, `/status` implemented            | Beckn protocol, state management | Complete order lifecycle working against sandbox                       |
| Catalog Normalizer                               | Standardizes diverse seller response formats          | Data engineering, schema mapping | Handles 5+ distinct seller catalog formats correctly                   |
| [[comparison_scoring_engine\|Comparison Engine]] | Multi-criteria scoring with explainable reasoning     | ML/AI, scoring algorithms        | Ranks sellers correctly for 10+ test scenarios with clear explanations |
| [[approval_workflow\|Approval Workflow]]         | Configurable threshold-based routing                  | Workflow engine, RBAC            | Orders above threshold require and receive approval before `/confirm`  |
| Comparison UI                                    | Side-by-side offer comparison with agent reasoning    | React, data visualization        | Users can view, compare, and act on agent recommendations              |
| [[real_time_tracking\|Real-time Tracking]]       | Order status updates via `/status` polling + webhooks | WebSockets, event handling       | Dashboard reflects status within **30 seconds** of change              |

> [!architecture] Technical Focus Areas
> - State management for multi-step Beckn v2 transaction lifecycle: `discover` → `select` → `init` → `confirm` → `status`.
> - [[comparison_scoring_engine|Hybrid scoring]]: deterministic Python functions + [[llm_providers|GPT-4o]] ReAct reasoning.
> - [[identity_access_keycloak|RBAC enforcement]] for [[approval_workflow|approval routing]].
> - WebSocket integration for real-time status push to [[frontend_react_nextjs|frontend]].
> - [[databases_postgresql_redis|PostgreSQL]] state machine for order lifecycle tracking.

> [!insight] What Phase 2 Unlocks
> Phase 2 delivers the **minimum viable autonomous procurement system** — a user can go from natural language request to confirmed order without touching SAP Ariba. This is the first demonstrable proof point for enterprise pilots. The comparison engine's explainability is particularly important for user trust: without knowing *why* Seller A is recommended, users will override the agent reflexively rather than trusting it.

> [!milestone] Deliverables Summary — End of Week 8
> - Full ONIX-routed flow operational: `discover` (sync query to Discovery Service) → Catalog Normalization → `/bap/caller/select` → `/bap/caller/init` → `/bap/caller/confirm` → `/bap/caller/status`.
> - [[catalog_normalizer|Catalog Normalizer]] handles 5+ formats as a standalone service on port 8005.
> - [[comparison_scoring_engine]] produces ranked, explained results.
> - [[data_normalizer|Data Normalizer]] persists every pipeline step to PostgreSQL.
> - [[approval_workflow|Approval routing]] enforced for all role combinations.
> - [[real_time_tracking|Real-time dashboard]] live with 30-second SLA.

---

## Completed Implementation — Catalog Normalizer (Bap-1 embedded)

> [!done] Delivered — Catalog Normalizer inside Bap-1

The **Catalog Normalizer** was first implemented as `src/normalizer/` inside the `Bap-1` project (monolith phase), then extracted as a standalone microservice (`CatalogNormalizer/` module + `services/catalog-normalizer/`).

### What was built

| Component | File | Responsibility |
|---|---|---|
| `FormatVariant` | `src/normalizer/formats.py` | IntEnum with 5 variants + detection predicates |
| `FormatDetector` | `src/normalizer/detector.py` | Detects the raw catalog format — no IO, no LLM |
| `SchemaMapper` | `src/normalizer/schema_mapper.py` | Deterministic mapping for variants 1–4 |
| `LLMFallbackNormalizer` | `src/normalizer/llm_fallback.py` | LLM fallback via instructor + Ollama for variant 5 |
| `CatalogNormalizer` | `src/normalizer/normalizer.py` | Public facade that orchestrates the 3-step pipeline |

### Design decisions
- The logic of `_parse_on_discover()` was **moved verbatim** into `SchemaMapper` for Formats A and B — no behavioral regressions.
- The LLM fallback follows the same pattern as `IntentParser/core.py` (instructor + Ollama) for consistency across the project.
- `CatalogNormalizer` is a module-level singleton in `client.py` — no changes required in the LangGraph graph or its nodes.
- Detection rule ordering: ONDC (variant 4) is checked **before** LEGACY (variant 2) because ONDC catalogs also contain `providers[].items[]`.
- On LLM error: returns an empty list instead of propagating the exception — the graph handles `offerings=[]` gracefully (routes directly to `present_results`).

### Tests
- 17 unit tests in `tests/test_normalizer.py` — all pass without Ollama running.
- Existing tests in `tests/test_discover.py` and `tests/test_agent.py` continue passing without changes (77 tests total, all green).

*Preceded by → [[phase1_foundation_protocol_integration]] | Continues in → [[phase3_advanced_intelligence_enterprise_features]]*

---

## Architecture Migration — Microservices (6 services)

> [!milestone] Completed: Bap-1 Monolith → 6 Microservices (AWS Step Functions pattern)

The Bap-1 monolith has been fully decomposed into 6 services under `services/` following the `architecture/Architecture.md` Step Functions model. See [[microservices_architecture]] for full detail.

### Services Delivered

| Service               | Port | Lambda Equivalent                        | Module            | Status |
| --------------------- | ---- | ---------------------------------------- | ----------------- | ------ |
| `intention-parser`    | 8001 | Lambda 1 — Intention Parser              | `IntentParser/`   | ✅     |
| `beckn-bap-client`    | 8002 | Lambda 2 — Beckn BAP Client              | —                 | ✅     |
| `comparative-scoring` | 8003 | Lambda 3 — Comparative & Scoring         | `ComparativeScoring/` | ✅  |
| `orchestrator`        | 8004 | Step Functions simulator                 | —                 | ✅     |
| `catalog-normalizer`  | 8005 | Lambda 4 — Catalog Format Normalization  | `CatalogNormalizer/` | ✅  |
| `data-normalizer`     | 8006 | Lambda 5 — PostgreSQL Persistence Bridge | `DataNormalizer/` | ✅     |

### Agent Stack Placement

| Agent | Lambda | Location |
|-------|--------|----------|
| Parser Agent | Lambda 1 | `services/intention-parser/` via `IntentParser/` |
| Normalizer Agent | Lambda 2 | `services/beckn-bap-client/src/normalizer/` |
| Catalog Agent | Lambda 4 | `services/catalog-normalizer/` via `CatalogNormalizer/` |
| Persistence Bridge | Lambda 5 | `services/data-normalizer/` via `DataNormalizer/` |

### Port Map — Full Local Stack

```
HOST (macOS / Linux)                 DOCKER (beckn_network)
─────────────────────────────────────────────────────────────────────────────
localhost:8001  ────────────────► intention-parser      :8001  (Lambda 1)
localhost:8002  ────────────────► beckn-bap-client      :8002  (Lambda 2)
localhost:8003  ────────────────► comparative-scoring   :8003  (Lambda 3)
localhost:8004  ────────────────► orchestrator          :8004  (Step Functions)
localhost:8005  ────────────────► catalog-normalizer    :8005  (Lambda 4)
localhost:8006  ────────────────► data-normalizer       :8006  (Lambda 5)
localhost:8081  ────────────────► onix-bap              :8081  (BAP ONIX adapter)
localhost:8082  ────────────────► onix-bpp              :8082  (BPP ONIX adapter)
localhost:3002  ────────────────► sandbox-bpp           :3002  (BPP mock)
localhost:6379  ────────────────► redis                 :6379  (ONIX cache)
host.docker.internal:11434 ◄──── Ollama (host process)
```

### State Pattern

JSON payload passed between services via HTTP POST. The orchestrator assembles the final result. The Data Normalizer persists every step to PostgreSQL — **stateless pipeline, stateful storage**.

---

## Completed Implementation — Catalog Normalizer (Microservice)

> [!done] Delivered — `catalog-normalizer` service (port 8005)

The `CatalogNormalizer/` module from Bap-1 was extracted as a standalone service, following the same volume-mount pattern as `IntentParser/` and `ComparativeScoring/`.

### File layout

```
CatalogNormalizer/          ← repo root module (volume-mounted at /app/CatalogNormalizer)
├── __init__.py             ← exports CatalogNormalizer
├── formats.py              ← FormatVariant enum + FINGERPRINT_RULES
├── detector.py             ← FormatDetector — pure function, no IO
├── schema_mapper.py        ← SchemaMapper — deterministic mappers for variants 1–4
├── llm_fallback.py         ← LLMFallbackNormalizer — instructor + Ollama
└── normalizer.py           ← CatalogNormalizer — public facade

services/catalog-normalizer/
├── Dockerfile              ← python:3.12-slim, build context = repo root
├── requirements.txt        ← aiohttp, instructor, openai, pydantic
└── src/handler.py          ← POST /normalize, GET /health
```

### HTTP interface

```
POST /normalize
Body: { "catalog": <raw BPP catalog dict>, "bpp_id": str, "bpp_uri": str }
Returns: { "offerings": [DiscoverOffering, ...], "format_variant": int }

GET /health
Returns: { "status": "ok", "service": "catalog-normalizer" }
```

### Environment variables

| Variable | Default | Description |
|---|---|---|
| `OLLAMA_URL` | `http://host.docker.internal:11434/v1` | Ollama endpoint for LLM fallback |
| `NORMALIZER_MODEL` | `qwen3:1.7b` | Model used for Format 5 (UNKNOWN) normalization |

---

## Completed Implementation — Data Normalizer (Microservice)

> [!done] Delivered — `data-normalizer` service (port 8006)

The Data Normalizer is the **persistence bridge** between the stateless microservices and PostgreSQL. It receives data from the orchestrator after each pipeline step, transforms it to the PostgreSQL schema, and persists it maintaining full referential integrity.

### Why it was needed

Before the Data Normalizer, the system was completely **stateless** — all data lived in memory and was lost on restart. PostgreSQL had 16 tables with a complete schema, but no microservice wrote to them. The Data Normalizer converts the system from stateless to stateful without modifying any existing service's business logic.

### File layout

```
DataNormalizer/                     ← repo root module (volume-mounted at /app/DataNormalizer)
├── __init__.py                     ← exports DataNormalizer
├── normalizer.py                   ← facade — orchestrates repos + transformers
├── db.py                           ← asyncpg connection pool (reads DB_* env vars)
├── repositories/
│   ├── request_repo.py             ← procurement_requests INSERT + status UPDATE
│   ├── intent_repo.py              ← parsed_intents + beckn_intents INSERT
│   ├── discovery_repo.py           ← bpp upsert + discovery_queries + seller_offerings
│   ├── scoring_repo.py             ← scored_offers INSERT (0–1 → 0–100)
│   └── order_repo.py               ← negotiation_outcomes + approval_decisions + purchase_orders
└── transformers/
    ├── offering_transformer.py     ← DiscoverOffering → seller_offerings schema
    ├── intent_transformer.py       ← BecknIntent → beckn_intents schema
    └── score_transformer.py        ← composite_score × 100 → total_score

services/data-normalizer/
├── Dockerfile                      ← python:3.12-slim, build context = repo root
├── requirements.txt                ← aiohttp, asyncpg, pydantic
└── src/handler.py                  ← 6 routes + health
```

### HTTP routes

```
GET  /health                      → { status: "ok", service: "data-normalizer" }

POST /normalize/request           Body: { raw_input_text, channel?, requester_id? }
                                  → { request_id }    201

POST /normalize/intent            Body: { request_id, intent_class, confidence,
                                          model_version, beckn_intent }
                                  → { intent_id, beckn_intent_id }    201

POST /normalize/discovery         Body: { beckn_intent_id, network_id, offerings: [...] }
                                  → { query_id, offering_ids: [{item_id, offering_id}] }    201

POST /normalize/scoring           Body: { query_id, scores: [{offering_id, rank,
                                          composite_score, price_value}] }
                                  → { score_ids: [{offering_id, score_id}] }    201

POST /normalize/order             Body: { score_id, bpp_uri, item_id, quantity,
                                          agreed_price, beckn_confirm_ref, delivery_terms }
                                  → { po_id }    201

PATCH /normalize/status           Body: { request_id, status }
                                  → { request_id, status }    200
```

### Key normalizations applied

| Source field | Source type | DB table.column | DB type | Transformation |
|---|---|---|---|---|
| `DiscoverOffering.price_value` | `str` | `seller_offerings.price` | `DECIMAL(15,2)` | `float(price_value)` |
| `DiscoverOffering.bpp_uri` | `str` | `seller_offerings.bpp_id` | `UUID` FK→`bpp` | find-or-create in `bpp` |
| `DiscoverOffering.fulfillment_hours` | `Optional[int]` | `seller_offerings.delivery_eta_hours` | `INTEGER NOT NULL` | default 24 if None |
| `DiscoverOffering.rating` | `Optional[str]` | `seller_offerings.quality_rating` | `FLOAT` 0–5 | `float(rating)` if not None |
| `BecknIntent.budget_constraints` | `Optional[BudgetConstraints]` | `beckn_intents.budget_min/max` | `DECIMAL(15,2)` | unpack object |
| `scoring.composite_score` | `float` 0–1 | `scored_offers.total_score` | `FLOAT` 0–100 | `× 100`, clamped |
| `order_id` | `str` | `purchase_orders.beckn_confirm_ref` | `VARCHAR(255) UNIQUE` | direct mapping |

### FK chain auto-created for purchase_orders

`purchase_orders` requires an `approval_id` FK → `approval_decisions`, which in turn requires a `negotiation_id` FK → `negotiation_outcomes`. The `order_repo` creates all three records in a single transaction:

```
scored_offers (existing)
  └─► negotiation_outcomes  (strategy=skipped, acceptance=skipped)
        └─► approval_decisions  (approval_level=auto, status=auto_approved)
              └─► purchase_orders  (status=pending)
```

### `procurement_status` state machine

```
draft → parsing → discovering → scoring → negotiating → confirmed
                                                       → cancelled
```

The orchestrator drives transitions by calling `PATCH /normalize/status` after each pipeline step.

### Integration with orchestrator

The orchestrator calls the Data Normalizer via `_persist()` — a fire-and-forget helper with a 5-second timeout that **never raises**. If the Data Normalizer is unreachable, the pipeline continues normally and logs a `DEBUG` warning.

```
orchestrator:8004
  ├─► POST /normalize/request      (on every /run, /compare, /discover)
  ├─► POST /normalize/intent       (after intention-parser step)
  ├─► PATCH /normalize/status → discovering
  ├─► POST /normalize/discovery    (after beckn-bap-client /discover)
  ├─► PATCH /normalize/status → scoring
  ├─► POST /normalize/scoring      (after comparative-scoring /score)
  ├─► PATCH /normalize/status → negotiating
  └─► POST /normalize/order        (after beckn-bap-client /confirm)
      └─► PATCH /normalize/status → confirmed
```

### Environment variables

| Variable | Default | Description |
|---|---|---|
| `DB_HOST` | `localhost` | PostgreSQL host |
| `DB_PORT` | `5432` | PostgreSQL port |
| `DB_NAME` | `procurement_agent` | Database name |
| `DB_USER` | `""` | PostgreSQL user |
| `DB_PASSWORD` | `""` | PostgreSQL password |
| `SYSTEM_USER_ID` | `00000000-0000-0000-0000-000000000001` | UUID for automated requests |

### Verification commands

```bash
# 1. Health check
curl http://localhost:8006/health

# 2. Create a request record
curl -s -X POST http://localhost:8006/normalize/request \
  -H "Content-Type: application/json" \
  -d '{"raw_input_text": "500 reams A4 paper", "channel": "web"}' | jq .
# Expected: {"request_id": "<uuid>"}

# 3. Full pipeline with persistence
curl -s -X POST http://localhost:8004/compare \
  -H "Content-Type: application/json" \
  -d '{"item":"A4 paper","descriptions":["80gsm"],"quantity":500,
       "location_coordinates":"12.97,77.59","delivery_timeline":72}'

# 4. Verify data in PostgreSQL
psql procurement_agent -c "SELECT status, created_at FROM procurement_requests ORDER BY created_at DESC LIMIT 5;"
psql procurement_agent -c "SELECT item_id, price, delivery_eta_hours FROM seller_offerings ORDER BY received_at DESC LIMIT 5;"
psql procurement_agent -c "SELECT rank, total_score FROM scored_offers ORDER BY scored_at DESC LIMIT 5;"
```

---

## Full Communication Diagram — All 6 Services

```
Browser
  │
  ├─ UI Step 1 ──► intention-parser:8001/parse  { query }         ← DIRECT call
  │                  └─ Ollama (host:11434) → qwen3:1.7b
  │                  └─ returns intent preview to user
  │
  └─ UI Step 2 ──► orchestrator:8004/compare  { BecknIntent }     ← user confirms
                     │
                     ├─ data-normalizer:8006/normalize/request    ← persist request
                     ├─ data-normalizer:8006/normalize/intent     ← persist intent
                     │
                     ├─ beckn-bap-client:8002/discover
                     │    ├─► onix-bap:8081 → catalog-normalizer:8005/normalize
                     │    │     └─ CatalogNormalizer (4 formats + LLM fallback)
                     │    └─► (async) on_discover → CallbackCollector
                     │
                     ├─ data-normalizer:8006/normalize/discovery  ← persist offerings
                     │
                     ├─ comparative-scoring:8003/score
                     │
                     ├─ data-normalizer:8006/normalize/scoring    ← persist scores
                     │
                     └─ beckn-bap-client:8002/select → /init → /confirm
                          └─ data-normalizer:8006/normalize/order ← persist PO
```

---

## Repository Layout (Phase 2 state)

```
Procurement-Agent/
├── services/
│   ├── intention-parser/     Lambda 1 — POST /parse              :8001
│   ├── beckn-bap-client/     Lambda 2 — POST /discover /select   :8002
│   ├── comparative-scoring/  Lambda 3 — POST /score              :8003
│   ├── orchestrator/         Step Functions — POST /run /compare :8004
│   ├── catalog-normalizer/   Lambda 4 — POST /normalize          :8005
│   └── data-normalizer/      Lambda 5 — POST /normalize/*        :8006
│       └── src/handler.py    6 routes + health
├── IntentParser/             NL module (volume-mounted)
├── CatalogNormalizer/        Catalog format module (volume-mounted)
├── ComparativeScoring/       Scoring module (volume-mounted)
├── DataNormalizer/           Persistence module (volume-mounted)
│   ├── repositories/         5 repo files (request, intent, discovery, scoring, order)
│   └── transformers/         3 transformer files
├── shared/models.py          BecknIntent, DiscoverOffering (source of truth)
├── database/sql/             16 SQL files — complete schema
├── config/                   ONIX routing YAML
├── docker-compose.yml        10 containers: 6 services + ONIX stack + redis
├── frontend/                 Next.js (port 3000)
└── Bap-1/                    Legacy monolith (preserved, no changes)
```

---

## Remaining Work (Phase 3)

| Component | Lambda | Port | Status |
|---|---|---|---|
| Negotiation Engine | Lambda 6 | 8007 (tentative) | ⏳ Not built |
| Approval Engine | Lambda 7 | 8008 (tentative) | ⏳ Not built |
| Agent Memory (RAG) | — | Qdrant | ⏳ Not built |
| Kafka Event Bus | — | 9092 | ⏳ Not built |
| ERP Integration | — | — | ⏳ Phase 4 |

*Preceded by → [[phase1_foundation_protocol_integration]] | Continues in → [[phase3_advanced_intelligence_enterprise_features]]*
