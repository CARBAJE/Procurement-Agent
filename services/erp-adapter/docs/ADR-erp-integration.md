# ADR — ERP Integration (Phase 3 / Milestone 2)

Status: Implemented (M3.1 → M3.5).
Date: 2026-05-26.
Owner: Eduardo García Díaz.

This ADR captures the load-bearing architectural decisions for the SAP +
Oracle ERP integration. Each entry has the alternative considered and why
it was rejected — future maintainers should challenge the rejection on the
basis of evidence (load shape, vendor change, org direction), not nostalgia.

## 1. Topology: dedicated microservice, not in-process

**Decision.** All ERP logic — including the synchronous budget gate on the
`/commit` critical path — lives in `services/erp-adapter` (port 8007). The
orchestrator calls it over HTTP. Other BAP services hold zero vendor SDK
dependencies.

**Why.** Three forces:
1. Vendor SDKs are heavy and opinionated (SAP's OData CSRF dance, Oracle's
   IDCS JWT). Pulling them into the orchestrator bloats its blast radius
   and complicates its tests.
2. The ERP path needs its own resilience posture (retry, breaker, outbox,
   webhooks) — different from anything else the BAP does today.
3. A single dedicated service is the obvious migration target if the org
   later moves to a service mesh or to multiple PostgreSQL tenants per
   vendor — no orchestrator refactor needed.

**Rejected: in-process module under `services/orchestrator/src/erp/`.**
Less infra to operate, but the orchestrator becomes coupled to vendor SDKs
and a single ERP outage stalls its event loop.

**Rejected: budget gate inside the orchestrator, push in a sidecar.**
Splits the surface — two failure modes, two metric namespaces, two auth
gates. Not worth it for what is fundamentally one set of vendor responsibilities.

## 2. Outbox pattern, **inside the existing `erp_sync_records` table**

**Decision.** Migration 19 turns `erp_sync_records` (entity 13 in the schema)
into a durable retry queue by adding 8 operational columns: `idempotency_key`,
`attempts`, `next_attempt_at`, `lease_until`, `worker_id`, `last_error`,
`payload`, `updated_at`. No new table is created.

**Why.** The original schema already modelled "one row per sync operation"
with `sync_type` (`budget_check | po_creation | ...`) and `status`
(`pending | in_progress | completed | failed`). It was almost an outbox by
intent; the missing pieces were retry-state and idempotency.

**Why this matters operationally.** Adding a new table would split audit
queries: "show me everything that happened to this PO" would need a union
across two tables. Reusing 13 keeps the read path simple.

**Rejected: a separate `po_outbox` table.** Cleaner separation of concerns
on paper, but doubles the write path and forces analytics to join.

**Rejected: Kafka.** Operationally heavier (broker, schema registry,
consumer groups), and a single Postgres pool already gives us `FOR UPDATE
SKIP LOCKED` which is enough for horizontal scaling at the loads this
service will see (Phase-3 target: 100 PO/sec, p95 budget-check < 800 ms).

## 3. Independence from the session-persistence work

**Decision.** `erp-adapter` runs against its own asyncpg pool against its
own narrow schema (migrations 12, 13, 19). It does NOT touch
`TransactionSessionStore` — that stays in-memory until the persistence
teammate ships `PostgresBackend` (per `ARCHITECTURE.md §7.2 #6`).

**Why.** Decouples the milestone. Persistence slip should not stall ERP
delivery; ERP slip should not stall persistence.

## 4. Vendor-neutral Protocol + per-vendor mappers

**Decision.** `ERPAdapter` is a Pydantic-free `typing.Protocol` with five
methods. Concrete classes (`MockERPAdapter`, `SAPS4HanaAdapter`,
`OracleERPCloudAdapter`) implement it. A `MultiVendorAdapter` wraps multiple
when `ERP_VENDORS=sap,oracle`. Each concrete adapter has a pure mapping
function (`map_to_sap_purchase_order`, etc.) that is contract-tested via
JSON snapshots.

**Why.** Vendor schema drift is the single biggest fragility we will hit.
Pure mappers + snapshots make drift visible at PR time, not at 3am.

## 5. Synchronous budget gate, asynchronous PO push

**Decision.** Budget check blocks `/commit` with a hard 800 ms total
budget. PO push is fire-and-forget via the outbox.

**Why.** Spend governance must precede transaction commit (legal/SOX);
sync is correct. PO push to ERP is operationally allowed to lag a few
seconds — the user already sees their order confirmed on Beckn — so async
is correct.

**Fail-open vs fail-closed.** Default for budget is **fail-closed in prod
(`ERP_BUDGET_CHECK_REQUIRED=true`)**, fail-open in dev. Override per env.
DLQ items NEVER auto-retry — they require explicit replay via
`POST /api/v1/admin/outbox/{sync_id}/replay`.

## 6. HMAC dual-secret for inbound webhooks

**Decision.** Webhook verification accepts either of two configured
secrets — `{VENDOR}_WEBHOOK_HMAC_SECRET` (primary) and `_NEXT` (rotation).
Constant-time compare via `hmac.compare_digest`. Webhooks are exempt from
the internal Bearer middleware — HMAC IS the auth.

**Why.** A single-secret design forces a synchronous rotation window where
either side of the cutover drops traffic. Two-secret accept is the
operationally standard pattern; rotation becomes: set NEXT, deploy vendor
config, promote, clear NEXT.

## 7. Internal Bearer token, mTLS deferred

**Decision.** Orchestrator → adapter calls are authenticated by a shared
Bearer token (`ERP_INTERNAL_TOKEN`). The middleware is a one-line swap to
Keycloak-issued JWTs (`services/erp-adapter/src/middleware/auth.py`).

**Why.** This is the first auth gate anywhere in the active services
(per `ARCHITECTURE.md §7.3 #9` the rest is stubbed). Shipping a bearer is
strictly better than what existed; pretending to ship Keycloak today would
be a half-measure that blocks the persistence-teammate's work.

**Deferred: mTLS to vendor.** Required by some on-prem SAP tenants but not
by SAP Cloud Public Edition or Oracle Fusion. Cert paths are wired in
`SAPS4HanaAdapter` but no production tenant uses them yet — left for the
deployment hardening sprint.

## 8. pybreaker per-vendor circuit, NOT a global one

**Decision.** One `pybreaker.CircuitBreaker` per logical vendor (`mock`,
`sap`, `oracle`). `VendorPermanentError` is excluded from the fail counter
(bad payload should not trip the breaker). State transitions update the
`erp_circuit_state{vendor}` Gauge.

**Why.** A SAP outage must not fail Oracle calls and vice versa. A single
breaker would conflate the two; a per-vendor breaker preserves blast radius.

## 9. Observability foundation

- **Metrics.** 9 series in `observability/metrics.py`. Histograms for the
  two hot paths (budget-check, po-push) with buckets tuned to the SLO.
- **Audit log.** Dedicated `erp.audit` logger emits one JSONL event per
  meaningful business decision (10 event types). This is the ERP-scoped
  foundation for the broader `ARCHITECTURE.md §7.4 #12` audit-trail gap.
- **Tracing.** `traceparent` propagated from orchestrator into the adapter;
  spans attach `erp.vendor`, `erp.transaction_id`, `erp.amount`,
  `erp.outcome`. OTLP exporter via `OTEL_EXPORTER_OTLP_ENDPOINT`.

## What's deferred (intentionally)

| | Why deferred | Where to pick up |
|---|---|---|
| mTLS to vendor | No tenant requires it today | `security/oauth.py` (SSL context hook) |
| `cancel_po` API | M3.x scope was create + status; cancellation is a separate workflow | `SAPS4HanaAdapter.cancel_po` raises NotImplementedError |
| Per-tenant token cache (`MULTI_TENANT=true`) | Single-tenant is enough for the pilot | `OAuthTokenCache` keyed by `(token_url, client_id)` already |
| Cost-center in `BecknIntent` | Default env var works for the pilot | `ERP_DEFAULT_COST_CENTER` + parser extension |
| Real-time tracking via WebSocket | Polling is fine for the pilot; orchestrator already enriches via Redis pubsub | `ARCHITECTURE.md §7.4 #11` |
| EBS / on-prem SAP | Pilot targets Cloud editions only | New adapter file, same Protocol |
| Beckn-vs-ERP state precedence | Beckn canonical, discrepancies surfaced via `STATE_DISCREPANCY` audit | Business sign-off pending |
| Vault / AWS Secrets Manager for HMAC + OAuth secrets | Env vars are enough for the pilot | `SecretsProvider` Protocol slot left in `security/__init__.py` |

## References

- `services/erp-adapter/README.md` — operational overview.
- `services/erp-adapter/deploy/alerts.yaml` — Prometheus alert rules.
- `database/sql/19_erp_sync_records_outbox.sql` — the additive ALTER.
- `services/erp-adapter/tests/snapshots/` — contract snapshots.
- Plan: `~/.claude/plans/you-are-acting-as-purrfect-summit.md`.
