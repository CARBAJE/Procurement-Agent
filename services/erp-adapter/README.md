# erp-adapter

Vendor-neutral ERP integration microservice. Owns **all** SAP/Oracle traffic
for the procurement agent: the synchronous budget gate on the `/commit`
critical path, the asynchronous PO push to the vendor, and the inbound
webhook ingress that mirrors vendor-side state changes back into the agent.

```
┌──────────────┐   POST /api/v1/budget/check (sync, ≤800ms)
│ orchestrator │ ─────────────────────────────────────────┐
└──────┬───────┘                                          ▼
       │ POST /api/v1/po/sync (async, 202)         ┌─────────────┐
       └─────────────────────────────────────────► │ erp-adapter │
                                                   └──────┬──────┘
                                                          │
                              ┌───────────────────────────┤
                              │ outbox worker (asyncpg +  │ outbound
                              │ FOR UPDATE SKIP LOCKED)   │ SAP/Oracle
                              ▼                           ▼
                       erp_sync_records                vendor REST/OData
                       (PG row = outbox entry)
                                                          │ webhook
                                                          ▼
                              ┌────────────────  POST /api/v1/webhooks/{vendor}/po-status
                              │ HMAC verify, normalize, persist, Redis publish
                              ▼
                       po.status_changed:{txn_id}  (orchestrator subscribes)
```

## Endpoints

| Method | Path                                     | Auth          | Purpose |
|--------|------------------------------------------|---------------|---------|
| GET    | `/healthz`                               | public        | Liveness — process alive |
| GET    | `/readyz`                                | public        | DB + Redis + per-vendor healthcheck + outbox lag |
| GET    | `/metrics`                               | public        | Prometheus exposition |
| POST   | `/api/v1/budget/check`                   | bearer        | Synchronous budget gate (≤800ms) |
| POST   | `/api/v1/po/sync`                        | bearer        | Enqueue PO push — idempotent on `transaction_id` |
| GET    | `/api/v1/po/sync/{sync_id}`              | bearer        | Poll outbox row state |
| POST   | `/api/v1/admin/outbox/{sync_id}/replay`  | bearer        | Reset a DLQ row to `pending` |
| POST   | `/api/v1/webhooks/sap/po-status`         | HMAC          | Inbound from SAP S/4HANA |
| POST   | `/api/v1/webhooks/oracle/po-status`      | HMAC          | Inbound from Oracle ERP Cloud |
| POST   | `/api/v1/webhooks/mock/po-status`        | HMAC          | Inbound from `services/erp-mock` (dev only) |

`bearer` = `Authorization: Bearer ${ERP_INTERNAL_TOKEN}`. Webhooks verify
`X-{Vendor}-Signature: sha256=...` against `{VENDOR}_WEBHOOK_HMAC_SECRET`
(and `{VENDOR}_WEBHOOK_HMAC_SECRET_NEXT` during rotation).

## Environment variables

### Required

| Var | Default | Purpose |
|---|---|---|
| `DB_HOST` / `DB_PORT` / `DB_NAME` / `DB_USER` / `DB_PASSWORD` | localhost / 5432 / procurement_agent / postgres / postgres123 | Postgres for the outbox |
| `REDIS_URL` | `redis://redis:6379` | Pub/sub for `po.status_changed:*` |
| `ERP_INTERNAL_TOKEN` | dev-internal-token-CHANGE_ME | Bearer that orchestrator uses |
| `ERP_VENDORS` | `mock` | `mock`, `sap`, `oracle`, or `sap,oracle` |

### Vendor (only required if listed in `ERP_VENDORS`)

| Var | Used by | Notes |
|---|---|---|
| `SAP_OAUTH_TOKEN_URL` | sap | IDP token endpoint |
| `SAP_BASE_URL` | sap | OData v4 base (`.../API_PURCHASEORDER_PROCESS_SRV`) |
| `SAP_CLIENT_ID` / `SAP_CLIENT_SECRET` | sap | client_credentials |
| `SAP_BUDGET_CHECK_URL` | sap | Vendor-shaped budget endpoint |
| `SAP_WEBHOOK_HMAC_SECRET` / `_NEXT` | sap | Dual secret for zero-downtime rotation |
| `ORACLE_OAUTH_TOKEN_URL` / `ORACLE_BASE_URL` / `ORACLE_CLIENT_ID` / `ORACLE_CLIENT_SECRET` / `ORACLE_BUDGET_CHECK_URL` / `ORACLE_WEBHOOK_HMAC_SECRET` / `_NEXT` | oracle | Same shape as SAP |

### Tuning

| Var | Default | |
|---|---|---|
| `BUDGET_CHECK_TOTAL_TIMEOUT_MS` | 800 | Hard wall budget on `/commit`'s critical path |
| `BREAKER_FAIL_MAX` | 5 | Failures inside reset_timeout that open the circuit |
| `BREAKER_RESET_TIMEOUT_SECS` | 60 | Half-open delay |
| `WORKER_CONCURRENCY` | 10 | Outbox rows claimed per loop |
| `WORKER_BACKOFF_CSV` | `5,30,120,600,3600` | Per-attempt backoff seconds (length = MAX_ATTEMPTS) |
| `WORKER_POLL_INTERVAL_SECONDS` | 2.0 | Idle poll cadence |
| `LOG_PAYLOADS` | false | DEBUG payload logging (sensitive) |

## Swap to a real tenant (the four env vars)

For each vendor, replace the four vendor-shaped URLs and the two credentials.
**No code changes required.**

**SAP S/4HANA Cloud Public Edition**:
```bash
ERP_VENDORS=sap
SAP_OAUTH_TOKEN_URL=https://<tenant>.authentication.<region>.hana.ondemand.com/oauth/token
SAP_BASE_URL=https://<tenant>-api.<region>.cloud.sap/sap/opu/odata/sap/API_PURCHASEORDER_PROCESS_SRV
SAP_BUDGET_CHECK_URL=https://<tenant>-api.<region>.cloud.sap/sap/opu/odata/sap/API_COMMITMENT_ITEM/Availability
SAP_CLIENT_ID=<from BTP service key>
SAP_CLIENT_SECRET=<from BTP service key>
SAP_WEBHOOK_HMAC_SECRET=<configure in SAP Event Mesh subscription>
```

**Oracle ERP Cloud (Fusion)**:
```bash
ERP_VENDORS=oracle
ORACLE_OAUTH_TOKEN_URL=https://<tenant>.identity.oraclecloud.com/oauth2/v1/token
ORACLE_BASE_URL=https://<tenant>-fa.<region>.oraclecloud.com/fscmRestApi/resources/11.13.18.05
ORACLE_BUDGET_CHECK_URL=https://<tenant>-fa.<region>.oraclecloud.com/fscmRestApi/resources/11.13.18.05/budgetaryControlChecks
ORACLE_CLIENT_ID=<IDCS application>
ORACLE_CLIENT_SECRET=<IDCS application>
ORACLE_WEBHOOK_HMAC_SECRET=<configure in OIC integration>
```

Both: `ERP_VENDORS=sap,oracle` fans out — one outbox row per vendor, both
must succeed for the PO to be considered fully synchronized.

## Extending to a new vendor

1. Implement `services/erp-adapter/src/adapters/<vendor>.py` against the
   `ERPAdapter` Protocol (`base.py`). Add a `map_to_<vendor>_purchase_order`
   pure function and a snapshot under `tests/snapshots/<vendor>_po_request.json`.
2. Register in `adapters/factory.py`.
3. Add `<VENDOR>_*` env vars to `config.py` and `docker-compose.yml`.
4. Mock the surface in `services/erp-mock/src/<vendor>_routes.py` to keep the
   in-process smoke tests working.

## Local development

### Prerequisite: Postgres container on `beckn_network`

The compose stack does NOT manage the Postgres lifecycle — you bring your own
container. Make sure it's attached to the `beckn_network` so DNS resolves the
hostname `procurement-postgres`:

```powershell
# Verify
docker network inspect beckn_network --format "{{range .Containers}}{{.Name}} {{end}}"

# If `procurement-postgres` is not listed:
docker network connect beckn_network procurement-postgres
```

### One-time schema bootstrap (manual)

The compose stack assumes the schema is already applied. Run the migrations
once (and again whenever a new `NN_*.sql` is added) — see
`database/README.md` for full instructions, but the short version is:

```powershell
# Easiest: pipe the new migration files into the running Postgres container.
Get-Content database/sql/19_erp_enum_extensions.sql | docker exec -i procurement-postgres psql -U postgres -d procurement_agent
Get-Content database/sql/19b_erp_sync_records_outbox.sql | docker exec -i procurement-postgres psql -U postgres -d procurement_agent
```

For a fresh database, run the full setup script instead (requires Python +
psycopg2-binary locally):

```powershell
$env:DB_HOST = "localhost"
$env:DB_PASSWORD = "postgres123"
python database/setup_database.py --create-db --continue-on-exists
```

The adapter falls back to `InMemoryOutboxRepo` if the DB schema isn't there
yet — useful for testing without DB, but POs are NOT durable in that mode.

### Run the stack

```powershell
docker compose up -d redis erp-mock erp-adapter

# Bearer token used in the dev compose:
$TOKEN = "dev-internal-token-CHANGE_ME"

curl -sS http://localhost:8007/healthz
curl -sS http://localhost:8007/readyz | jq

# Budget check (synchronous)
curl -sS -X POST http://localhost:8007/api/v1/budget/check \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"transaction_id":"demo-1","cost_center":"CC-IND-PROC-01","requested_amount":"12500.00"}'

# PO sync (enqueue)
curl -sS -X POST http://localhost:8007/api/v1/po/sync \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d @sample-po.json
```

`X-Mock-Scenario` header (only honored by mock-erp): `happy`,
`budget_exhausted`, `po_create_fails`, `webhook_delayed`.

## Tests

```bash
# Contract — pins the wire shape for SAP + Oracle mappers
PYTHONIOENCODING=utf-8 python services/erp-adapter/tests/test_contracts.py

# Smokes — in-process aiohttp servers, no docker required
PYTHONIOENCODING=utf-8 python services/erp-adapter/tests/smoke_m31.py   # budget gate
PYTHONIOENCODING=utf-8 python services/erp-adapter/tests/smoke_m32.py   # outbox + DLQ
PYTHONIOENCODING=utf-8 python services/erp-adapter/tests/smoke_m33.py   # bidirectional webhooks
PYTHONIOENCODING=utf-8 python services/erp-adapter/tests/smoke_m34.py   # SAP/Oracle real + breaker
PYTHONIOENCODING=utf-8 python services/erp-adapter/tests/smoke_m35.py   # readyz + DLQ replay
```

## Observability

- `/metrics` exposes 9 series; see `src/observability/metrics.py`.
- `erp.audit` logger emits one JSON line per business event: `BUDGET_CHECK`,
  `PO_SYNC_ENQUEUED`, `PO_SYNC_ATTEMPT`, `PO_SYNC_SENT`, `PO_SYNC_RETRY`,
  `PO_DLQ`, `PO_REPLAY`, `WEBHOOK_RECEIVED`, `WEBHOOK_REJECTED`,
  `STATE_DISCREPANCY` (orchestrator-side).
- `deploy/alerts.yaml` ships 6 Prometheus alerting rules tuned to the SLO
  budgets in this README.

## Related docs

- `services/erp-adapter/docs/ADR-erp-integration.md` — Architecture Decision
  Record (why microservice, why outbox-not-Kafka, why HMAC dual-secret,
  what's deferred).
- `Bap-1/docs/ARCHITECTURE.md §7` — historical Phase-2 production blocker
  list. Predates the microservices migration; useful for protocol-level
  intent only — file-path references inside it point to the deprecated
  monolith.
