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

---

## Testing Guide — Frontend Flow

> Tests in this section cover **only the path the browser takes**: Step 1 (direct call to intention-parser)
> and Steps 2→3→4 (via orchestrator). The Data Normalizer is called automatically by the orchestrator
> after each step — the frontend never calls it directly.

### Prerequisites

```bash
# 1. Full stack running
docker compose up --build

# 2. All 6 services healthy
curl -s http://localhost:8001/health | jq .status   # "ok"
curl -s http://localhost:8002/health | jq .status   # "ok"
curl -s http://localhost:8003/health | jq .status   # "ok"
curl -s http://localhost:8004/health | jq .status   # "ok"
curl -s http://localhost:8005/health | jq .status   # "ok"
curl -s http://localhost:8006/health | jq .status   # "ok"

# 3. PostgreSQL accessible
psql -U cristianmontiel -d procurement_agent -c "SELECT COUNT(*) FROM procurement_requests;"
```

---

### Test A — Health Check

**Goal:** Confirm the Data Normalizer container is up and the DB connection pool is ready.

```bash
curl -s http://localhost:8006/health | jq .
```

**Expected response:**
```json
{ "status": "ok", "service": "data-normalizer" }
```

**Failure signals:** `Connection refused` → container not running. `500` → asyncpg failed to connect to PostgreSQL.

---

### Test B — Frontend Step 1: NL Parse + Persistence

**Goal:** The browser calls `intention-parser:8001/parse` directly. The intent is returned immediately and **no** data-normalizer call is made at this stage — persistence begins only when the orchestrator runs.

```bash
# Simulate the exact call the browser makes (Step 1)
curl -s -X POST http://localhost:8001/parse \
  -H "Content-Type: application/json" \
  -d '{"query": "I need 500 reams of A4 paper for the Mumbai office"}' | jq .
```

**Expected response shape:**
```json
{
  "item": "A4 paper",
  "quantity": 500,
  "descriptions": ["standard office paper"],
  "unit": "reams",
  "location_coordinates": "19.0760,72.8777",
  "delivery_timeline": 72,
  "budget_constraints": null
}
```

**DB check — should be EMPTY at this point (no orchestrator call yet):**
```sql
SELECT COUNT(*) FROM procurement_requests;
-- Expected: same count as before this test
```

---

### Test C — Frontend Step 2: Compare Flow + Full Persistence Chain

**Goal:** The browser sends the parsed intent to `orchestrator:8004/compare`. The orchestrator calls
`beckn-bap-client → comparative-scoring` and then persists each step via the Data Normalizer.
After this call, five DB tables must have new rows.

```bash
RESPONSE=$(curl -s -X POST http://localhost:8004/compare \
  -H "Content-Type: application/json" \
  -d '{
    "item": "A4 paper",
    "descriptions": ["80gsm", "500 sheets per ream"],
    "quantity": 500,
    "unit": "reams",
    "location_coordinates": "12.9716,77.5946",
    "delivery_timeline": 72
  }')

echo "$RESPONSE" | jq .
```

**Expected response shape:**
```json
{
  "ranked_offerings": [
    {
      "item_id": "item-a4-paperdirect",
      "provider_name": "PaperDirect",
      "price_value": "168.00",
      "currency": "INR",
      "rank": 1
    }
  ],
  "transaction_id": "<uuid>",
  "query_id": "<uuid>"
}
```

**DB verification — all 5 rows must exist:**
```sql
-- 1. Root request row (status = negotiating after compare)
SELECT request_id, raw_input_text, status, created_at
FROM procurement_requests
ORDER BY created_at DESC LIMIT 1;
-- Expected: status = 'negotiating'

-- 2. Parsed intent
SELECT intent_id, intent_class, confidence, model_version
FROM parsed_intents
ORDER BY created_at DESC LIMIT 1;
-- Expected: intent_class = 'procurement'

-- 3. Beckn intent with defaults applied
SELECT beckn_intent_id, item, quantity, unit, location_coordinates,
       delivery_timeline_hours, budget_min, budget_max
FROM beckn_intents
ORDER BY created_at DESC LIMIT 1;
-- Expected: unit='reams', location_coordinates='12.9716,77.5946'

-- 4. Discovery query + seller offerings
SELECT sq.query_id, COUNT(so.offering_id) AS num_offerings
FROM discovery_queries sq
JOIN seller_offerings so ON so.query_id = sq.query_id
GROUP BY sq.query_id
ORDER BY sq.created_at DESC LIMIT 1;
-- Expected: num_offerings >= 1

-- 5. Scored offers with 0-100 scale
SELECT offering_id, rank, total_score, tco_value
FROM scored_offers
ORDER BY created_at DESC LIMIT 3;
-- Expected: total_score between 0 and 100 (not 0 to 1)
```

---

### Test D — Frontend Step 3: Commit Flow + Purchase Order Chain

**Goal:** The browser picks the top-ranked offering and calls `orchestrator:8004/commit`. The orchestrator
confirms with Beckn and persists the full FK chain: `negotiation_outcomes → approval_decisions → purchase_orders`.

```bash
# Use the transaction_id and item_id from Test C response
COMMIT_RESPONSE=$(curl -s -X POST http://localhost:8004/commit \
  -H "Content-Type: application/json" \
  -d '{
    "transaction_id": "<transaction_id from Test C>",
    "item_id": "item-a4-paperdirect",
    "quantity": 500
  }')

echo "$COMMIT_RESPONSE" | jq .
```

**Expected response shape:**
```json
{
  "status": "confirmed",
  "order_id": "<beckn-order-id>",
  "po_id": "<uuid>",
  "item_id": "item-a4-paperdirect",
  "agreed_price": 168.00
}
```

**DB verification — full FK chain:**
```sql
-- Full purchase order chain (one query)
SELECT
  pr.request_id,
  pr.status                        AS request_status,
  po.po_id,
  po.item_id,
  po.quantity,
  po.agreed_price,
  po.currency,
  po.beckn_confirm_ref,
  po.status                        AS po_status,
  ad.status                        AS approval_status,
  no2.strategy_applied,
  no2.discount_percent
FROM purchase_orders po
JOIN approval_decisions ad  ON ad.approval_id  = po.approval_id
JOIN negotiation_outcomes no2 ON no2.negotiation_id = ad.negotiation_id
JOIN scored_offers so       ON so.score_id     = no2.score_id
JOIN seller_offerings sof   ON sof.offering_id = so.offering_id
JOIN discovery_queries dq   ON dq.query_id     = sof.query_id
JOIN beckn_intents bi       ON bi.beckn_intent_id = dq.beckn_intent_id
JOIN parsed_intents pi      ON pi.beckn_intent_id = bi.beckn_intent_id
JOIN procurement_requests pr ON pr.request_id  = pi.request_id
ORDER BY po.created_at DESC LIMIT 1;
```

**Expected values:**
| Column | Expected |
|---|---|
| `request_status` | `confirmed` |
| `po_status` | `pending` |
| `approval_status` | `auto_approved` |
| `strategy_applied` | `skipped` |
| `discount_percent` | `0.0` |
| `beckn_confirm_ref` | non-null Beckn order ID |

---

### Test E — Status Lifecycle Verification

**Goal:** Confirm the `procurement_requests.status` state machine transitions correctly across the full frontend flow.

```bash
# After a complete flow (Tests B + C + D), query the latest request
psql -U cristianmontiel -d procurement_agent -c "
SELECT request_id, status, updated_at
FROM procurement_requests
ORDER BY created_at DESC LIMIT 1;
"
```

**Expected status after each stage:**

| Frontend Action | Expected `status` |
|---|---|
| After `POST /compare` starts | `parsing` |
| After intent parsed | `discovering` |
| After Beckn discover completes | `scoring` |
| After scoring completes | `negotiating` |
| After `POST /commit` completes | `confirmed` |

---

### Test F — Data Normalizer Resilience

**Goal:** Verify that if the Data Normalizer is down, the frontend flow still returns live data (no crash).
Persistence is best-effort — the orchestrator never fails because of it.

```bash
# 1. Stop only the data-normalizer container
docker compose stop data-normalizer

# 2. Run a full compare — must still return offerings
curl -s -X POST http://localhost:8004/compare \
  -H "Content-Type: application/json" \
  -d '{
    "item": "A4 paper",
    "descriptions": ["80gsm"],
    "quantity": 500,
    "location_coordinates": "12.9716,77.5946",
    "delivery_timeline": 72
  }' | jq .ranked_offerings
# Expected: array of offerings (pipeline not blocked)

# 3. Verify DB did NOT get new rows (normalizer was down)
psql -U cristianmontiel -d procurement_agent -c "
SELECT COUNT(*) FROM procurement_requests;
"
# Expected: same count as before step 2

# 4. Restart the normalizer
docker compose start data-normalizer
```

---

### Test G — End-to-End Verification Script

```bash
#!/usr/bin/env bash
# data_normalizer_frontend_flow_test.sh
# Runs the complete frontend flow and verifies persistence at each step.

set -euo pipefail
BASE_ORCHESTRATOR="http://localhost:8004"
BASE_NORMALIZER="http://localhost:8006"
PG="psql -U cristianmontiel -d procurement_agent -t -A"

echo "=== [0] Health checks ==="
curl -sf "$BASE_NORMALIZER/health" | grep -q '"ok"' && echo "  data-normalizer: OK" || { echo "  data-normalizer: FAIL"; exit 1; }

echo ""
echo "=== [1] Step 1 — Parse (direct to intention-parser, no DB write expected) ==="
PARSE_RESULT=$(curl -sf -X POST http://localhost:8001/parse \
  -H "Content-Type: application/json" \
  -d '{"query": "500 reams A4 paper for the Delhi office"}')
echo "$PARSE_RESULT" | jq '{item, quantity, unit}'
ROWS_BEFORE=$($PG -c "SELECT COUNT(*) FROM procurement_requests;")
echo "  procurement_requests rows before compare: $ROWS_BEFORE"

echo ""
echo "=== [2] Step 2 — Compare (orchestrator persists intent + discovery + scoring) ==="
COMPARE_RESULT=$(curl -sf -X POST "$BASE_ORCHESTRATOR/compare" \
  -H "Content-Type: application/json" \
  -d "$(echo "$PARSE_RESULT" | jq '. + {"descriptions": ["80gsm"]}')")
echo "$COMPARE_RESULT" | jq '{transaction_id, num_offerings: (.ranked_offerings | length)}'

TXN_ID=$(echo "$COMPARE_RESULT" | jq -r '.transaction_id')
ITEM_ID=$(echo "$COMPARE_RESULT" | jq -r '.ranked_offerings[0].item_id')

sleep 1  # give fire-and-forget persist time to complete

ROWS_AFTER=$($PG -c "SELECT COUNT(*) FROM procurement_requests;")
echo "  procurement_requests rows after compare: $ROWS_AFTER"
[ "$ROWS_AFTER" -gt "$ROWS_BEFORE" ] && echo "  ✓ New request persisted" || echo "  ✗ No new request found"

REQUEST_STATUS=$($PG -c "SELECT status FROM procurement_requests ORDER BY created_at DESC LIMIT 1;")
echo "  Request status: $REQUEST_STATUS (expected: negotiating)"
[ "$REQUEST_STATUS" = "negotiating" ] && echo "  ✓ Status correct" || echo "  ✗ Unexpected status: $REQUEST_STATUS"

OFFERING_COUNT=$($PG -c "SELECT COUNT(*) FROM seller_offerings ORDER BY received_at DESC;" )
echo "  seller_offerings total rows: $OFFERING_COUNT"

SCORED_COUNT=$($PG -c "SELECT COUNT(*) FROM scored_offers;")
echo "  scored_offers total rows: $SCORED_COUNT"

echo ""
echo "=== [3] Step 3 — Commit (orchestrator creates purchase order FK chain) ==="
COMMIT_RESULT=$(curl -sf -X POST "$BASE_ORCHESTRATOR/commit" \
  -H "Content-Type: application/json" \
  -d "{\"transaction_id\": \"$TXN_ID\", \"item_id\": \"$ITEM_ID\", \"quantity\": 500}")
echo "$COMMIT_RESULT" | jq '{status, order_id, po_id}'

sleep 1

PO_COUNT=$($PG -c "SELECT COUNT(*) FROM purchase_orders;")
echo "  purchase_orders total rows: $PO_COUNT"

FINAL_STATUS=$($PG -c "SELECT status FROM procurement_requests ORDER BY created_at DESC LIMIT 1;")
echo "  Final request status: $FINAL_STATUS (expected: confirmed)"
[ "$FINAL_STATUS" = "confirmed" ] && echo "  ✓ Status correct" || echo "  ✗ Unexpected status: $FINAL_STATUS"

echo ""
echo "=== Done ==="
```
