---
tags: [component, agent, react-loop, microservices, distributed, step-functions, python]
cssclasses: [procurement-doc, component-doc]
status: "#implemented"
related: ["[[microservices_architecture]]", "[[beckn_bap_client]]", "[[nl_intent_parser]]", "[[comparison_scoring_engine]]", "[[phase1_foundation_protocol_integration]]", "[[phase2_core_intelligence_transaction_flow]]"]
---

# Component: Procurement ReAct Agent — Distributed Architecture

> [!architecture] Role in the System
> The ReAct reasoning pattern (Reason → Act → Observe) is preserved but **distributed across microservices**. Each former LangGraph node is now an independent service or orchestrator step. The `services/orchestrator/src/workflow.py` is the new graph — sequential HTTP calls replace LangGraph edges.

## Node → Service Mapping

| Former LangGraph Node | New Location | HTTP Call |
|-----------------------|--------------|-----------|
| `parse_intent` | `services/intention-parser/` | `POST /parse` |
| `discover` | `services/beckn-bap-client/` | `POST /discover` |
| `rank_and_select` | `services/comparative-scoring/` | `POST /score` |
| `send_select` | `services/beckn-bap-client/` | `POST /select` |
| `present_results` | `services/orchestrator/` (response assembly) | — |

## State Management

State that was a shared `ProcurementState` TypedDict in memory is now **JSON payload** passed between services:

```python
# Former LangGraph approach (shared in-process state):
state["intent"] = BecknIntent(...)
state["offerings"] = [DiscoverOffering(...), ...]

# New microservices approach (JSON payload between services):
parse_result  = POST /parse    {"query": "..."}
discover_result = POST /discover  parse_result["beckn_intent"]
score_result  = POST /score    {"offerings": discover_result["offerings"]}
select_result = POST /select   {score_result["selected"], discover_result["transaction_id"]}
```

Each service is **stateless** — no shared asyncio state, no shared Python objects.

## Orchestrator: The New Graph

`services/orchestrator/src/workflow.py` implements the Step Functions state machine:

```python
# Step 1 — parse
parse_result = POST {INTENTION_PARSER_URL}/parse  { query }

# Step 2 — discover
discover_result = POST {BECKN_BAP_URL}/discover  { beckn_intent }

# Step 3 — score
score_result = POST {COMPARATIVE_SCORING_URL}/score  { offerings }

# Step 4 — select
select_result = POST {BECKN_BAP_URL}/select  { selected + txn_id }
```

Conditional routing (was LangGraph `add_conditional_edges`):
- If `intent != "procurement"` → return error (abort pipeline)
- If `offerings == []` → return without scoring or selecting

## Agents Embedded in Services

The ReAct pattern's **Reason** steps are implemented by embedded agents:

| Step | Agent | Location |
|------|-------|----------|
| parse_intent | Parser Agent (LLM) | `services/intention-parser/` via `IntentParser/` |
| rank_and_select | Deterministic (Phase 1), LLM planned (Phase 2) | `services/comparative-scoring/` |
| Catalog normalization | Normalizer Agent | `services/beckn-bap-client/src/normalizer/` |

## Entry Point

```bash
# Start all services
docker compose up --build

# Run the pipeline
python run.py "500 A4 paper Bangalore 3 days"
# Equivalent to:
curl -X POST http://localhost:8004/run -d '{"query": "500 A4 paper Bangalore 3 days"}'
```
