---
tags: [technology, ai, langchain, langgraph, agent-framework, react-loop, python]
cssclasses: [procurement-doc, tech-doc]
status: "#processed"
related: ["[[llm_providers]]", "[[beckn_bap_client]]", "[[vector_db_qdrant_pinecone]]", "[[observability_stack]]", "[[phase1_foundation_protocol_integration]]", "[[nl_intent_parser]]", "[[negotiation_engine]]"]
---

# Agent Framework — LangChain / LangGraph (Python)

> [!architecture] Role in the System
> LangChain / LangGraph is the **cognitive engine** of the procurement agent. It orchestrates every multi-step procurement workflow: taking the structured intent from [[nl_intent_parser]], invoking the [[beckn_bap_client|Beckn BAP Client]] tools, running the [[comparison_scoring_engine]], executing the [[negotiation_engine]], checking [[approval_workflow|approval thresholds]], and writing to the [[audit_trail_system]]. LangGraph models these workflows as directed graphs with conditional branching — enabling deterministic, auditable state transitions.

## Technologies

| Library | Role |
|---|---|
| LangChain | Tool-use, memory integration, LLM orchestration |
| LangGraph | Complex multi-step workflow graphs (stateful agent loops) |

> [!tech-stack] Why LangChain / LangGraph
> LangChain is the most mature Python agent orchestration library with first-class support for tool-use, [[vector_db_qdrant_pinecone|vector memory]], and [[observability_stack|LangSmith]] observability. LangGraph extends it to support **stateful directed graphs** — essential for procurement workflows that have conditional branches (e.g., route to [[approval_workflow]] if above threshold, retry [[negotiation_engine]] if counter-offer rejected). Production-grade agentic systems require this level of explicit state management to be auditable and debuggable.

## Agent Architecture — ReAct Loop

The core agent uses a **ReAct** (Reasoning + Acting) loop:

1. **Reason** — think through each procurement criterion step by step using [[llm_providers|GPT-4o]].
2. **Act** — invoke tools: [[beckn_bap_client|Beckn client]], [[erp_integration|ERP API]], [[comparison_scoring_engine|scoring engine]], [[vector_db_qdrant_pinecone|vector DB]].
3. **Observe** — process tool outputs, update state, decide next step.
4. **Repeat** — loop until a terminal state is reached (`confirmed`, `escalated`, `advisory_complete`).

## Operating Modes

| Mode | Trigger | Agent Behavior |
|---|---|---|
| Fully Autonomous | Below spend threshold, routine category | Search → Compare → Negotiate → Confirm without human step |
| Human-in-the-Loop | Above [[approval_workflow\|approval threshold]] | Search → Compare → Recommend → Wait for approval → Confirm |
| Advisory | CPO analytical run (Story 4) | Search → Compare → Report (no transaction executed) |

> [!milestone] Phase Delivery
> - **[[phase1_foundation_protocol_integration|Phase 1]]:** Agent autonomously plans and executes a 3-step procurement workflow. Acceptance: end-to-end search-to-recommendation without human intervention.
> - **[[phase2_core_intelligence_transaction_flow|Phase 2]]:** Full transaction lifecycle wired; [[approval_workflow|approval routing]] functional.
> - **[[phase3_advanced_intelligence_enterprise_features|Phase 3]]:** [[negotiation_engine]] and multi-network [[beckn_bap_client|search]] added; [[vector_db_qdrant_pinecone|vector memory]] connected for RAG retrieval.

## Observability

All LLM calls are traced by [[observability_stack|LangSmith]]: input prompt (with version), output, latency, token usage, cost. Every trace is tied to the [[model_governance_monitoring|Model Registry]] version — enabling full reproducibility and audit.

> [!guardrail] Agent Scope Constraints
> The agent operates strictly within the permissions granted by [[identity_access_keycloak|Keycloak RBAC]]. It **cannot** execute `/confirm` for orders above the requester's threshold without a confirmed approval event from the [[approval_workflow]]. All negotiation actions are validated against [[negotiation_strategy_model|negotiation policy boundaries]] before execution (max 20% discount cap).
