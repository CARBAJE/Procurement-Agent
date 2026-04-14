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

| Milestone | Deliverable | Skills Required | Acceptance Criteria |
|---|---|---|---|
| Beckn Sandbox Setup | beckn-onix adapter deployed + Python agent layer connected to Beckn sandbox | Protocol engineering, Go, beckn-onix, Python | ONIX adapter sends `GET /discover` to Discovery Service and receives synchronous catalog response; BPP `POST /publish` to Catalog Service verified; ED25519 signing verified |
| Core API Flows | `discover`, `select`, `init` implemented (v2 flow) | Beckn protocol spec, API design | End-to-end discover flow against Beckn v2 sandbox with 3+ offerings returned |
| **NL Intent Parser** | [[nl_intent_parser\|LLM-based parser]] converting text to structured intent | LLM integration ([[llm_providers\|GPT-4o]]), prompt engineering, JSON schema | Correctly parses 15+ diverse requests into valid Beckn-compatible intent |
| Agent Framework | [[agent_framework_langchain_langgraph\|LangChain/LangGraph]] agent with ReAct loop | Python, LangChain, LLM APIs | Agent autonomously plans and executes a 3-step procurement workflow |
| Frontend Scaffold | [[frontend_react_nextjs\|React/Next.js]] app with auth, basic request form | React, TypeScript, Next.js | Running locally with SSO stub; request submission functional |
| Data Models | [[databases_postgresql_redis\|PostgreSQL]] schema for requests, offers, orders, audit events | Database design, SQL, migrations | Schema supports full procurement lifecycle with audit trail |

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

*Continues in → [[phase2_core_intelligence_transaction_flow]]*
