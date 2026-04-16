# BAP-1 — Beckn Buyer Application Platform

> Week 1 milestone: Core API Flows (`/discover`, `/select`)  
> **Beckn Protocol v2**

---

## What is this?

This is the **BAP (Buyer Application Platform)** — the buyer-side client of the [Beckn Protocol](https://becknprotocol.io/). It is the layer that sits between an enterprise procurement agent and the open commerce network.

When the AI agent wants to buy something, it uses this library to:

1. **Discover** sellers — send intent to the ONIX adapter, wait for `on_discover` callback with catalog
2. **Select** the best offer and signal intent to the chosen seller (`/select`)
3. **Complete** the order lifecycle: init → confirm → status *(Phase 2)*

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
bap-1/
├── src/
│   ├── config.py               # BecknConfig (env-driven settings)
│   ├── server.py               # aiohttp server on port 8000:
│   │                           #   POST /bap/receiver/{action}  — async callbacks
│   │                           #   POST /bpp/discover           — local catalog endpoint
│   └── beckn/
│       ├── models.py           # Pydantic v2 protocol models (BecknIntent, Contract, etc.)
│       ├── adapter.py          # Protocol adapter (context building, wire payloads, URLs)
│       ├── client.py           # Async HTTP client (aiohttp)
│       └── callbacks.py        # CallbackCollector for on_discover/on_select/etc.
├── tests/
│   ├── conftest.py             # Shared pytest fixtures
│   ├── test_discover.py        # /discover flow tests
│   └── test_select.py          # /select flow tests
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

    # Select — sends contract, waits for on_select callback separately
    ack = await client.select(order, txn_id, bpp_id, bpp_uri)
```

| Method | Sends to | Returns |
|---|---|---|
| `discover_async(intent, collector)` | `onix-bap /bap/caller/discover` | `DiscoverResponse` (via callback) |
| `select(order, txn_id, bpp_id, bpp_uri)` | `onix-bap /bap/caller/select` | ACK dict |

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

`aiohttp` server on port 8000 with two responsibilities:

**Callback receiver** — `POST /bap/receiver/{action}`  
Receives `on_discover`, `on_select`, `on_init`, `on_confirm`, `on_status` from onix-bap and routes them to `CallbackCollector`.

**Local catalog endpoint** — `POST /bpp/discover`  
Acts as the local Catalog Discovery Service. onix-bap routes discover requests here (via `BAPCaller.yaml`). Returns the hardcoded A4 paper catalog as an async `on_discover` callback.

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
python run.py
```

Expected output:
```
============================================================
  Real BAP -- Beckn Protocol v2
============================================================
  BAP ID     : bap.example.com
  ONIX URL   : http://localhost:8081
  Item       : A4 paper 80gsm
  Quantity   : 500
  Budget max : Rs. 200.0

  Discovering ...

  3 offering(s) found:

    [bpp.example.com     ]  OfficeWorld Supplies            Rs. 195.00  *4.8
    [bpp.example.com     ]  PaperDirect India               Rs. 189.00  *4.5
    [bpp.example.com     ]  Stationery Hub                  Rs. 201.00  *4.9

  Selected : PaperDirect India
  Price    : Rs. 189.00
  BPP      : bpp.example.com

  Selecting PaperDirect India ...
  on_select: RECEIVED

  Done. Next: /init -> /confirm -> /status
============================================================
```

### Stopping the stack

```bash
docker compose -f docker-compose-my-bap.yml down
```

---

## Running Tests

Tests use `aioresponses` to mock all HTTP calls — no Docker needed.

```bash
pytest tests/ -v
pytest tests/test_discover.py -v
pytest tests/test_select.py -v
```

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

| Phase | Weeks | Milestone |
|---|---|---|
| **1 — Foundation** | 1–4 | Core API flows (v2) ✅, NL Intent Parser, Agent Framework, Data Models |
| **2 — Intelligence** | 5–8 | `/init`, `/confirm`, `/status`, Catalog Normalizer, Comparison Engine |
| **3 — Advanced** | 9–12 | Negotiation Engine, Agent Memory (Vector DB), Audit Trail, ERP Integration |
| **4 — Production** | 13–16 | Performance, Security Hardening, CI/CD, Evaluation Suite |

---

## Tech Stack

| Layer | Technology |
|---|---|
| Protocol Models | Pydantic v2 |
| Async HTTP | aiohttp |
| Configuration | pydantic-settings |
| Testing | pytest + pytest-asyncio + aioresponses |
| Beckn Adapters | beckn-onix (`fidedocker/onix-adapter`) via Docker |
| Mock BPP | `fidedocker/sandbox-2.0` via Docker |
| Agent Framework | LangChain / LangGraph *(Phase 1, Week 3)* |
| LLM | Claude Sonnet *(Phase 1, Week 3)* |
