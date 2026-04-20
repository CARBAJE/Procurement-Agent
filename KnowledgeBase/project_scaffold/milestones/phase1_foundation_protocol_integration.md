---
tags: [milestone, phase-1, foundation, protocol-integration, beckn, langchain, weeks-1-4]
cssclasses: [procurement-doc, milestone-doc]
status: "#processed"
related: ["[[beckn_bap_client]]", "[[nl_intent_parser]]", "[[agent_framework_langchain_langgraph]]", "[[frontend_react_nextjs]]", "[[databases_postgresql_redis]]", "[[llm_providers]]", "[[phase2_core_intelligence_transaction_flow]]"]
---

# Phase 1: Foundation & Protocol Integration (Weeks 1–4)

> [!milestone] Phase Objective
> Establish working connectivity with the Beckn/ONDC network and build the core agent framework. By end of Week 4, the team must have a demonstrable end-to-end path: natural language request → Beckn search → seller responses parsed → agent recommendation — even if comparison and negotiation are not yet complete.

## Milestones & Deliverables

| Milestone            | Deliverable                                                                                  | Skills Required                                                              | Acceptance Criteria                                                                                                                                                          |
| -------------------- | -------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Beckn Sandbox Setup  | beckn-onix adapter deployed + Python agent layer connected to Beckn sandbox                  | Protocol engineering, Go, beckn-onix, Python                                 | ONIX adapter sends `GET /discover` to Discovery Service and receives synchronous catalog response; BPP `POST /publish` to Catalog Service verified; ED25519 signing verified |
| Core API Flows       | `discover`, `select`, `init` implemented (v2 flow)                                           | Beckn protocol spec, API design                                              | End-to-end discover flow against Beckn v2 sandbox with 3+ offerings returned                                                                                                 |
| **NL Intent Parser** | [[nl_intent_parser\|LLM-based parser]] converting text to structured intent                  | LLM integration ([[llm_providers\|GPT-4o]]), prompt engineering, JSON schema | Correctly parses 15+ diverse requests into valid Beckn-compatible intent                                                                                                     |
| Agent Framework      | [[agent_framework_langchain_langgraph\|LangChain/LangGraph]] agent with ReAct loop           | Python, LangChain, LLM APIs                                                  | Agent autonomously plans and executes a 3-step procurement workflow                                                                                                          |
| Frontend Scaffold    | [[frontend_react_nextjs\|React/Next.js]] app with auth, basic request form                   | React, TypeScript, Next.js                                                   | Running locally with SSO stub; request submission functional                                                                                                                 |
| Data Models          | [[databases_postgresql_redis\|PostgreSQL]] schema for requests, offers, orders, audit events | Database design, SQL, migrations                                             | Schema supports full procurement lifecycle with audit trail                                                                                                                  |

> [!architecture] Technical Focus Areas
> - `beckn-onix` Go adapter for protocol compliance (ED25519 signing, schema validation); `discover` queries to Discovery Service; `publish` registration flow for BPP catalog updates.
> - Python agent HTTP client calling ONIX adapter at `localhost:8081`.
> - Schema-constrained LLM decoding ([[nl_intent_parser]]) for reliable JSON output.
> - [[agent_framework_langchain_langgraph|LangChain/LangGraph]] ReAct agent loop (Reason → Act → Observe).
> - [[databases_postgresql_redis|PostgreSQL]] data model covering the full procurement lifecycle.
> - [[identity_access_keycloak|Keycloak]] SSO stub for the frontend.

> [!insight] Why Phase 1 is the Riskiest Phase
> The Beckn protocol integration is the highest technical uncertainty in the entire project. Synchronous Discovery Service integration — ensuring the Catalog Service has up-to-date BPP offerings and that `discover` queries return accurate, filtered results is the highest technical uncertainty. Phase 1 exists to derisk this before building intelligence on top of it. Every subsequent phase assumes this foundation works correctly.

> [!milestone] Deliverables Summary — End of Week 4
> - [[beckn_bap_client|BAP client]] operational: `discover` queries returning catalog data from Discovery Service; BPP `publish` flow verified.
> - [[nl_intent_parser|NL parser]] validated on 15+ requests.
> - [[agent_framework_langchain_langgraph|Agent]] executes a 3-step workflow autonomously.
> - [[frontend_react_nextjs|Frontend]] running locally.
> - [[databases_postgresql_redis|Data model]] deployed with full lifecycle schema.

---

## Implementation Record

> [!check] Current Status
> Four of six deliverables are fully implemented. The end-to-end flow — NL query → IntentParser (Ollama) → Beckn discover → rank → /select — is operational. Only **Frontend Scaffold** and **Data Models** remain to close Phase 1.

### Deliverable Status

| Milestone | Status | Branch |
|---|---|---|
| Beckn Sandbox Setup | ✅ Implemented | `BAP-1` |
| Core API Flows (`discover` + `select`) | ✅ Implemented | `BAP-1` |
| NL Intent Parser | ✅ Implemented | `BAP-1` |
| Agent Framework | ✅ Implemented | `feature/agent-framework` |
| Frontend Scaffold | ⏳ Pending | — |
| Data Models | ⏳ Pending | — |

> [!warning] Remaining to close Phase 1
> - **Frontend Scaffold** — [[frontend_react_nextjs|React/Next.js]] app with auth and basic request form.
> - **Data Models** — [[databases_postgresql_redis|PostgreSQL]] schema for requests, offers, orders, and audit events.

---

### Implemented Architecture

```
User NL Query  (CLI argument)
      │
      ▼
┌─────────────────────────────────────────────────┐
│            Procurement ReAct Agent              │  feature/agent-framework
│            LangGraph StateGraph                 │  Bap-1/src/agent/
│                                                 │
│  parse_intent → discover → rank_and_select      │
│              → send_select → present_results    │
└──────────┬──────────────────────┬───────────────┘
           │                      │
           ▼                      ▼
┌──────────────────────┐   ┌──────────────────────────┐
│    IntentParser      │   │    Beckn BAP Layer        │
│    (Ollama NLP)      │   │    Bap-1/src/beckn/       │
│    qwen3:1.7b        │   │    + Bap-1/src/server.py  │
│    shared/models.py  │   │    + beckn-onix :8081     │
└──────────────────────┘   └──────────────────────────┘
```

---

### Layer 1 — NL Intent Parser

**Docs:** [[nl_intent_parser]] · **Model:** Ollama `qwen3:1.7b` (local, no cloud API)

Two-stage pipeline running entirely on-device:

| Stage | What it does | Output |
|---|---|---|
| Stage 1 — Classification | Classifies the query into a PascalCase intent. Only `SearchProduct`, `RequestQuote`, `PurchaseOrder` proceed. | `ParsedIntent { intent, confidence, reasoning }` |
| Stage 2 — Extraction | Extracts all structured fields via `instructor` + `Mode.JSON`, `max_retries=3`. | `BecknIntent` via `shared/models.py` ACL |

**Complexity routing:** `_is_complex(query)` selects `COMPLEX_MODEL` or `SIMPLE_MODEL` based on query length, numeric token count, and keywords (`budget`, `days`, `INR`, `delivery`, etc.). Both default to `qwen3:1.7b` in Phase 1 — the routing is designed to plug in a heavier model in Phase 2.

**BAP facade** (`Bap-1/src/nlp/intent_parser_facade.py`):
```python
def parse_nl_to_intent(query: str) -> BecknIntent | None:
    result = parse_request(query)
    return result.beckn_intent   # None for non-procurement queries
```

**Canonical output example:**
```json
{
  "item": "A4 paper 80GSM",
  "descriptions": ["A4", "80GSM"],
  "quantity": 500,
  "location_coordinates": "12.9716,77.5946",
  "delivery_timeline": 72,
  "budget_constraints": { "max": 200.0, "min": 0.0 }
}
```

---

### Layer 2 — Beckn BAP Client

**Docs:** [[beckn_bap_client]] · **Protocol:** Beckn v2 · **ONIX adapter:** Go, port 8081

#### Implemented flows

| Action | Python call | Callback received |
|---|---|---|
| `discover` | `POST /bap/caller/discover` | `POST :8000/bap/receiver/on_discover` |
| `select` | `POST /bap/caller/select` | `POST :8000/bap/receiver/on_select` |

#### Key files

| File | Responsibility |
|---|---|
| `src/beckn/adapter.py` | Builds Beckn v2 wire payloads (UUID txn IDs, RFC 3339 timestamps). Owns all URL construction. |
| `src/beckn/client.py` | Async HTTP layer. `discover_async()` registers queue, sends to ONIX, awaits `on_discover`. |
| `src/beckn/callbacks.py` | `CallbackCollector` — one `asyncio.Queue` per `(transaction_id, action)` for callback correlation. |
| `src/beckn/models.py` | Pydantic v2 models: `DiscoverOffering`, `DiscoverResponse`, `SelectOrder`, `SelectedItem`. |
| `src/server.py` | aiohttp server port 8000. Receives all inbound callbacks, dispatches to `CallbackCollector`. |
| `shared/models.py` | Anti-Corruption Layer — `BecknIntent`, `BudgetConstraints` shared by IntentParser and Bap-1. |

#### Async discover sequence

```
BecknClient.discover_async(intent, collector, timeout=15s)
  ├─ adapter.build_discover_wire_payload(intent)   → Beckn v2 JSON
  ├─ collector.register(txn_id, "on_discover")     → asyncio.Queue created
  ├─ POST /bap/caller/discover                     → beckn-onix :8081
  │     └─ ONIX → /bpp/discover on server.py      → ACK
  │           └─ ONIX fires callback              → POST :8000/bap/receiver/on_discover
  │                 └─ server.py → collector.put(txn_id, payload)
  └─ await Queue.get(timeout=15s)                  → DiscoverResponse
```

---

### Layer 3 — Procurement ReAct Agent

**Docs:** [[agent_react_framework]] · **Framework:** LangGraph `StateGraph` · **Branch:** `feature/agent-framework`

#### Graph topology

```
parse_intent → discover ──(offerings found)──→ rank_and_select → send_select → present_results
                        └──(empty / error)───────────────────────────────────→ present_results
```

#### Nodes

| Node | ReAct role | What it does |
|---|---|---|
| `parse_intent` | Reason | Calls `parse_nl_to_intent()`. Skips NLP if intent already pre-loaded. |
| `discover` | Act | Calls `BecknClient.discover_async()` → populates `offerings` and `transaction_id`. |
| `rank_and_select` | Reason | `min(offerings, key=lambda o: float(o.price_value))` — cheapest wins (Phase 1). |
| `send_select` | Act | Builds `SelectOrder`, calls `BecknClient.select()`. |
| `present_results` | Observe | Formats final summary. Always executes — never skipped. |

#### Reasoning trace example

```
[parse_intent]    item='A4 paper 80gsm' qty=500 loc=12.9716,77.5946 timeline=72h budget_max=200.0
[discover]        txn=a1b2c3 found 3 offering(s): OfficeWorld@₹195, PaperDirect@₹189, StationeryHub@₹201
[rank_and_select] selected 'PaperDirect' ₹189 (cheapest of 3)
[send_select]     ACK=ACK bpp=seller-2 provider=PaperDirect
[present_results] Order initiated — PaperDirect | A4 Paper Ream × 500 | ₹189 INR | txn=a1b2c3
```

---

### How to Run the Full Flow

#### Prerequisites

- Docker Desktop running
- Ollama running with `qwen3:1.7b` (only for NL query mode)
- `Bap-1/.env` configured

#### Step 1 — Start the Docker stack

```bash
cd starter-kit/generic-devkit/install
docker compose -f docker-compose-my-bap.yml up -d
```

Starts: `onix-bap` (port 8081), `onix-bpp`, `sandbox-bpp`, `redis`.

#### Step 2 — Start Ollama (NL mode only)

```bash
ollama run qwen3:1.7b
```

#### Step 3 — Run the agent

```bash
cd Bap-1

# NL query — full pipeline including Ollama
python run.py "500 reams A4 paper 80gsm Bangalore 3 days max 200 INR"

# Hardcoded intent — skips Ollama, uses INTENT constant in run.py
python run.py
```

#### Expected output

```
============================================================
  Procurement ReAct Agent — Beckn Protocol v2
============================================================
  BAP ID   : procurement-bap
  ONIX URL : http://localhost:8081
  Mode     : NL query

  Running agent...

    [parse_intent]    item='A4 paper 80gsm' qty=500 ...
    [discover]        txn=abc-123 found 3 offering(s): ...
    [rank_and_select] selected 'PaperDirect' ₹189 (cheapest of 3)
    [send_select]     ACK=ACK bpp=seller-2 provider=PaperDirect
    [present_results] Order initiated — PaperDirect | A4 Paper Ream × 500 | ₹189 INR | txn=abc-123

  Done. Next: /init -> /confirm -> /status
============================================================
```

---

### Test Coverage

**Command:** `pytest tests/ -v` (no Docker, no Ollama required)
**Result:** 59 passed, 0 failed

| File | Tests | Covers |
|---|---|---|
| `tests/test_agent.py` | 14 | LangGraph graph: state fields, routing, ranking, error propagation, reasoning trace |
| `tests/test_callbacks.py` | 10 | `CallbackCollector`: routing by txn_id/action, timeouts, concurrency |
| `tests/test_discover.py` | 17 | `BecknIntent` validation, adapter payload, discover URL, `discover_async` end-to-end |
| `tests/test_intent_parser.py` | 10 | Facade bridge, canonical field conversion, 3 integration queries via Ollama |
| `tests/test_select.py` | 9 | Select payload, ONIX URL invariant, `client.select()` end-to-end |

---

### Repository Layout

```
Procurement-Agent/
├── IntentParser/               ← NLP core (Stage 1 + Stage 2, Ollama)
├── shared/
│   └── models.py               ← BecknIntent, BudgetConstraints (ACL)
└── Bap-1/
    ├── src/
    │   ├── beckn/              ← adapter, client, callbacks, models
    │   ├── nlp/
    │   │   └── intent_parser_facade.py
    │   ├── agent/              ← feature/agent-framework: state, nodes, graph
    │   ├── config.py
    │   └── server.py           ← aiohttp :8000, callback routes
    ├── run.py                  ← entry point — ProcurementAgent.arun()
    └── tests/                  ← 59 unit tests
```

*Continues in → [[phase2_core_intelligence_transaction_flow]]*
