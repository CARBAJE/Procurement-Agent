---
tags: [intent-parser, pipeline, architecture, two-stage, beckn, nlp]
cssclasses: [procurement-doc, ai-doc]
status: "#approved"
related: ["[[02_Stage1_IntentClassifier]]", "[[03_Stage2_BecknIntentParser]]", "[[04_Domain_Gating_Procurement_Intents]]", "[[10_Heuristic_Complexity_Router]]", "[[05_ParsedIntent_Schema]]", "[[06_BecknIntent_Schema]]"]
---

# Two-Stage Intent Parsing Pipeline — Overview

> [!architecture] Pipeline Summary
> The intent parsing pipeline is a **two-stage, schema-validated NLP system** for enterprise procurement intent extraction on the Beckn Protocol. Stage 1 classifies free-form user queries into procurement intent categories. Stage 2 — activated **only for procurement-relevant intents** — extracts a fully structured, Beckn-compatible `BecknIntent` object. The pipeline uses [[08_Instructor_Library_Integration|`instructor`]] for guaranteed structured LLM output, [[09_Pydantic_v2_Schema_Enforcement|Pydantic v2]] for schema enforcement with runtime validators, and a [[10_Heuristic_Complexity_Router|heuristic complexity router]] for compute allocation.

---

## Full Pipeline Diagram

```
User Query (natural language)
        │
        ▼
┌───────────────────────────────────────┐
│  Stage 1: IntentClassifier            │
│  Model: qwen3:8b (fixed)              │
│  Output: ParsedIntent                 │
│  - intent (open PascalCase str)       │
│  - product_name, quantity             │
│  - confidence [0.0, 1.0]             │
│  - reasoning                          │
└───────────────────────────────────────┘
        │
        ▼ intent ∈ {"SearchProduct","RequestQuote","PurchaseOrder"}?
        │
    ┌───┴──────┐
    │ NO       │ YES
    │          ▼
    │  ┌────────────────────────────────────────────┐
    │  │  is_complex_request(query) heuristic       │
    │  │  ┌─ len > 120  → complex                  │
    │  │  ├─ ≥ 2 numerics → complex               │
    │  │  ├─ delivery keywords → complex           │
    │  │  └─ budget keywords → complex             │
    │  └────────────────────────────────────────────┘
    │          │
    │    complex?──┬──No──► qwen3:1.7b
    │              └──Yes─► qwen3:8b
    │          │
    │          ▼
    │  ┌───────────────────────────────────────────┐
    │  │  Stage 2: BecknIntentParser               │
    │  │  Output: BecknIntent                      │
    │  │  - item, descriptions, quantity           │
    │  │  - location_coordinates (lat,lon)         │
    │  │  - delivery_timeline (hours)              │
    │  │  - budget_constraints {min, max}          │
    │  └───────────────────────────────────────────┘
    │          │
    ▼          ▼
{"intent": ..., "beckn_intent": None}   {"intent": ..., "beckn_intent": {...}, "routed_to": ...}
```

---

## Stage Responsibilities

| Stage | Class | Output Schema | Purpose |
|---|---|---|---|
| Stage 1 | `IntentClassifier` | [[05_ParsedIntent_Schema\|ParsedIntent]] | Domain gatekeeper — classify and short-circuit non-procurement queries |
| Stage 2 | `BecknIntentParser` | [[06_BecknIntent_Schema\|BecknIntent]] | Deep structured extraction — produce Beckn-protocol-ready JSON |

## Key Architectural Properties

- **Separation of concerns:** Stage 1 never attempts to extract Beckn fields. Stage 2 is never invoked for non-procurement queries. Each stage has a single, clearly bounded responsibility.
- **Compute efficiency:** The [[10_Heuristic_Complexity_Router|`is_complex_request()` heuristic]] allocates model capacity per query complexity — lightweight queries go to `qwen3:1.7b`, complex queries to `qwen3:8b`.
- **Guaranteed structured output:** Both stages use [[08_Instructor_Library_Integration|`instructor`]] + [[09_Pydantic_v2_Schema_Enforcement|Pydantic v2]] — the caller always receives a validated object, never a raw string.
- **Graceful fallback:** If Stage 2's lightweight model fails validation after `max_retries=3`, the query escalates to the heavy model automatically — see [[12_Retry_Mechanism_Validation_Feedback_Loop]].

## Output Shape

**Non-procurement query (Stage 1 short-circuits):**
```json
{"intent": "Greeting", "beckn_intent": null}
```

**Procurement query (Stage 2 completes):**
```json
{
  "intent": "SearchProduct",
  "beckn_intent": {
    "item": "SS flanged valve",
    "descriptions": ["SS316", "flanged", "2 inch"],
    "quantity": 500,
    "location_coordinates": "12.9716,77.5946",
    "delivery_timeline": 120,
    "budget_constraints": {"min": 0.0, "max": 50000.0}
  },
  "routed_to": "qwen3:8b"
}
```

## Related Notes
- [[02_Stage1_IntentClassifier]] — Stage 1 detailed design
- [[03_Stage2_BecknIntentParser]] — Stage 2 detailed design
- [[04_Domain_Gating_Procurement_Intents]] — The short-circuit gating logic
- [[10_Heuristic_Complexity_Router]] — Model routing between `qwen3:1.7b` and `qwen3:8b`
- [[26_Production_vs_Prototype_Divergences]] — How this prototype maps to the production Lambda 1
