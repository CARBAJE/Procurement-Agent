---
name: beckn-protocol-guide
description: Beckn Protocol v2.0.0/v2.1 wire-shape rules and hard-won gotchas for this BAP. Auto-invoke when editing anything under Bap-1/src/beckn/, services/beckn-bap-client/, ONIX routing in config/*.yaml, or any code that builds /discover, /select, /init, /confirm, /status payloads.
tools: Read, Grep, Glob, Edit, Bash
---

# Beckn Protocol guidance for THIS project

Authoritative source: `Bap-1/CLAUDE.md` (read it first when in doubt — it is hand-curated by the team and explains the *why*). Architecture deep-dive: `Bap-1/docs/ARCHITECTURE.md`. ADR for async discovery: `docs/architecture/decisions/0001-use-redis-pubsub-for-async-beckn-responses.md`.

## What this BAP does

Python BAP (Buyer App) talks to BPPs (Sellers) **only** through the `onix-bap` Go adapter (port 8081). Never POST to a BPP directly. ONIX handles ED25519 signing and routing.

- Discovery is **inherently async**: `POST /bap/caller/discover` returns ACK only; the catalog arrives later as `POST /on_discover` webhook.
- Two correlation patterns coexist:
  1. `CallbackCollector` (one `asyncio.Queue` per `(transaction_id, action)`) — used inside `Bap-1/src/beckn/`.
  2. **Redis Pub/Sub** on channel `beckn_results:{transaction_id}` — used between `services/mcp-sidecar/` and `services/beckn-bap-client/`. See `redis-pubsub-discovery` skill.

## The 8 wire-shape gotchas (do NOT regress these)

These were discovered by running the full `/discover → /select → /init → /confirm → /status` against the live ONIX Go validator. The unit tests mock HTTP and would not have caught them.

1. **`Contract` is `additionalProperties: false`.** Only `id, commitments, consideration, participants, performance, settlements, status, descriptor, contractAttributes` are allowed. Buyer billing goes in `participants[role=buyer]` (permissive); fulfillment goes in `performance[]` (strict envelope); payment in `settlements[]`.
2. **`Contract.commitments` is required EVERYWHERE a Contract appears** — `/init`, `/confirm`, `/status`. `send_confirm` and `send_status` replay items each time to rebuild commitments. Don't "optimize" that away.
3. **`Contract.status.code` enum: `DRAFT | ACTIVE | CANCELLED | COMPLETE`.** `/select` uses DRAFT, `/confirm` uses ACTIVE. **Never** use `"CONFIRMED"` — validator rejects it.
4. **`performance` envelope is strict** (`{id, status, commitmentIds, performanceAttributes}`). `performanceAttributes` is `Attributes`, a JSON-LD container that REQUIRES `@context` (a URI ONIX will HTTP-GET) and `@type` (an IRI). We currently **omit `performanceAttributes` entirely** to dodge schema 404s — see `TODO(beckn-v2.1-context)` in `Bap-1/src/beckn/adapter.py::_performance_dict`.
5. **`/status` payload is `{message: {contract: {id, commitments}}}`** — NOT `{message: {orderId: ...}}`. Order id goes inside `contract.id`.
6. **The Beckn schemas are compiled inside `/app/plugins/schemav2validator.so`** in the ONIX container. To discover a sub-schema, probe with a deliberately bogus field — the error message echoes the schema inline. Then read `docker logs onix-bap | grep 'Schema validation failed'`.
7. **`{participants, settlements}` entries are permissive** (no `additionalProperties: false`); `performance` entries are strict. Probe before assuming.
8. **Every Contract-carrying message** (init, confirm, status) **needs `items` from state** — `send_init`, `send_confirm`, `send_status` all pull `selected + intent.quantity` to rebuild `SelectedItem` lists. New actions follow the same pattern.

## Other invariants enforced by tests

- `BecknIntent.delivery_timeline` is **hours as int** (72 = 3 days), not ISO 8601 (`P3D`). The NL parser converts before building the intent.
- `select_url` MUST contain `caller` in the path — tests in `Bap-1/tests/test_select.py` enforce that `/select` never goes directly to a BPP.
- Beckn v2.0.0 `/select` uses `{ contract: { commitments, consideration } }` — **not** `{ order: ... }`. ONIX rejects `order`.
- `SelectedItem` carries `name`, `price_value`, `price_currency` — always pass these from `DiscoverOffering`.
- ONIX appends the action name to the routing target — config target `http://host:8000/bpp` + action `discover` → `http://host:8000/bpp/discover`. **Never** include the action name in the target URL inside `config/generic-routing-*.yaml`.

## Layer responsibilities (do not cross)

- `Bap-1/src/beckn/models.py` — Pydantic v2 wire models. `BecknIntent` and `BudgetConstraints` live in `shared/models.py` and are re-exported here.
- `Bap-1/src/beckn/adapter.py` — builds messages, owns ALL URL construction (`discover_url`, `select_url`, `caller_action_url(action)`). Nothing else builds Beckn URLs.
- `Bap-1/src/beckn/client.py` — thin async HTTP (aiohttp). No protocol logic.
- `Bap-1/src/beckn/callbacks.py` — `CallbackCollector` queues. Always `register()` before send, `cleanup()` after `collect()`.
- `services/beckn-bap-client/src/handler.py` — the dockerised version; mirrors Bap-1 logic but publishes to Redis on `/on_discover`.

## Probing the live ONIX validator

```bash
# Compose stack must be up
docker compose up -d redis onix-bap onix-bpp sandbox-bpp
curl -X POST http://localhost:8081/bap/caller/init \
  -H "Content-Type: application/json" \
  -d '{"message":{"contract":{"commitments":[],"performance":[{"bogusField":"x"}]}}}'
docker logs onix-bap --tail 50 | grep -A 20 "Schema validation failed"
```

## Production blockers (deliberately stubbed)

Search for grep-able TODO markers before claiming a feature complete:

| Marker | Where | What's deferred |
|---|---|---|
| `TODO(beckn-v2.1-context)` | `Bap-1/src/beckn/adapter.py` | `performanceAttributes` JSON-LD `@context` |
| `TODO(persistence)` | `Bap-1/src/agent/session.py`, `frontend/src/lib/session-store.ts` | swap in-memory session store for Postgres backend |
| `TODO(comparison-engine)` | `Bap-1/src/agent/nodes.py::rank_and_select`, `Bap-1/src/server.py::_build_scoring` | multi-criterion scoring strategy |
| `TODO(approval-workflow)` | `Bap-1/src/server.py::commit`, `frontend/src/components/ConfirmCommitDialog.tsx` | manual approval gate |
| `TODO(realtime-ws)` | `Bap-1/src/server.py::status`, `frontend/src/components/StatusPoller.tsx` | replace polling with WebSockets |

Full catalog: `Bap-1/docs/ARCHITECTURE.md §7`.
