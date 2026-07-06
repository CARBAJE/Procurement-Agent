# Phase 3 — Audit Trail System: Test & Verification Guide

> Component: [[audit_trail_system]]
> Branch: `feature/agent-memory-learning`
> Spec: `components/audit_trail_system.md`

---

## What is implemented

### Deployed architecture

```
Agent action (any pipeline step)
        ↓
orchestrator: await _persist_audit(session, event_type, agent_action,
                                   reasoning_payload, request_id, po_id)
  └─ fire-and-forget — never interrupts the main flow
        ↓
POST /normalize/audit   (data-normalizer :8006)
        ↓
INSERT INTO audit_trail_events (PostgreSQL 16)
  - event_type:        audit_event_type ENUM (9 values)
  - agent_action:      TEXT (action description)
  - reasoning_payload: JSONB (inputs, outputs, scores, LLM traces)
  - kafka_offset:      BIGINT (placeholder for future Kafka integration)
  - retention_until:   NOW() + 7 years  (SOX 404 / GDPR / IT Act 2000)

─────────────────────────────────────────────────────────────────────

Audit query (compliance officer / frontend)
        ↓
GET /normalize/audit?request_id=X         ← full decision chain for a request
GET /normalize/audit?po_id=X              ← events for a confirmed PO
GET /normalize/audit/{event_id}           ← individual event with full payload
        ↓
Frontend: /request/{id}/audit
  └─ AuditTrailPanel (vertical timeline, collapsible payload)
```

### Write points in the pipeline (20+ events)

| Stage | event_type | agent_action |
|---|---|---|
| Request creation | `normalize` | `request_created` |
| Intent persistence | `normalize` | `intent_persisted` |
| Discovery execution | `discover` | `discovery_executed` |
| Offer scoring | `score` | `offerings_scored` |
| Negotiation | `negotiate` | `negotiation_step` / `counter_sent` |
| Order confirmation | `confirm` | `order_confirmed` |
| PO status change | `normalize` | `po_status_updated` |
| User override | `override` | `user_overrode_recommendation` |
| Notification sent | `notification` | `notification_sent` |
| ERP sync | `erp_sync` | `erp_budget_checked` / `erp_po_created` |

### Key files

| File | Role |
|---|---|
| `database/sql/14_audit_trail_events.sql` | Schema: table + `audit_event_type` enum |
| `database/sql/17_indexes.sql` | 4 optimized indexes (request, type, po, splunk_pending) |
| `DataNormalizer/repositories/audit_repo.py` | Write: `create_audit_event()` · Read: `get_events_by_request()`, `get_events_by_po()`, `get_event_by_id()` |
| `DataNormalizer/normalizer.py` | Facade: `normalize_audit()` + 3 getters |
| `services/data-normalizer/src/handler.py` | `POST /normalize/audit` + `GET /normalize/audit` + `GET /normalize/audit/{event_id}` |
| `services/orchestrator/src/workflow.py` | `_persist_audit()` + 20+ call sites |
| `frontend/src/app/api/audit/route.ts` | Next.js proxy → data-normalizer |
| `frontend/src/components/procurement/AuditTrailPanel.tsx` | Timeline with per-type icons and collapsible payload |
| `frontend/src/components/procurement/AuditTrailView.tsx` | Client component with async load + error state |
| `frontend/src/app/request/[id]/audit/page.tsx` | SSR authenticated page |

### Implementation vs. spec

| Aspect | Spec | Implemented |
|---|---|---|
| Event bus | Kafka (7-year retention, replication ≥ 3) | `kafka_offset` column exists as placeholder; real publishing deferred to Phase 4 |
| SIEM sink | Splunk + ServiceNow batch consumer | `splunk_indexed` column exists; exporter deferred to Phase 4 |
| LLM traces | LangSmith integration | `reasoning_payload` captures all data; LangSmith wiring deferred to Phase 4 |
| Retention enforcement | Nightly DELETE/archival job | `retention_until` column exists; cleanup job deferred to Phase 4 |

---

## Prerequisites

```bash
# 1. Full stack must be running
docker compose up -d
docker compose ps   # data-normalizer and orchestrator must show Up

# 2. Verify the table schema
psql -U postgres -d procurement_agent -c "\d audit_trail_events"
# Must show: event_id, request_id, po_id, actor_id, event_type,
#            agent_action, reasoning_payload, kafka_offset,
#            splunk_indexed, event_timestamp, retention_until

# 3. Verify the write endpoint responds
curl -s http://localhost:8006/health
# → {"status": "ok", "service": "data-normalizer"}
```

---

## Test 1 — Write Path: verify events are written during a procurement flow

### Step 1 — Check initial event count

```bash
psql -U postgres -d procurement_agent -c \
  "SELECT COUNT(*) FROM audit_trail_events;"
```

### Step 2 — Complete a full order in the frontend

1. Open `http://localhost:3000` and log in
2. Enter: **"200 reams A4 paper Chennai 2 days"**
3. Wait for suppliers to appear with scoring
4. Select a supplier → click **Commit / Confirm Order**
5. Wait for the status to advance to `confirmed`

### Step 3 — Verify events in the database

```bash
psql -U postgres -d procurement_agent -c "
SELECT event_type, agent_action, event_timestamp
FROM audit_trail_events
ORDER BY event_timestamp DESC
LIMIT 10;"
```

**Expected result** — at least these events in chronological order:

| event_type | agent_action |
|---|---|
| `normalize` | `request_created` |
| `normalize` | `intent_persisted` |
| `discover` | `discovery_executed` |
| `score` | `offerings_scored` |
| `confirm` | `order_confirmed` |

Also in orchestrator logs:

```bash
docker compose logs orchestrator | grep "audit"
# → INFO:__main__:[audit] normalize (request_created) → <event_id>
# → INFO:__main__:[audit] confirm (order_confirmed) → <event_id>
```

### Step 4 — Write a manual event via API

```bash
curl -s -X POST http://localhost:8006/normalize/audit \
  -H "Content-Type: application/json" \
  -d '{
    "event_type":        "score",
    "agent_action":      "manual test event",
    "reasoning_payload": {"items": 3, "top_score": 0.92}
  }' | python3 -m json.tool
# → {"event_id": "<uuid>"}
```

---

## Test 2 — Read Path: query the decision chain for a request

> Requires Test 1 to have been completed (at least 1 confirmed order with a `request_id`).

### Step 1 — Get the request_id

```bash
psql -U postgres -d procurement_agent -c "
SELECT request_id, raw_input_text, created_at
FROM procurement_requests
ORDER BY created_at DESC LIMIT 3;"
```

### Step 2 — Query all events for that request

```bash
export REQUEST_ID="<uuid-from-step-1>"

curl -s "http://localhost:8006/normalize/audit?request_id=$REQUEST_ID" \
  | python3 -m json.tool
```

**Expected result:**

```json
{
  "count": 5,
  "events": [
    {
      "event_id": "...",
      "event_type": "normalize",
      "agent_action": "request_created",
      "reasoning_payload": {"raw_query": "200 reams A4 paper..."},
      "event_timestamp": "2026-07-06T10:23:01.123456",
      "retention_until": "2033-07-06T10:23:01.123456",
      "splunk_indexed": false
    },
    ...
  ]
}
```

The full decision chain must be **reconstructible solely from these events** — no application state required (SOX 404 compliance).

### Step 3 — Query an individual event

```bash
export EVENT_ID=$(curl -s "http://localhost:8006/normalize/audit?request_id=$REQUEST_ID" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['events'][0]['event_id'])")

curl -s "http://localhost:8006/normalize/audit/$EVENT_ID" | python3 -m json.tool
# → full event with expanded reasoning_payload
```

### Step 4 — Query by PO (post-confirmation)

```bash
export PO_ID=$(psql -U postgres -d procurement_agent -At -c \
  "SELECT po_id FROM purchase_orders ORDER BY created_at DESC LIMIT 1;")

curl -s "http://localhost:8006/normalize/audit?po_id=$PO_ID" \
  | python3 -m json.tool
# → confirm, erp_sync, notification events linked to that PO
```

---

## Test 3 — Frontend: audit trail visualization in the browser

> Requires a confirmed order with a known `request_id`.

### Step 1 — Navigate to the audit trail page

```
http://localhost:3000/request/<request_id>/audit
```

### Step 2 — Verify the timeline

The page must show the **AuditTrailPanel** component with:

- One node per event, in chronological order (ASC)
- Distinct icon and color per type (`normalize`=grey, `score`=purple, `confirm`=green, `override`=orange …)
- Badge showing the event type
- Formatted timestamp (`Jul 6, 2026, 10:23 AM`)
- **"Show reasoning payload"** button that expands the full JSON

### Step 3 — Verify the empty state

Navigate with a `request_id` that has no events:

```
http://localhost:3000/request/00000000-0000-0000-0000-000000000000/audit
```

Must show the empty state with an icon and the message "No audit events recorded yet."

---

## Test 4 — Endpoint validations

```bash
# Invalid event_type → 400
curl -s -X POST http://localhost:8006/normalize/audit \
  -H "Content-Type: application/json" \
  -d '{"event_type": "invalid_type", "agent_action": "test"}' -w "\n%{http_code}"
# → 400

# Missing agent_action → 400
curl -s -X POST http://localhost:8006/normalize/audit \
  -H "Content-Type: application/json" \
  -d '{"event_type": "score"}' -w "\n%{http_code}"
# → 400

# GET without required params → 400
curl -s "http://localhost:8006/normalize/audit" -w "\n%{http_code}"
# → 400  (request_id or po_id query parameter is required)

# GET non-existent event_id → 404
curl -s "http://localhost:8006/normalize/audit/00000000-0000-0000-0000-000000000000" \
  -w "\n%{http_code}"
# → 404
```

---

## Automated tests

```bash
cd services/data-normalizer
PYTHONPATH=<repo_root> .venv-test/bin/python -m pytest tests/test_endpoints.py -k "audit" -v

# Expected output (10 tests):
# PASSED test_post_audit_appends_event
# PASSED test_validation_errors_return_400[/normalize/audit-body7]
# PASSED test_validation_errors_return_400[/normalize/audit-body8]
# PASSED test_audit_get_by_request_id_returns_events
# PASSED test_audit_get_by_request_id_empty_when_no_events
# PASSED test_audit_get_by_po_id_returns_events
# PASSED test_audit_get_missing_param_returns_400
# PASSED test_audit_get_event_by_id
# PASSED test_audit_get_event_by_id_not_found_404
# PASSED test_audit_get_limit_respected
```

---

## Troubleshooting

### No events appear in the database after an order

```bash
docker compose logs orchestrator | grep -E "audit|persist"
# No lines → _persist_audit() is not being called
# "WARNING [persist_audit] failed" → data-normalizer is unavailable
```

Verify `DATA_NORMALIZER_URL` is configured in the orchestrator:

```bash
docker compose exec orchestrator env | grep DATA_NORMALIZER
# → DATA_NORMALIZER_URL=http://data-normalizer:8006
```

### `GET /normalize/audit` returns 500

Verify that `audit_trail_events` has all expected columns:

```bash
psql -U postgres -d procurement_agent -c "\d audit_trail_events"
```

If `retention_until` is missing, the migration `14_audit_trail_events.sql` did not apply cleanly. Re-run:

```bash
python database/setup_database.py
```

### Frontend shows "data-normalizer unavailable" (502)

The Next.js proxy at `/api/audit/route.ts` reads `DATA_NORMALIZER_URL` from the server-side Next.js environment, not from the Docker container. For local development:

```bash
# frontend/.env.local
DATA_NORMALIZER_URL=http://localhost:8006
```

### Events have empty `reasoning_payload: {}`

This is valid — the orchestrator omits the payload on low-level events. For scoring and confirm events the payload must contain content:

```bash
psql -U postgres -d procurement_agent -c "
SELECT agent_action, jsonb_pretty(reasoning_payload)
FROM audit_trail_events
WHERE event_type = 'score'
ORDER BY event_timestamp DESC LIMIT 1;"
```

---

## Phase 3 Acceptance Checklist

- [ ] `audit_trail_events` exists with `audit_event_type` enum and 9 valid values
- [ ] `POST /normalize/audit` returns `{"event_id": "<uuid>"}` with status 201
- [ ] `GET /normalize/audit?request_id=X` returns the full event chain in chronological order
- [ ] `GET /normalize/audit/{event_id}` returns the individual event with `reasoning_payload`
- [ ] After confirming an order in the frontend, at least 4 events are automatically persisted
- [ ] `retention_until` is `event_timestamp + 7 years` on all events
- [ ] Frontend `/request/{id}/audit` shows the timeline with per-type icons and collapsible payloads
- [ ] Validations return 400 for invalid `event_type` and missing `agent_action`
- [ ] A non-existent `event_id` returns 404
- [ ] The decision chain is **reconstructible solely from the events** — no application state required (SOX 404)
