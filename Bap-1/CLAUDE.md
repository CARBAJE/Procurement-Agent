# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Run all tests
pytest tests/ -v

# Run a single test file
pytest tests/test_discover.py -v

# Run a single test by name
pytest tests/test_discover.py::test_discover_returns_offerings -v

# Run unit tests for the NL parser facade (no Ollama needed — LLM is mocked)
pytest tests/test_intent_parser.py -v -k "not integration"

# Run integration tests (requires Ollama running with qwen3:8b)
pytest tests/test_intent_parser.py -v -m integration

# Start the Docker stack (onix-bap, onix-bpp, sandbox-bpp, redis)
cd starter-kit/generic-devkit/install
docker compose -f docker-compose-my-bap.yml up -d

# Run the end-to-end flow (Docker stack must be running)
python run.py                                    # hardcoded intent
python run.py "500 A4 paper Bangalore 3 days"   # NL query (requires Ollama)

# Run the server standalone
python -m src.server       # NOT python src/server.py (import resolution breaks)
```

## Architecture

This is a **Beckn Protocol v2 BAP (Buyer Application Platform)** — the buyer side of an open commerce network. The Python layer never talks directly to BPPs (sellers); all traffic routes through a **beckn-onix adapter** (Go service, port 8081) which handles ED25519 signing and network routing.

### Frontend-facing HTTP API (split two-step flow — Milestone 2)

| Route | Purpose |
|---|---|
| `POST /parse` | NL → `BecknIntent` via IntentParser (Ollama) |
| `POST /compare` | Run `arun_compare()` (discover + rank only), store state under `transaction_id`, return offerings + scoring + reasoning_steps |
| `POST /commit` | Load session by `transaction_id`, override `selected` with user's `chosen_item_id`, run `arun_commit()` (select + init + confirm), return `order_id` + `order_state` + payment terms |
| `GET /status/{txn_id}/{order_id}` | Poll order lifecycle; `bpp_id`/`bpp_uri` are recovered from the session if omitted |

All four fall back to a mock response (`status: "mock"`) when the ONIX Docker stack is offline, so the frontend works standalone. Session state is held in `src/agent/session.py::TransactionSessionStore` (in-memory, TTL 1800s) — swap to `PostgresBackend` via the `StateBackend` Protocol when DB persistence lands.

### Two-phase flow

**Discovery (async):** BAP sends `POST /bap/caller/discover` to ONIX adapter → adapter routes to the local catalog endpoint (`/bpp/discover` on `src/server.py`) → server ACKs immediately and fires an async `on_discover` callback back to `/bap/receiver/on_discover` → `CallbackCollector` wakes up `discover_async()`.

**Transactional actions (async):** `/select`, `/init`, `/confirm`, `/status` go to `POST /bap/caller/{action}` on the ONIX adapter. The adapter routes to `onix-bpp` → `sandbox-bpp`, which generates the `on_*` callback. The callback travels back through `onix-bpp` → `onix-bap` → `host:8000/bap/receiver/{action}` → `CallbackCollector`.

### Layer responsibilities

- **`src/beckn/models.py`** — Pydantic v2 protocol models. `BecknIntent` and `BudgetConstraints` are defined in `shared/models.py` (repo root) and re-exported here — all imports from `src.beckn.models` still work. Never put protocol-formatting logic outside the beckn/ layer.

- **`src/beckn/adapter.py`** — Builds protocol messages (UUID transaction IDs, RFC 3339 timestamps, context headers). Owns all URL construction — `discover_url`, `select_url`, `caller_action_url(action)`. Nothing else should construct Beckn URLs.

- **`src/beckn/client.py`** — Thin async HTTP layer (aiohttp). `discover_async()` sends to `onix-bap` and waits for the `on_discover` callback via `CallbackCollector`. `select()` returns the ACK dict. No protocol logic here.

- **`src/beckn/callbacks.py`** — `CallbackCollector` uses one `asyncio.Queue` per `(transaction_id, action)` tuple. This is how the async callbacks are correlated back to the code that sent the request. Always `register()` before sending the action, `cleanup()` after `collect()`.

- **`src/agent/session.py`** — `TransactionSessionStore` with `InMemoryBackend` (TTL 1800s, background sweeper). Holds `ProcurementState` between `/compare` and `/commit`. Implements a `StateBackend` Protocol so a future `PostgresBackend` is a one-line swap in `server.py::create_app`.

- **`src/agent/graph.py`** — three graph factories sharing the same nodes: `build_graph` (full flow, used by `run.py`), `build_compare_graph` (stops after `rank_and_select`), `build_commit_graph` (starts at `send_select`). `ProcurementAgent` wraps all three.

- **`src/server.py`** — aiohttp server on port 8000. Frontend routes: `/parse`, `/compare`, `/commit`, `/status/{txn}/{order}`. Protocol routes: `POST /bap/receiver/{action}` for callbacks, `POST /bpp/discover` as local catalog (6 offerings with diverse price / rating / ETA / stock). Helper `_build_scoring()` produces a multi-criterion-ready payload (currently a single `price` criterion) — swap for a `ScoringStrategy` when the Comparison Engine lands. Module-level `collector` + `session_store` are shared with `run.py`.

- **`mock_onix.py`** — Legacy mock of the Go beckn-onix adapter. Used only by unit tests (via `aioresponses`). Not used for local dev — the real `onix-bap` Docker container replaces it.

### Test setup

All tests mock HTTP with `aioresponses`. The `conftest.py` fixtures (`adapter`, `collector`) point to `http://mock-onix.test` — a non-existent host that only works inside `aioresponses` context managers. `pytest-asyncio` runs all `async def test_*` automatically (`asyncio_mode = auto` in `pytest.ini`).

### NL Intent Parser (`src/nlp/`)

Implemented as a **Facade** over the standalone `IntentParser/` module (one level above `Bap-1/`).

- **`src/nlp/intent_parser_facade.py`** — single public function `parse_nl_to_intent(query) -> BecknIntent | None`. Returns `None` for non-procurement queries. No type conversion needed — both modules share `shared/models.BecknIntent`.
- **IntentParser** uses `instructor` + Ollama (`qwen3:8b` complex, `qwen3:1.7b` simple). Routing heuristic: query > 120 chars or ≥ 2 numbers or procurement keywords → complex model.
- **Path resolution**: `pytest.ini` has `pythonpath = ..` so tests find `IntentParser/`; `run.py` does `sys.path.insert` for runtime.
- **Unit tests** mock `parse_request` — no Ollama needed. Integration tests (`-m integration`) require Ollama running with `qwen3:8b`.

## Key constraints

- `BecknIntent.delivery_timeline` is **hours as int** (72 = 3 days), not ISO 8601 (`P3D`). The NL parser converts "3 days" → 72 before building the intent.
- The `select_url` must always contain `caller` in the path — tests enforce that `/select` never goes directly to a BPP.
- `BecknConfig` is constructed with field values directly in tests (not from `.env`) to keep tests hermetic.
- Beckn v2.0.0 `/select` uses `{ contract: { commitments, consideration } }` — **not** `{ order: ... }`. The ONIX adapter validates against the official spec and rejects `order`.
- `SelectedItem` carries optional `name`, `price_value`, `price_currency` fields used to build the `contract` wire payload. Always pass these from the `DiscoverOffering` when calling `client.select()`.
- The ONIX adapter appends the action name to the routing target URL — e.g. target `http://host:8000/bpp` + action `discover` → `http://host:8000/bpp/discover`. Never include the action name in the target URL inside routing config files.

## Beckn v2.1 wire shape — hard-won gotchas

These were discovered the hard way by validating the full `/discover → /select → /init → /confirm → /status` flow against the live ONIX Go validator. The unit tests mock HTTP and would not have caught these. If you're about to change anything in `src/beckn/adapter.py` or `src/beckn/client.py` parsers, read these first:

1. **`Contract` has `additionalProperties: false`.** Only these keys pass: `id, commitments, consideration, participants, performance, settlements, status, descriptor, contractAttributes`. **Billing and fulfillment DO NOT go inline** — buyer info goes in `participants[role=buyer]` (permissive), fulfillment info in `performance[]` (strict envelope), payment in `settlements[]` (permissive).
2. **`Contract.commitments` is required everywhere a Contract appears** — `/init`, `/confirm`, and even `/status` (which inherits via `allOf: [Contract, {required: [id]}]`). `send_confirm` and `send_status` replay items each time to rebuild commitments. Don't "optimize" that away.
3. **`Contract.status.code` enum: `DRAFT | ACTIVE | CANCELLED | COMPLETE`.** `/select` uses DRAFT, `/confirm` uses ACTIVE. Do NOT use "CONFIRMED" — the validator rejects it.
4. **Performance envelope is strict** (`{id, status, commitmentIds, performanceAttributes}`), but `performanceAttributes` is typed as `Attributes` — a JSON-LD container that REQUIRES `@context` (a URI) and `@type` (an IRI). The ONIX validator will then HTTP-GET that URI as a schema; if 404, validation fails. **Today we omit `performanceAttributes` entirely** to dodge this — see `TODO(beckn-v2.1-context)` and `Bap-1/docs/ARCHITECTURE.md §7.1 #1` for the full story and unblock options.
5. **`/status` wire payload is `{message: {contract: {id, commitments}}}`** — NOT `{message: {orderId: ...}}`. The order id goes inside `contract.id`, and commitments must be replayed (see #2).
6. **The Beckn schemas are compiled inside `/app/plugins/schemav2validator.so` in the ONIX container** and are not in any JSON file. To discover a sub-schema, probe with a deliberately bogus field — the error message echoes the full schema inline. Example: `curl -X POST http://localhost:8081/bap/caller/init -d '{"message":{"contract":{"commitments":[...],"performance":[{"bogusField":"x"}]}}}'` then read `docker logs onix-bap | grep 'Schema validation failed'`.
7. **`{participants, settlements}` entry objects are permissive** (no `additionalProperties: false`) but `performance` entries are strict. Probe first before assuming.
8. **Every message carrying a Contract** (init, confirm, status) **requires `items` passed down from state** — `send_init`, `send_confirm`, `send_status` nodes all pull `selected + intent.quantity` to rebuild `SelectedItem` lists. If you add a new action, follow the same pattern.

## Production blockers (what's stubbed / deliberately deferred)

Full catalog in `Bap-1/docs/ARCHITECTURE.md §7` with 14 items grouped by category (protocol, data, security, ops). Each has a grep-able TODO marker in the code pointing back to its row in §7. Quick index:

| TODO marker | Grep | Section |
|---|---|---|
| `TODO(beckn-v2.1-context)` | `adapter.py::_performance_dict` | §7.1 #1 |
| `TODO(persistence)` | `session.py`, `server.py`, `frontend/src/lib/session-store.ts` | §7.2 #6 |
| `TODO(comparison-engine)` | `nodes.py::rank_and_select`, `server.py::_build_scoring` | §7.2 #7 |
| `TODO(approval-workflow)` | `server.py::commit`, `ConfirmCommitDialog.tsx` | §7.3 #10 |
| `TODO(realtime-ws)` | `server.py::status`, `StatusPoller.tsx` | §7.4 #11 |

Before implementing any of these, read §7 — it documents the unblock options, the owner (some are assigned to other teammates, not Eduardo), and the extension points that are already in place so the swap is a one-line change.
