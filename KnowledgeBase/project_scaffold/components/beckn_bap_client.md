---
tags: [component, beckn, protocol, ondc, bap, async, search, confirm, catalog-normalization]
cssclasses: [procurement-doc, component-doc]
status: "#processed"
related: ["[[beckn_client]]", "[[nl_intent_parser]]", "[[comparison_scoring_engine]]", "[[negotiation_engine]]", "[[phase1_foundation_protocol_integration]]", "[[phase2_core_intelligence_transaction_flow]]", "[[phase3_advanced_intelligence_enterprise_features]]", "[[audit_trail_system]]"]
---

# Component: Beckn BAP Client

> [!architecture] Role in the System
> The Beckn BAP Client is the **protocol bridge** between the [[agent_framework_langchain_langgraph|LangChain agent]] and the open Beckn/ONDC commerce network. The system acts as an intelligent **Beckn Application Platform (BAP)** — sitting between enterprise users and the open network, translating agent tool calls into Beckn-compliant HTTP messages and returning normalized seller responses. Implementation technology: [[beckn_client|Python + aiohttp (async)]].

## Core Transaction Flows

### `/search` — Discovery
- Broadcasts the structured procurement intent (from [[nl_intent_parser]]) across the Beckn/ONDC network.
- Fundamentally different from querying a single marketplace — reaches **all network sellers simultaneously**.

### `/on_search` — Async Response Collection
- Sellers respond asynchronously via callback.
- `aiohttp` async client collects all responses concurrently.
- Responses feed into the **Catalog Normalization Layer** (below).

### `/select` — Negotiation Signal
- Signals buyer interest in specific offers.
- Allows the [[negotiation_engine|Negotiation Engine]] to propose modified terms (price, quantity, delivery).

### `/init` — Order Initialization
- Initiates the order with the selected seller.

### `/confirm` — Order Confirmation
- Places the confirmed order.
- Triggers [[event_streaming_kafka|Kafka]] publish → [[erp_integration|ERP sync]] + [[audit_trail_system|audit event]] + [[communication_slack_teams|notification dispatch]].

### `/status` — Order Tracking
- Retrieves real-time delivery status.
- Combined with webhooks → feeds [[real_time_tracking]].

## Catalog Normalization Layer

Diverse sellers return different catalog formats. The normalization layer:
1. **Schema mapping rules** (deterministic) — covers known seller formats.
2. **[[llm_providers|LLM]]-based normalizer** — handles edge cases and unknown formats.
3. **Output:** Unified schema consumable by [[comparison_scoring_engine]].

**Phase 2 acceptance:** Handles 5+ distinct seller catalog formats correctly.

> [!milestone] Phase Delivery
> - **[[phase1_foundation_protocol_integration|Phase 1]] (Weeks 1–4):** `/search` and `/on_search` against Beckn sandbox; 3+ seller responses parsed.
> - **[[phase2_core_intelligence_transaction_flow|Phase 2]] (Weeks 5–8):** `/init`, `/confirm`, `/status` implemented; full order lifecycle validated.
> - **[[phase3_advanced_intelligence_enterprise_features|Phase 3]] (Weeks 9–12):** Multi-network concurrent queries to 2+ Beckn networks; graceful degradation when one network is down.

> [!guardrail] Async Reliability
> The client handles **partial response sets** gracefully — if only 8 of 12 sellers respond within the timeout window, the [[comparison_scoring_engine]] proceeds with available responses. Unresponded sellers are logged to [[audit_trail_system|Kafka audit events]].
> [[observability_stack|Prometheus]] `beckn_api_success_rate` must remain ≥ 99.5% (per [[technical_performance_metrics]]).
