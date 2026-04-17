---
tags: [component, beckn, protocol, ondc, bap, async, search, confirm, catalog-normalization, beckn-onix, go]
cssclasses: [procurement-doc, component-doc]
status: "#processed"
related: ["[[beckn_client]]", "[[nl_intent_parser]]", "[[comparison_scoring_engine]]", "[[negotiation_engine]]", "[[phase1_foundation_protocol_integration]]", "[[phase2_core_intelligence_transaction_flow]]", "[[phase3_advanced_intelligence_enterprise_features]]", "[[audit_trail_system]]"]
---

# Component: Beckn BAP Client

> [!architecture] Role in the System
> The Beckn BAP Client is the **protocol bridge** between the [[nl_intent_parser|NL Intent Parser]] and the open Beckn/ONDC commerce network. The system acts as an intelligent **Beckn Application Platform (BAP)** using a two-layer architecture: the **Python BAP layer** invokes the **beckn-onix Go adapter** via HTTP, which handles protocol compliance (ED25519 signing, schema validation, async routing). Implementation technology: [[beckn_client|beckn-onix + Python BAP layer]].

## Entry Point: From NL to Wire Format

The full pipeline from user input to network call:

```
User NL Query
      │
      ▼
IntentParser (Ollama / qwen3:1.7b)         ← IntentParser/core.py
      │  ParseResult.beckn_intent
      ▼
intent_parser_facade.parse_nl_to_intent()  ← Bap-1/src/nlp/intent_parser_facade.py
      │  BecknIntent (shared/models.py ACL)
      ▼
BecknAdapter.build_discover_payload()      ← Bap-1/src/beckn/adapter.py
      │  Beckn v2 JSON (context + message)
      ▼
BecknClient.discover_async()               ← Bap-1/src/beckn/client.py
      │  POST /bap/caller/discover
      ▼
beckn-onix Adapter (Go, port 8081)
      │  ED25519-signed Beckn message
      ▼
BPP Network → on_discover callback
      │  POST host:8000/bap/receiver/on_discover
      ▼
server.py → CallbackCollector              ← Bap-1/src/server.py
      │  asyncio.Queue per (txn_id, action)
      ▼
discover_async() returns DiscoverResponse
```

## Architecture: Two-Layer Protocol Bridge

```
Python BAP Layer (run.py + src/)
      │  HTTP calls to localhost:8081
      ▼
beckn-onix Adapter (Go, BAP — port 8081)
      │  Beckn-signed HTTP messages
      ▼
Beckn/ONDC Network (BPPs)
      │  Async /on_* callbacks → port 8081
      ▼
beckn-onix Adapter routes to Python callback handlers (port 8000)
```

## Core Transaction Flows

### `discover` — Discovery (Beckn v2)
- Python BAP layer calls `POST /bap/caller/discover` on the ONIX adapter with a structured `BecknIntent`.
- ONIX adapter routes the request to the local catalog endpoint (`/bpp/discover` on `src/server.py`), which ACKs immediately and fires an async `on_discover` callback to `POST /bap/receiver/on_discover`.
- `BecknClient.discover_async()` blocks on a `CallbackCollector` queue until the callback arrives (configurable timeout, default 10s).
- Responses feed into the **Catalog Normalization Layer** (below).

### `publish` — Catalog Registration (BPP-side)
- BPPs register/update their product catalog by calling `POST /publish` to the Catalog Service.
- The BAP system does not initiate this — BPPs do it proactively when their catalog changes.
- The Catalog Service indexes offerings for efficient `discover` queries.

### `/select` — Negotiation Signal
- Python agent calls `POST /bap/caller/select` → ONIX routes to `POST /bpp/receiver/select`.
- Signals buyer interest in specific offers; allows the [[negotiation_engine|Negotiation Engine]] to propose modified terms.

### `/init` — Order Initialization
- Python agent calls `POST /bap/caller/init` → initiates the order with the selected seller.

### `/confirm` — Order Confirmation
- Python agent calls `POST /bap/caller/confirm` → places the confirmed order.
- Triggers [[event_streaming_kafka|Kafka]] publish → [[erp_integration|ERP sync]] + [[audit_trail_system|audit event]] + [[communication_slack_teams|notification dispatch]].

### `/status` — Order Tracking
- Python agent calls `POST /bap/caller/status` → retrieves real-time delivery status.
- Combined with webhooks → feeds [[real_time_tracking]].

## ONIX Endpoint Routing Table

| Action   | Python BAP Layer Calls          | ONIX Routes To                        | Callback to BAP                         |
| -------- | ------------------------------- | ------------------------------------- | --------------------------------------- |
| discover | `POST /bap/caller/discover`     | `/bpp/discover` (local catalog)       | `POST /bap/receiver/on_discover`        |
| select   | `POST /bap/caller/select`       | `POST /bpp/receiver/select`           | `POST /bap/receiver/on_select`          |
| init     | `POST /bap/caller/init`         | `POST /bpp/receiver/init`             | `POST /bap/receiver/on_init`            |
| confirm  | `POST /bap/caller/confirm`      | `POST /bpp/receiver/confirm`          | `POST /bap/receiver/on_confirm`         |
| status   | `POST /bap/caller/status`       | `POST /bpp/receiver/status`           | `POST /bap/receiver/on_status`          |

## Security: ED25519 Signing (beckn-onix)

All Beckn messages are signed automatically by the ONIX adapter:
- `signer.so` plugin attaches ED25519 `Authorization` header to every outbound request.
- `signvalidator.so` plugin validates signatures on every inbound callback.
- In dev mode (local-simple config), keys are pre-configured in YAML — no manual certificate generation required.
- In production: ED25519 key pairs managed via HashiCorp Vault or equivalent KMS.

## Catalog Normalization Layer

Diverse sellers return different catalog formats from `/discover` response. The normalization layer:
1. **Schema mapping rules** (deterministic) — covers known seller formats.
2. **[[llm_providers|LLM]]-based normalizer** — handles edge cases and unknown formats.
3. **Output:** Unified schema consumable by [[comparison_scoring_engine]].

**Phase 2 acceptance:** Handles 5+ distinct seller catalog formats correctly.

> [!milestone] Phase Delivery
> - **[[phase1_foundation_protocol_integration|Phase 1]] (Weeks 1–4):** beckn-onix adapter deployed; `discover` and `publish` functional against Beckn v2 sandbox; 3+ seller responses parsed.
> - **[[phase2_core_intelligence_transaction_flow|Phase 2]] (Weeks 5–8):** `/init`, `/confirm`, `/status` implemented; full order lifecycle validated.
> - **[[phase3_advanced_intelligence_enterprise_features|Phase 3]] (Weeks 9–12):** Multi-network concurrent queries to 2+ Beckn networks; graceful degradation when one network is down.

> [!guardrail] Discovery Reliability
> If the Discovery Service returns fewer results than expected, the [[comparison_scoring_engine]] proceeds with available offerings. Logged to [[audit_trail_system|Kafka audit events]].
> [[observability_stack|Prometheus]] `beckn_api_success_rate` must remain ≥ 99.5% (per [[technical_performance_metrics]]).
