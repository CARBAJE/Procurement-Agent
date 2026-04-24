# BAP-1 — Beckn Buyer Application Platform

> Phase 2 milestones delivered (Eduardo): Full Transaction Flow ✅ · Comparison UI ✅
> **Beckn Protocol v2.1** (validated live against the sandbox ONIX stack)

---

## What is this?

This is the **BAP (Buyer Application Platform)** — the buyer-side client of the [Beckn Protocol](https://becknprotocol.io/). It is the layer that sits between an enterprise procurement agent and the open commerce network.

When the AI agent wants to buy something, it uses this library to:

1. **Discover** sellers — send intent to the ONIX adapter, wait for `on_discover` callback with catalog.
2. **Compare** offerings side-by-side with multi-criterion-ready scoring (today: price only, Comparison Engine plugs in later).
3. **Commit** the chosen order through `/select` → `/init` → `/confirm`, splitting state between a `/compare` (discover + rank) and `/commit` (the transactional tail) so the UI can show alternatives before the order is final.
4. **Track** order state via `/status` polling (30 s SLA; swap-ready for WebSocket push).

---

## How the Beckn v2 Protocol Works

All actions in Beckn v2 are **asynchronous**: the BAP sends a request, gets an immediate ACK, and waits for the BPP to POST back a callback to `/bap/receiver/{action}`.

```
BAP              onix-bap (adapter)     onix-bpp (adapter)     sandbox-bpp
 │                    │                       │                      │
 │──/bap/caller/discover──>│                  │                      │
 │                    │──routes to /bpp/discover (local catalog)     │
 │<── ACK ────────────│                  │                      │
 │                    │                  │                      │
 │<── /bap/receiver/on_discover ─────────│  (async callback)   │
 │                    │                  │                      │
 │──/bap/caller/select────>│             │                      │
 │                    │──────────────────>│                     │
 │<── ACK ────────────│                  │──────────────────────>│
 │                    │                  │                      ├─ generates on_select
 │                    │<─────────────────│<─────────────────────│
 │<── /bap/receiver/on_select ───────────│                      │
```

The Python BAP never talks directly to BPPs. All traffic goes through the **beckn-onix adapter** (Go service, port 8081) which handles ED25519 signing, schema validation against the official Beckn v2.0.0 spec, and network routing.

### v1 vs v2 at a glance

| | v1 | v2 |
|---|---|---|
| Discovery | Async broadcast `/search` + `/on_search` callbacks | Async `/discover` + `on_discover` callback |
| Select message | `{ order: { provider, items } }` | `{ contract: { commitments, consideration } }` |
| Catalog | BPPs respond on-demand | BPPs pre-register via `catalog/publish` |
| Signing | Application-level | Handled by ONIX adapter (ED25519) |

---

## Project Structure

```
../shared/                      # shared models (one level above Bap-1/)
└── models.py                   # BecknIntent, BudgetConstraints — single source of truth

bap-1/
├── src/
│   ├── config.py                  # BecknConfig (env-driven settings)
│   ├── server.py                  # aiohttp :8000 — frontend API + callback receiver:
│   │                              #   POST /parse                       NL → BecknIntent
│   │                              #   POST /compare                     discover + rank only
│   │                              #   POST /commit                      select + init + confirm
│   │                              #   GET  /status/{txn}/{order}        poll order state
│   │                              #   POST /bap/receiver/{action}       async callbacks from ONIX
│   │                              #   POST /bpp/discover                local catalog endpoint
│   ├── nlp/
│   │   └── intent_parser_facade.py
│   ├── agent/
│   │   ├── state.py               # ProcurementState TypedDict (17 fields, reasoning_steps)
│   │   ├── nodes.py               # 8 async nodes: parse_intent, discover, rank_and_select,
│   │   │                          # send_select, send_init, send_confirm, send_status, present_results
│   │   ├── graph.py               # build_graph / build_compare_graph / build_commit_graph
│   │   │                          # + ProcurementAgent (arun, arun_compare, arun_commit, get_status)
│   │   └── session.py             # TransactionSessionStore + StateBackend Protocol (swap to Postgres)
│   └── beckn/
│       ├── models.py              # Pydantic v2 protocol models; BecknIntent from shared/
│       ├── adapter.py             # v2.1 payload builders + URL helpers
│       ├── client.py              # Async aiohttp client (discover/select/init/confirm/status)
│       ├── callbacks.py           # CallbackCollector — asyncio.Queue per (txn_id, action)
│       └── providers/             # Provider Pattern for billing/fulfillment/payment (swap point)
├── tests/
│   ├── conftest.py                # Shared pytest fixtures
│   ├── test_discover.py, test_select.py,
│   │   test_init.py, test_confirm.py, test_status.py   # per-action flow tests (v2.1 wire shape)
│   ├── test_agent.py              # Full graph via AsyncMock client
│   ├── test_compare_commit.py     # Compare/commit partial graphs
│   ├── test_session_store.py      # TransactionSessionStore unit tests
│   ├── test_scoring_builder.py    # _build_scoring helper
│   ├── test_server_endpoints.py   # HTTP routing + JSON shape via aiohttp.test_utils
│   └── test_intent_parser.py      # NL parser facade (unit + opt-in integration)
├── starter-kit/
│   └── generic-devkit/
│       ├── config/
│       │   ├── generic-bap.yaml                  # onix-bap adapter config
│       │   ├── generic-bpp.yaml                  # onix-bpp adapter config
│       │   ├── generic-routing-BAPCaller.yaml     # routes discover → local /bpp/discover
│       │   ├── generic-routing-BAPReceiver.yaml   # routes on_* → host:8000/bap/receiver
│       │   └── generic-routing-BPPCaller.yaml     # routes on_select etc → onix-bap (local)
│       └── install/
│           └── docker-compose-my-bap.yml          # Docker stack without sandbox-bap
├── mock_onix.py                # Legacy mock adapter (port 8081) — for tests only
├── publish_catalog.py          # Publishes A4 paper catalog to onix-bpp
├── run.py                      # End-to-end runner: discover → select
├── requirements.txt
├── pytest.ini
└── .env
```

---

## Architecture

### Local development stack

```
┌─────────────────────────────────────────────────────────────────┐
│  HOST MACHINE                                                   │
│                                                                 │
│  run.py + src/server.py  (port 8000)                           │
│    ├── POST /bpp/discover     ← onix-bap forwards discover here │
│    └── POST /bap/receiver/*   ← onix-bap forwards callbacks here│
└──────────────────────────────┬──────────────────────────────────┘
                               │ host.docker.internal
┌──────────────────────────────▼──────────────────────────────────┐
│  DOCKER (beckn_network)                                         │
│                                                                 │
│  onix-bap :8081   ←──────────────────────────────────────────  │
│    bap/caller/ → signs + validates + routes outbound requests   │
│    bap/receiver/ → validates + forwards callbacks to host:8000  │
│                                                                 │
│  onix-bpp :8082                                                 │
│    bpp/receiver/ → forwards inbound requests to sandbox-bpp     │
│    bpp/caller/  → signs + routes on_* callbacks to onix-bap    │
│                                                                 │
│  sandbox-bpp :3002   ← receives select/init/etc, generates on_*│
│  redis :6379         ← adapter session cache                    │
└─────────────────────────────────────────────────────────────────┘
```

### Routing summary

| Config file | Governs | Key rule |
|---|---|---|
| `BAPCaller.yaml` | Outbound BAP requests | `discover` → `host:8000/bpp` (local catalog) |
| `BAPReceiver.yaml` | Inbound callbacks to BAP | All `on_*` → `host:8000/bap/receiver` |
| `BPPCaller.yaml` | Outbound BPP callbacks | `on_select` etc → `onix-bap:8081/bap/receiver` (bypasses registry) |
| `BPPReceiver.yaml` | Inbound requests to BPP | All actions → `sandbox-bpp:3002/api/webhook` |

---

## Components

### `BecknConfig`

Settings powered by `pydantic-settings`. Reads from `.env`.

| Variable | Default | Description |
|---|---|---|
| `BAP_ID` | `bap.example.com` | BAP subscriber ID (must match ONIX adapter config) |
| `BAP_URI` | `http://host.docker.internal:8000/bap/receiver` | Callback URL reachable from Docker |
| `ONIX_URL` | `http://localhost:8081` | onix-bap adapter URL |
| `CORE_VERSION` | `2.0.0` | Beckn protocol version |
| `CALLBACK_TIMEOUT` | `15.0` | Seconds to wait for async callbacks |

---

### `BecknIntent` (Anti-Corruption Layer)

Canonical representation of what the procurement agent wants. Sits between AI/NL output and the Beckn wire format.

Defined in `shared/models.py` (one level above `Bap-1/`) and re-exported from `src/beckn/models.py` — so all existing imports remain unchanged.

```python
BecknIntent(
    item="A4 paper 80gsm",
    descriptions=["A4", "80gsm"],
    quantity=500,
    location_coordinates="12.9716,77.5946",  # "lat,lon"
    delivery_timeline=72,                     # hours (not ISO 8601)
    budget_constraints=BudgetConstraints(max=200.0),
)
```

---

### `BecknClient`

Async HTTP client. Use as an async context manager.

```python
async with BecknClient(adapter) as client:
    # Discover — async, waits for on_discover callback
    discover_resp = await client.discover_async(intent, collector, timeout=15.0)

    # Select — sends contract, awaits on_select (fire-and-forget in practice)
    ack = await client.select(order, txn_id, bpp_id, bpp_uri)

    # Init — sends buyer+fulfillment, awaits on_init with payment terms
    init_resp = await client.init(
        contract_id=..., items=..., billing=..., fulfillment=...,
        transaction_id=..., bpp_id=..., bpp_uri=..., collector=collector,
    )

    # Confirm — commits with payment, awaits on_confirm with order_id
    confirm_resp = await client.confirm(
        contract_id=..., items=..., payment=..., transaction_id=...,
        bpp_id=..., bpp_uri=..., collector=collector,
    )

    # Status — polls lifecycle state; items replayed for v2.1 commitments requirement
    status_resp = await client.status(
        order_id=..., items=..., transaction_id=...,
        bpp_id=..., bpp_uri=..., collector=collector,
    )
```

| Method | Sends to | Returns |
|---|---|---|
| `discover_async(intent, collector)` | `/bap/caller/discover` | `DiscoverResponse` via callback |
| `select(order, txn_id, bpp_id, bpp_uri)` | `/bap/caller/select` | ACK dict |
| `init(...)` | `/bap/caller/init` | `InitResponse` with payment terms |
| `confirm(...)` | `/bap/caller/confirm` | `ConfirmResponse` with order_id |
| `status(...)` | `/bap/caller/status` | `StatusResponse` with current state |

---

### `CallbackCollector`

Async inbox for callbacks. Uses one `asyncio.Queue` per `(transaction_id, action)` pair.

```python
collector.register(txn_id, "on_select")       # open queue before sending request
ack = await collector.handle_callback("on_select", payload)  # called by server.py
callbacks = await collector.collect(txn_id, "on_select", timeout=10.0)
collector.cleanup(txn_id, "on_select")
```

---

### `src/server.py`

`aiohttp` server on port 8000 with two groups of responsibilities:

**Frontend-facing HTTP API** (consumed by the Next.js proxies in `frontend/src/app/api/procurement/`):

| Route | Purpose |
|---|---|
| `POST /parse` | NL → BecknIntent (Ollama via IntentParser). Errors propagate — no silent mock. |
| `POST /compare` | Runs `ProcurementAgent.arun_compare()` (discover + rank only); stores state in `TransactionSessionStore`; returns offerings + scoring + reasoning trace. |
| `POST /commit` | Loads session, overrides `selected` with user's pick, runs `arun_commit()` (select + init + confirm); returns order_id + state. |
| `GET  /status/{txn_id}/{order_id}` | Polls order state; rebuilds `items` from session to satisfy v2.1's Contract.commitments requirement. |

**Protocol layer** (speaks to the ONIX Go adapter):

| Route | Purpose |
|---|---|
| `POST /bap/receiver/{action}` | Receives async callbacks `on_discover`, `on_select`, `on_init`, `on_confirm`, `on_status` and routes them to `CallbackCollector`. |
| `POST /bpp/discover` | Local Catalog Discovery Service stub. onix-bap routes discover requests here (via `BAPCaller.yaml`). Returns the 6-item local catalog as an async `on_discover` callback. |

All four frontend-facing routes fall back to mock data (`status: "mock"`) when the ONIX stack is unavailable — so the UI works standalone for demos without Docker.

---

## Quickstart

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure environment

```bash
# .env
BAP_ID=bap.example.com
BAP_URI=http://host.docker.internal:8000/bap/receiver
ONIX_URL=http://localhost:8081
DOMAIN=beckn.one/testnet
CORE_VERSION=2.0.0
CALLBACK_TIMEOUT=15
```

### 3. Run the tests

```bash
pytest tests/ -v
```

### 4. Start the Docker stack

```bash
cd starter-kit/generic-devkit/install
docker compose -f docker-compose-my-bap.yml up -d
docker ps   # should show: redis, onix-bap, onix-bpp, sandbox-bpp
```

### 5. Run the end-to-end flow

```bash
# With hardcoded intent (no Ollama needed)
python run.py

# With natural language query (requires Ollama running with qwen3:8b)
python run.py "500 reams A4 paper 80gsm Bangalore, 3 days, max 200 INR"
```

Expected output: the NL query is parsed, discover returns 6 offerings, the cheapest (Budget Paper Co at ₹165) is selected, `/select` → `/init` → `/confirm` round-trip completes, and a final `order_id` is assigned by the BPP. The trace ends with "Order CONFIRMED — <provider> | <item> × <qty> | ₹<price> INR | order=<id> state=CREATED".

### Stopping the stack

```bash
docker compose -f docker-compose-my-bap.yml down
```

---

## Running Tests

129 tests across 12 files. All HTTP is mocked with `aioresponses` — no Docker needed for tests. Ollama integration tests are opt-in.

```bash
pytest tests/ -v                                                # full suite
pytest tests/ -v --deselect tests/test_intent_parser.py::test_integration_parse_nl_to_intent   # skip Ollama
pytest tests/test_init.py -v                                    # one flow
pytest tests/test_compare_commit.py::test_compare_recommends_cheapest -v  # one test
```

Breakdown: agent 21 · callbacks 10 · discover 17 · init 8 · confirm 8 · status 11 · select 9 · intent_parser 10 · session_store 10 · compare_commit 11 · scoring_builder 7 · server_endpoints 10.

---

## What is simulated vs real

| Component | Real or simulated? |
|---|---|
| `onix-bap`, `onix-bpp` | **Real** — official Beckn ONIX Go adapters (ED25519 signing, schema validation) |
| Beckn v2.0.0 message format | **Real** — validated against the official OpenAPI spec |
| Catalog (`_LOCAL_CATALOG` in `server.py`) | **Simulated** — hardcoded A4 paper suppliers |
| `sandbox-bpp` | **Simulated** — generic container that generates `on_select` responses |
| BPP network / registry | **Simulated** — `sandbox-bpp` acts as all BPPs |

---

## Roadmap

| Phase | Weeks | Milestone | Status |
|---|---|---|---|
| **1 — Foundation** | 1–4 | Core API flows (v2), NL Intent Parser, Agent Framework, Data Models | ✅ Complete |
| **2 — Intelligence** | 5–8 | Eduardo: Full Transaction Flow (`/init`, `/confirm`, `/status`) + Comparison UI. Others: Catalog Normalizer, Comparison Engine, Approval Workflow, Real-time Tracking, DB persistence | ✅ Eduardo · ⏳ Others |
| **3 — Advanced** | 9–12 | Negotiation Engine, Agent Memory (Vector DB), Audit Trail, ERP Integration | ⏳ |
| **4 — Production** | 13–16 | Performance, Security Hardening, CI/CD, Evaluation Suite, JSON-LD context resolution | ⏳ |

**What's stubbed and why** — see `docs/ARCHITECTURE.md §7` for the full inventory of 14 production blockers, their TODO markers in the code, and the recommended unblock options.

---

## Tech Stack

| Layer | Technology |
|---|---|
| Protocol Models | Pydantic v2 |
| Async HTTP | aiohttp |
| Agent Framework | LangGraph (three partial graphs reusing the same nodes: full / compare / commit) |
| NL Intent Parser | Ollama (qwen3:8b / qwen3:1.7b) via `instructor` + OpenAI SDK — called from the `IntentParser/` module one level up |
| Session store | In-memory dict with 30 min TTL + async sweeper; `StateBackend` Protocol ready for Postgres |
| Configuration | pydantic-settings (.env) |
| Testing | pytest + pytest-asyncio + aioresponses |
| Beckn Adapters | beckn-onix (`fidedocker/onix-adapter`) via Docker |
| Sandbox BPP | `fidedocker/sandbox-2.0` via Docker (template echo — not a real seller) |

---

## Related docs

- `docs/ARCHITECTURE.md` — full architecture, two-step flow diagrams, production blockers (§7).
- `CLAUDE.md` — Claude Code guidance + Beckn v2.1 wire-shape gotchas (the hard-won lessons from live validation).
- `../frontend/README.md` — UI layer overview.
- `../KnowledgeBase/project_scaffold/milestones/phase*.md` — original 16-week roadmap per phase.
