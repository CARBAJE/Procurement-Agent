---
tags: [component, ai, scoring, comparison, microservice, lambda, step-functions]
cssclasses: [procurement-doc, component-doc]
status: "#implemented"
related: ["[[beckn_bap_client]]", "[[microservices_architecture]]", "[[agent_react_framework]]", "[[approval_workflow]]", "[[phase2_core_intelligence_transaction_flow]]"]
---

# Component: Comparative & Scoring Engine

> [!architecture] Role in the System
> `services/comparative-scoring/` is **Lambda 3** in the Step Functions state machine. It is a standalone aiohttp microservice on port 8003. Called by the orchestrator as Step 3 after discovery. Receives all offerings, returns the single best one.

## HTTP Interface

```
POST /score
Body:     { "offerings": [DiscoverOffering…] }
Response: { "selected": DiscoverOffering } | { "selected": null }

GET /health
Response: { "status": "ok", "service": "comparative-scoring" }
```

`DiscoverOffering` fields in the body are plain JSON dicts — no import of `shared.models` required.

## Phase 1 — Cheapest Wins (Implemented)

```python
selected = min(offerings, key=lambda o: float(o["price_value"]))
```

Deterministic. Returns `null` if `offerings` is empty.

## Phase 2 — Multi-Criteria Scoring (Planned)

To be implemented inside this service (no other service changes needed):
- Price weight (deterministic)
- Delivery reliability (from memory/history)
- Quality indicators (hybrid LLM + rules)
- Compliance fit (LLM ReAct reasoning)
- Human-readable explanation per recommendation

## Called By

The orchestrator calls this service as **Step 3**:
```python
score_result = POST http://comparative-scoring:8003/score  { "offerings": offerings }
selected = score_result["selected"]
```

## Internal Structure

```
services/comparative-scoring/
├── src/handler.py    aiohttp server — POST /score with cheapest-wins logic
├── Dockerfile
└── requirements.txt  (aiohttp only — no LLM deps in Phase 1)
```
