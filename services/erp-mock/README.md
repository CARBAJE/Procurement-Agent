# erp-mock — Local ERP Stub Server

An aiohttp stub server (port 8008) that emulates SAP S/4HANA OData, Oracle ERP Cloud REST, and a vendor-neutral mock surface. Enables the full `erp-adapter` integration loop without real ERP tenants.

All state is **in-memory and non-durable** — process restart resets all PO counters and idempotency records.

## Relationship to erp-adapter

`erp-mock` is the target when `ERP_VENDORS=mock` in `erp-adapter`. It provides the same HTTP surface that real SAP/Oracle tenants expose, allowing `erp-adapter` to be tested end-to-end without credentials or network access to a real ERP system.

## Endpoints

| Method | Path | Simulates |
|--------|------|-----------|
| GET | `/health` | Liveness |
| POST | `/mock/budget/check` | Vendor-neutral budget gate |
| POST | `/sap/budget/check` | SAP-shaped budget gate |
| POST | `/oracle/budget/check` | Oracle-shaped budget gate |
| POST | `/mock/policy/evaluate` | ERP policy evaluation → PolicyEnvelope |
| POST | `/mock/po/create` | Vendor-neutral PO creation |
| POST | `/sap/oauth2/token` | SAP OAuth2 client_credentials token |
| GET | `/sap/opu/odata/sap/API_PURCHASEORDER_PROCESS_SRV/A_PurchaseOrder` | SAP CSRF token fetch |
| POST | `/sap/opu/odata/sap/API_PURCHASEORDER_PROCESS_SRV/A_PurchaseOrder` | SAP PO creation |
| POST | `/oauth2/v1/token` | Oracle OAuth2 token |
| POST | `/fscmRestApi/resources/11.13.18.05/purchaseOrders` | Oracle PO creation |

## Scenarios

Select via `MOCK_SCENARIO` env var (process-wide) or `X-Mock-Scenario` request header (per-request override):

| Scenario | Budget | PO failures | Webhook delay | Policy |
|----------|--------|-------------|---------------|--------|
| `happy` (default) | allowed, 250,000 balance | 0 | 2s | standard |
| `budget_exhausted` | denied, 0 balance | 0 | — | — |
| `po_create_fails` | allowed | 10 before success | — | tests outbox retry |
| `webhook_delayed` | allowed | 0 | 30s | tests async timeout |
| `erp_approval_required` | allowed | 0 | — | approval_required=True |
| `erp_preferred_supplier` | allowed | 0 | — | preferred_supplier_ids=["preferred-bpp-001"] |

## Automatic webhook emission

After a successful `POST /mock/po/create`, the server schedules a signed `po-status` webhook to `WEBHOOK_TARGET_URL/api/v1/webhooks/mock/po-status` after `WEBHOOK_DELAY_SECONDS`. The webhook is HMAC-signed with `SAP_WEBHOOK_HMAC_SECRET` (shared with erp-adapter by convention). Override `WEBHOOK_TARGET_URL` at runtime for tests.

## Idempotency

All PO create endpoints honor `Idempotency-Key` header. A second request with the same key returns the stored response.

## Response shapes

| Endpoint | Key fields |
|----------|-----------|
| Budget (success) | `allowed: true, available_balance: "250000.00", hold_id: "hold-<uuid12>"` |
| Budget (denied) | `allowed: false, available_balance: "0.00", reasons: ["INSUFFICIENT_FUNDS"]` |
| SAP PO | `d.PurchaseOrder: "4500NNNNNNN"` |
| Oracle PO | `OrderNumber: "PO-OR-NNNNNN", Status: "Open"` |
| Mock PO | `erp_reference_id: "MOCK-PO-XXXXXXXXXX", vendor: "mock"` |
| Policy | `preferred_supplier_ids, approval_required, auto_commit_allowed, constraints` |

## Configuration

| Var | Default | Description |
|-----|---------|-------------|
| `PORT` | `8008` | Listen port |
| `MOCK_SCENARIO` | `happy` | Default scenario |
| `WEBHOOK_TARGET_URL` | `http://erp-adapter:8007` | Where to POST signed status webhooks |
| `WEBHOOK_DELAY_SECONDS` | `2.0` | Delay before firing webhook |
| `SAP_WEBHOOK_HMAC_SECRET` | `dev-sap-hmac-CHANGE_ME` | HMAC secret for webhook signing |
| `ORACLE_WEBHOOK_HMAC_SECRET` | `dev-oracle-hmac-CHANGE_ME` | Oracle HMAC (currently unused by mock emitter) |

## Run

```bash
docker compose up -d erp-mock
# Scenario override at request time:
curl -H "X-Mock-Scenario: budget_exhausted" http://localhost:8008/mock/budget/check ...
```
