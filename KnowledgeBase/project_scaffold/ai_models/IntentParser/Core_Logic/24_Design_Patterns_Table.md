---
tags: [intent-parser, design-patterns, architecture, decisions]
cssclasses: [procurement-doc, ai-doc]
status: "#approved"
related: ["[[01_Two_Stage_Pipeline_Overview]]", "[[04_Domain_Gating_Procurement_Intents]]", "[[10_Heuristic_Complexity_Router]]", "[[09_Pydantic_v2_Schema_Enforcement]]", "[[13_Location_Resolution]]", "[[15_Multi_Backend_Support]]"]
---

# Design Patterns and Architectural Decisions

> [!architecture] Summary
> This note catalogues the eight design patterns applied in the intent parsing pipeline, their implementations, and the rationale for each decision. Together, these patterns represent the accumulated architectural reasoning for the two-stage extraction approach.

---

## Design Patterns Table

| Pattern | Implementation | Rationale |
|---|---|---|
| **Open intent vocabulary** | `intent: str` (not `Literal`) | Handles unanticipated intents without redeployment — see [[04_Domain_Gating_Procurement_Intents]] |
| **Two-stage pipeline** | `IntentClassifier` → `BecknIntentParser` | Separation of concerns; avoids extracting Beckn fields for non-procurement queries — see [[01_Two_Stage_Pipeline_Overview]] |
| **Heuristic model routing** | `is_complex_request()` | Compute cost optimization; routes lightweight queries to smaller model — see [[10_Heuristic_Complexity_Router]] |
| **Schema-as-prompt** | `Field(description=...)` | Instructions embedded in schema; no separate prompt engineering file — see [[09_Pydantic_v2_Schema_Enforcement]] |
| **Validator-as-guardrail** | `@field_validator` | Runtime constraint enforcement; triggers [[08_Instructor_Library_Integration\|instructor]] retry loop — see [[12_Retry_Mechanism_Validation_Feedback_Loop]] |
| **Deterministic post-processing** | `resolve_location()` in validator | Removes LLM uncertainty from location coordinates — see [[13_Location_Resolution]] |
| **Batch isolation** | `try/except` per future | Single query failures don't abort batch — see [[14_Batch_Processing_ThreadPoolExecutor]] |
| **Backend portability** | `instructor.from_*()` adapters | Same schemas work across Ollama, OpenAI, Anthropic — see [[15_Multi_Backend_Support]] |

---

## Pattern Deep-Dives

### Open Intent Vocabulary
The decision to use `intent: str` instead of a closed `Literal` enum is the foundational architectural choice that shapes the entire Stage 1 design. It trades implicit gate enforcement (closed enum) for explicit gate logic ([[04_Domain_Gating_Procurement_Intents|`_PROCUREMENT_INTENTS` set check]]) in exchange for graceful handling of unanticipated query types.

**The cost if wrong:** Over-reliance on open vocabulary without the explicit gate would cause Stage 2 to run on non-procurement queries, producing nonsensical `BecknIntent` objects that crash the [[beckn_bap_client|BAP client]].

### Two-Stage Pipeline
The separation between classification (Stage 1) and extraction (Stage 2) is motivated by the **principle of least work**: Stage 2 is expensive (more fields, more prompting, more potential retries) — invoking it on every query, including greetings and cancellations, wastes compute and degrades latency for non-procurement users.

**The cost if wrong:** A single-stage pipeline that always extracts all Beckn fields would produce `beckn_intent: {item: "Hello", quantity: null, ...}` for greetings, silently triggering a `discover` call for nonsensical items.

### Schema-as-Prompt
`Field(description=...)` co-locates the LLM instruction with the field definition — there is no separate prompt template file that must be kept in sync with the schema. When the schema evolves (new field added), the instruction travels with the field automatically.

**The cost if wrong:** Separate prompt templates and schema definitions drift out of sync as the codebase evolves — a common source of subtle extraction failures in production NLP systems.

### Deterministic Post-Processing
`resolve_location()` in the `@field_validator` ensures that **known cities always produce correct coordinates** — regardless of how the LLM formats the location string. This is the most reliable class of validator: deterministic, zero-latency, zero-cost, zero-variance.

**The cost if wrong:** Without deterministic resolution, LLM-produced coordinates carry ~10% error rate on known cities (spacing, precision, misspelling). Each error produces a BAP client protocol failure.

---

## Anti-Patterns Avoided

| Anti-Pattern | How It's Avoided |
|---|---|
| Manual `json.loads()` with try/except | [[08_Instructor_Library_Integration\|`instructor`]] handles all parsing |
| Hardcoded intent enum | Open `intent: str` + domain gate |
| Fixed model for all query complexities | Heuristic router allocates model by complexity |
| Separate prompt file per field | `Field(description=...)` co-locates instructions |
| Batch abort on single failure | Per-future `try/except` in `classify_batch()` |

---

## Related Notes
- [[01_Two_Stage_Pipeline_Overview]] — Two-stage separation of concerns
- [[04_Domain_Gating_Procurement_Intents]] — Open vocabulary + explicit gate
- [[10_Heuristic_Complexity_Router]] — Heuristic model routing
- [[09_Pydantic_v2_Schema_Enforcement]] — Schema-as-prompt pattern
- [[13_Location_Resolution]] — Deterministic post-processing
- [[15_Multi_Backend_Support]] — Backend portability
- [[14_Batch_Processing_ThreadPoolExecutor]] — Batch isolation
