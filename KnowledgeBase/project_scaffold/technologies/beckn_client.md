---
tags: [technology, beckn, protocol, ondc, beckn-onix, go, python, async, bap]
cssclasses: [procurement-doc, tech-doc]
status: "#processed"
related: ["[[nl_intent_parser]]", "[[comparison_scoring_engine]]", "[[negotiation_engine]]", "[[phase1_foundation_protocol_integration]]", "[[phase2_core_intelligence_transaction_flow]]", "[[phase3_advanced_intelligence_enterprise_features]]", "[[beckn_bap_client]]"]
---

# Beckn BAP Client — beckn-onix + Python Agent Layer

> [!architecture] Role in the System
> The Beckn integration uses a **two-layer architecture**: a **beckn-onix Go adapter** handles all Beckn protocol compliance (signing, schema validation, routing), while the **Python/LangChain agent** invokes it via its HTTP API. This separation allows the agent to focus on business logic while beckn-onix manages protocol-level concerns. The [[agent_framework_langchain_langgraph|LangChain agent]] passes structured intent from [[nl_intent_parser]] to the ONIX adapter, which translates calls into Beckn-compliant signed HTTP messages and returns normalized seller responses to the [[comparison_scoring_engine]].

## Architecture

```
Python/LangChain Agent
      │
      ▼  HTTP calls to ONIX adapter API
beckn-onix Go Adapter (port 8081 — BAP)
      │
      ▼  Beckn-compliant signed messages
Beckn Network (BPPs via Gateway)
```

## Implementation

| Layer | Technology |
|---|---|
| Protocol adapter | **beckn-onix** (Go ≥1.23) — handles signing, schema validation, routing |
| Agent HTTP client | Python + `httpx` / `aiohttp` — calls ONIX adapter at `localhost:8081` |
| Signing | ED25519 via `signer.so` plugin (auto-generated in dev mode) |
| State/cache | Redis 7 (port 6379) — used by ONIX adapter for message correlation |
| Language (adapter) | Go |
| Language (agent layer) | Python |

> [!tech-stack] Why beckn-onix over Custom Client
> beckn-onix (the Beckn Open Network Integration Exchange) provides battle-tested Beckn v1.1 protocol compliance out of the box: ED25519 request signing, schema validation against official JSON schemas, asynchronous callback routing, and plugin extensibility. Building a custom Python client equivalent would require reimplementing all of this — beckn-onix provides it as a maintained open-source framework. The Python agent layer simply makes HTTP calls to the ONIX adapter's well-defined API.

> [!tech-stack] Discovery is Now Synchronous
> In Beckn v2, discovery is handled synchronously via the Discovery Service. BPPs proactively register their catalogs by calling `POST /publish` to the Catalog Service. BAPs call `GET /discover` on the Discovery Service, which queries the Catalog Service and returns matching offerings directly — no async callbacks required. The async complexity of v1 (collecting multiple BPP callbacks via Redis) is eliminated for discovery. Redis is still used for state management of ongoing transactions (select/init/confirm). The Discovery Service returns matching offerings in <1s, replacing the v1 pattern of "12 seller responses in 8 seconds via async callbacks".

## Core Beckn Transaction Flows (via ONIX Adapter)

| Flow | Python Agent calls ONIX at | ONIX routes to BPP | BPP callback arrives at |
|---|---|---|---|
| Catalog Registration | BPP calls `POST /publish` to Catalog Service | — | — |
| Discovery | BAP calls `GET /discover` on Discovery Service | — | Returns matching offerings synchronously |
| Negotiation | `POST /bap/caller/select` | `POST /bpp/receiver/select` | `POST /bap/receiver/on_select` |
| Initialization | `POST /bap/caller/init` | `POST /bpp/receiver/init` | `POST /bap/receiver/on_init` |
| Confirmation | `POST /bap/caller/confirm` | `POST /bpp/receiver/confirm` | `POST /bap/receiver/on_confirm` |
| Tracking | `POST /bap/caller/status` | `POST /bpp/receiver/status` | `POST /bap/receiver/on_status` |

## beckn-onix Service Ports (Local Dev)

| Service | URL |
|---|---|
| BAP ONIX Adapter | `http://localhost:8081` |
| BPP ONIX Adapter | `http://localhost:8082` |
| Sandbox BAP | `http://localhost:3001` |
| Sandbox BPP | `http://localhost:3002` |
| Redis | `localhost:6379` |
| Registry (DeDI) | `http://localhost:3030` |
| Gateway | `http://localhost:4030` |

## Setup (beckn-onix)

```bash
git clone https://github.com/beckn/beckn-onix.git
cd beckn-onix
go mod download && go mod verify
go build -o server cmd/adapter/main.go
./install/build-plugins.sh   # compiles signer.so, signvalidator.so, cache.so
docker run -d --name redis-onix -p 6379:6379 redis:alpine
./install/setup.sh           # starts BAP + BPP ONIX adapters
```

## Catalog Normalization Layer

Diverse sellers return different catalog formats. The normalization layer (in the Python agent layer) standardizes them:

1. **Schema mapping rules** (deterministic) — covers 80%+ of known seller formats.
2. **LLM-based normalizer** ([[llm_providers|GPT-4o]]) — handles edge cases and unknown formats.

**Phase 2 acceptance:** Handles 5+ distinct seller catalog formats correctly.

> [!milestone] Phase Delivery
> - **[[phase1_foundation_protocol_integration|Phase 1]] (Weeks 1–4):** beckn-onix adapter deployed; `discover` and `publish` functional against Beckn v2 sandbox; 3+ seller responses parsed correctly.
> - **[[phase2_core_intelligence_transaction_flow|Phase 2]] (Weeks 5–8):** `/init`, `/confirm`, `/status` implemented via ONIX adapter; full order lifecycle validated against sandbox.
> - **[[phase3_advanced_intelligence_enterprise_features|Phase 3]] (Weeks 9–12):** Multi-network concurrent queries to 2+ Beckn networks; graceful degradation when one network is down.

> [!guardrail] Discovery Reliability
> If the Discovery Service returns fewer results than expected, the [[comparison_scoring_engine]] proceeds with the available offerings. Results are logged to [[audit_trail_system|Kafka audit events]]. The [[observability_stack|Prometheus]] `beckn_api_success_rate` metric must remain ≥ 99.5%.
