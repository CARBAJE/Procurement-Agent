# Data Normalizer — Persistence Bridge (port 8006)

## What Is It and Why It Exists

The Data Normalizer is the **persistence bridge** between the stateless microservices and the PostgreSQL database. Without it, all data flows through memory and is lost on restart.

**Main objective:** Receive raw data from each step of the procurement pipeline,
transform it to the PostgreSQL schema, and persist it while maintaining referential
integrity — without modifying the business logic of any existing microservice.

## Architecture

```
DataNormalizer/          ← real module at repo root (mounted as Docker volume)
├── __init__.py          ← exports DataNormalizer
├── normalizer.py        ← facade — orchestrates repos + transformers
├── db.py                ← asyncpg connection pool
├── repositories/        ← one file per DB table group
│   ├── request_repo.py  ← procurement_requests + status updates
│   ├── intent_repo.py   ← parsed_intents + beckn_intents
│   ├── discovery_repo.py← discovery_queries + seller_offerings + bpp upsert
│   ├── scoring_repo.py  ← scored_offers
│   └── order_repo.py    ← negotiation_outcomes + approval_decisions + purchase_orders
└── transformers/        ← source → PostgreSQL schema type conversions
    ├── offering_transformer.py
    ├── intent_transformer.py
    └── score_transformer.py

services/data-normalizer/   ← thin aiohttp wrapper
├── Dockerfile
├── requirements.txt
└── src/handler.py           ← 6 routes + health
```

## HTTP Routes

### `GET /health`
```json
{ "status": "ok", "service": "data-normalizer" }
```

### `POST /normalize/request`
Creates the root `procurement_requests` row.
```json
// Request
{ "raw_input_text": "500 reams A4 paper", "channel": "web", "requester_id": null }

// Response 201
{ "request_id": "<uuid>" }
```

### `POST /normalize/intent`
Creates `parsed_intents` + `beckn_intents` rows.
```json
// Request
{
  "request_id": "<uuid>",
  "intent_class": "procurement",
  "confidence": 0.97,
  "model_version": "qwen3:1.7b",
  "beckn_intent": { "item": "A4 paper", "quantity": 500, ... }
}

// Response 201
{ "intent_id": "<uuid>", "beckn_intent_id": "<uuid>" }
```

### `POST /normalize/discovery`
Creates `discovery_queries` row, upserts `bpp` rows, and creates one
`seller_offerings` row per offering.
```json
// Request
{
  "beckn_intent_id": "<uuid>",
  "network_id": "beckn-default",
  "offerings": [ /* DiscoverOffering dicts */ ]
}

// Response 201
{
  "query_id": "<uuid>",
  "offering_ids": [
    { "item_id": "item-a4-paperdirect", "offering_id": "<uuid>" },
    ...
  ]
}
```

### `POST /normalize/scoring`
Creates one `scored_offers` row per entry.
```json
// Request
{
  "query_id": "<uuid>",
  "scores": [
    { "offering_id": "<uuid>", "rank": 1, "composite_score": 0.85, "price_value": "168.00" },
    ...
  ]
}

// Response 201
{ "score_ids": [ { "offering_id": "<uuid>", "score_id": "<uuid>" }, ... ] }
```

### `POST /normalize/order`
Creates `negotiation_outcomes` + `approval_decisions` (auto) + `purchase_orders`.
```json
// Request
{
  "score_id": "<uuid>",
  "bpp_uri": "http://onix-bpp:8082/bpp/receiver",
  "item_id": "item-a4-paperdirect",
  "quantity": 500,
  "agreed_price": 168.00,
  "beckn_confirm_ref": "order-abc123",
  "delivery_terms": "Standard delivery",
  "currency": "INR"
}

// Response 201
{ "po_id": "<uuid>" }
```

### `PATCH /normalize/status`
Updates `procurement_requests.status` lifecycle column.
```json
// Request
{ "request_id": "<uuid>", "status": "scoring" }

// Response 200
{ "request_id": "<uuid>", "status": "scoring" }
```

## Normalization Logic Per Step

### Discovery (`DiscoverOffering` → `seller_offerings`)
| Source field | Source type | DB column | DB type | Transformation |
|---|---|---|---|---|
| `price_value` | `str` | `price` | `DECIMAL(15,2)` | `float(price_value)` |
| `bpp_uri` | `str` | `bpp_id` | `UUID` FK → `bpp` | find-or-create in `bpp` |
| `fulfillment_hours` | `Optional[int]` | `delivery_eta_hours` | `INTEGER NOT NULL` | default 24 if None |
| `rating` | `Optional[str]` | `quality_rating` | `FLOAT` 0–5 | `float(rating)` or None |
| `specifications` | `list[str]` | `certifications` | `JSONB` | `json.dumps()` |

### Intent (`BecknIntent` → `beckn_intents`)
| Source field | DB column | Transformation |
|---|---|---|
| `budget_constraints.min/max` | `budget_min/max` | unpack BudgetConstraints |
| `delivery_timeline` | `delivery_timeline_hours` | default 72 if None |
| `location_coordinates` | same | default `'0.0,0.0'` if None |
| `descriptions` | same | `json.dumps()` as JSONB |

### Scoring → `scored_offers`
| Source | DB column | Transformation |
|---|---|---|
| `composite_score` (0–1) | `total_score` (0–100) | `× 100`, clamped |
| `price_value` | `tco_value` | `float()` |

### Order → FK chain
`score_id` → `negotiation_outcomes` (strategy=skipped) → `approval_decisions` (auto_approved) → `purchase_orders`

## `procurement_status` State Machine

```
draft → parsing → discovering → scoring → negotiating → pending_approval → confirmed
                                                                          → cancelled
```

The orchestrator calls `PATCH /normalize/status` after each step:
- Before step 1 (parse): `parsing`
- After step 1: `discovering`
- After step 2 (discover): `scoring`
- After step 3 (score): `negotiating`
- After commit: `confirmed`

## Integration with Orchestrator

The orchestrator (`services/orchestrator/src/workflow.py`) calls the Data Normalizer
via `_persist()` (fire-and-forget, 5-second timeout, never raises). If the normalizer
is unreachable, the pipeline continues normally — persistence is best-effort.

```python
DATA_NORMALIZER_URL = os.getenv("DATA_NORMALIZER_URL", "http://localhost:8006")
```

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `DB_HOST` | `localhost` | PostgreSQL host |
| `DB_PORT` | `5432` | PostgreSQL port |
| `DB_NAME` | `procurement_agent` | Database name |
| `DB_USER` | `""` | PostgreSQL user |
| `DB_PASSWORD` | `""` | PostgreSQL password |
| `SYSTEM_USER_ID` | `00000000-0000-0000-0000-000000000001` | UUID of the system user auto-created for automated requests |

## Relationship to Other Components

| Component | Relationship |
|---|---|
| `orchestrator` | Calls data-normalizer after each pipeline step |
| `beckn-bap-client` | Produces `DiscoverOffering` data for `/normalize/discovery` |
| `comparative-scoring` | Produces ranking data for `/normalize/scoring` |
| `catalog-normalizer` | Independently normalizes catalog formats; data-normalizer handles DB persistence of the result |
| `shared/models.py` | `BecknIntent`, `DiscoverOffering` — source models for transformers |
