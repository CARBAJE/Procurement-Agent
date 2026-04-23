---
tags: [component, beckn, protocol, ondc, bap, async, search, confirm, catalog-normalization, beckn-onix, go]
cssclasses: [procurement-doc, component-doc]
status: "#processed"
related: ["[[beckn_client]]", "[[nl_intent_parser]]", "[[comparison_scoring_engine]]", "[[negotiation_engine]]", "[[phase1_foundation_protocol_integration]]", "[[phase2_core_intelligence_transaction_flow]]", "[[phase3_advanced_intelligence_enterprise_features]]", "[[audit_trail_system]]"]
---

# Component: Beckn BAP Client

> [!architecture] Role in the System
> The Beckn BAP Client is the **protocol bridge** between the [[agent_framework_langchain_langgraph|LangChain agent]] and the open Beckn/ONDC commerce network. The system acts as an intelligent **Beckn Application Platform (BAP)** using a two-layer architecture: the **Python agent layer** invokes the **beckn-onix Go adapter** via HTTP, which handles protocol compliance (ED25519 signing, schema validation, async routing). Implementation technology: [[beckn_client|beckn-onix + Python agent layer]].

## Architecture: Two-Layer Protocol Bridge

```
LangChain Agent (Python)
      │  HTTP calls to localhost:8081
      ▼
beckn-onix Adapter (Go, BAP — port 8081)
      │  Beckn-signed HTTP messages
      ▼
Beckn/ONDC Network (BPPs)
      │  Async /on_* callbacks → port 8081
      ▼
beckn-onix Adapter routes to Python agent callback handlers
```

## Core Transaction Flows

### `discover` — Discovery (Beckn v2)
- Python agent calls `GET /discover` on the Discovery Service with structured procurement intent.
- Discovery Service queries the Catalog Service and returns matching BPP offerings synchronously.
- No async callbacks — the response is immediate (< 1s target).
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

| Action   | Python Agent Calls                         | ONIX Routes To BPP           | Response                                    |
| -------- | ------------------------------------------ | ---------------------------- | ------------------------------------------- |
| discover | `GET /discover` (to Discovery Service)     | —                            | Synchronous response with matching offerings |
| select   | `POST /bap/caller/select`                  | `POST /bpp/receiver/select`  | `POST /bap/receiver/on_select`              |
| init    | `POST /bap/caller/init`    | `POST /bpp/receiver/init`    | `POST /bap/receiver/on_init`    |
| confirm | `POST /bap/caller/confirm` | `POST /bpp/receiver/confirm` | `POST /bap/receiver/on_confirm` |
| status  | `POST /bap/caller/status`  | `POST /bpp/receiver/status`  | `POST /bap/receiver/on_status`  |

## Security: ED25519 Signing (beckn-onix)

All Beckn messages are signed automatically by the ONIX adapter:
- `signer.so` plugin attaches ED25519 `Authorization` header to every outbound request.
- `signvalidator.so` plugin validates signatures on every inbound callback.
- In dev mode (local-simple config), keys are pre-configured in YAML — no manual certificate generation required.
- In production: ED25519 key pairs managed via HashiCorp Vault or equivalent KMS.

## Catalog Normalization Layer

Diverse sellers return different catalog formats from `on_discover` callbacks. Normalization is fully handled by the [[catalog_normalizer]] module (`src/normalizer/`) — `BecknClient` delegates to it via a module-level singleton:

```python
_normalizer = CatalogNormalizer()
# inside _build_discover_response():
offerings.extend(_normalizer.normalize({"message": {"catalog": catalog}}, bpp_id, bpp_uri))
```

### Supported Formats

| Variant | Structure | Detection |
|---|---|---|
| `BECKN_V2_FLAT_RESOURCES` (1) | `resources[]` at catalog root (real Beckn v2) | `resources` key is a non-empty list |
| `ONDC_CATALOG` (4) | `fulfillments[]` + `tags[]` present | both keys present |
| `LEGACY_PROVIDERS_ITEMS` (2) | `providers[].items[]` (mock_onix/legacy) | `providers` list with `items` sub-key |
| `BPP_CATALOG_V1` (3) | `items[]` with `provider` as string ID | `items[0]["provider"]` is a string |
| `UNKNOWN` (5) | No fingerprint matched | LLM fallback (instructor + Ollama `qwen3:1.7b`) |

### Module layers (`src/normalizer/`)

- `FormatDetector` — pure function, detects variant via `FINGERPRINT_RULES` (ordered, first-match-wins)
- `SchemaMapper` — deterministic mapping for variants 1–4, no LLM
- `LLMFallbackNormalizer` — instructor + Ollama for unknown formats; returns `[]` on error, never raises
- `CatalogNormalizer` — public facade that orchestrates the 3-step pipeline

**Phase 2 acceptance:** Implemented — 5+ formats validated, 17 unit tests pass without Ollama.

> [!milestone] Phase Delivery
> - **[[phase1_foundation_protocol_integration|Phase 1]] (Weeks 1–4):** beckn-onix adapter deployed; `discover` and `publish` functional against Beckn v2 sandbox; 3+ seller responses parsed.
> - **[[phase2_core_intelligence_transaction_flow|Phase 2]] (Weeks 5–8):** `/init`, `/confirm`, `/status` implemented; full order lifecycle validated.
> - **[[phase3_advanced_intelligence_enterprise_features|Phase 3]] (Weeks 9–12):** Multi-network concurrent queries to 2+ Beckn networks; graceful degradation when one network is down.

> [!guardrail] Discovery Reliability
> If the Discovery Service returns fewer results than expected, the [[comparison_scoring_engine]] proceeds with available offerings. Logged to [[audit_trail_system|Kafka audit events]].
> [[observability_stack|Prometheus]] `beckn_api_success_rate` must remain ≥ 99.5% (per [[technical_performance_metrics]]).
