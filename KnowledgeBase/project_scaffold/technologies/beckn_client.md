---
tags: [technology, beckn, protocol, ondc, aiohttp, python, async, bap]
cssclasses: [procurement-doc, tech-doc]
status: "#processed"
related: ["[[nl_intent_parser]]", "[[comparison_scoring_engine]]", "[[negotiation_engine]]", "[[phase1_foundation_protocol_integration]]", "[[phase2_core_intelligence_transaction_flow]]", "[[phase3_advanced_intelligence_enterprise_features]]", "[[beckn_bap_client]]"]
---

# Beckn BAP Client — Python + aiohttp

> [!architecture] Role in the System
> This is the **protocol adapter** between the [[agent_framework_langchain_langgraph|LangChain agent]] and the open Beckn/ONDC commerce network. The agent invokes it as a tool — passing structured intent from [[nl_intent_parser]] — and the client translates those calls into Beckn-compliant HTTP requests, manages asynchronous seller callbacks, and returns normalized responses to the [[comparison_scoring_engine]].

## Implementation

| Layer | Technology |
|---|---|
| HTTP client | Python + `aiohttp` (async) |
| Protocol adapter | Custom Beckn protocol adapter |
| Language | Python |

> [!tech-stack] Why Async-First
> Beckn's `/on_search` callbacks arrive **asynchronously** from multiple sellers simultaneously — a synchronous HTTP client would serialize these, adding `n × latency` per seller instead of `max(latency)`. With `aiohttp`, the client dispatches `/search`, then collects all `/on_search` responses concurrently as they arrive, feeding them to the [[comparison_scoring_engine]] in a single batch. This is why Story 1 achieves 12 seller responses in 8 seconds.

## Core Beckn Transaction Flows

| Flow | Endpoint | Purpose |
|---|---|---|
| Discovery | `/search` | Broadcasts procurement intent across the open network |
| Discovery response | `/on_search` (callback) | Collects async seller responses |
| Negotiation | `/select` | Signals buyer interest; proposes modified terms |
| Initialization | `/init` | Initiates order |
| Confirmation | `/confirm` | Places the order |
| Tracking | `/status` | Retrieves real-time order tracking |

## Catalog Normalization Layer

Diverse sellers return different catalog formats. The normalization layer (embedded in this component) standardizes them into a unified schema for the [[comparison_scoring_engine]]:

1. **Schema mapping rules** (deterministic) — covers 80%+ of known seller formats.
2. **LLM-based normalizer** ([[llm_providers|GPT-4o]]) — handles edge cases and unknown formats.

**Phase 2 acceptance:** Handles 5+ distinct seller catalog formats correctly.

> [!milestone] Phase Delivery
> - **[[phase1_foundation_protocol_integration|Phase 1]] (Weeks 1–4):** `/search` and `/on_search` functional against Beckn sandbox; 3+ seller responses parsed correctly.
> - **[[phase2_core_intelligence_transaction_flow|Phase 2]] (Weeks 5–8):** `/init`, `/confirm`, `/status` implemented; full order lifecycle validated against sandbox.
> - **[[phase3_advanced_intelligence_enterprise_features|Phase 3]] (Weeks 9–12):** Multi-network concurrent queries to 2+ Beckn networks; graceful degradation when one network is down.

> [!guardrail] Async Reliability
> The client must handle partial response sets gracefully — if only 8 of 12 sellers respond within the timeout window, the [[comparison_scoring_engine]] proceeds with the available responses. Missing callbacks are logged to [[audit_trail_system|Kafka audit events]]. The [[observability_stack|Prometheus]] `beckn_api_success_rate` metric must remain ≥ 99.5%.
