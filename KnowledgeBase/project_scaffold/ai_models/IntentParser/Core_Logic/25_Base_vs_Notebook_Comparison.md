---
tags: [intent-parser, comparison, evolution, prototype, architecture]
cssclasses: [procurement-doc, ai-doc]
status: "#approved"
related: ["[[26_Production_vs_Prototype_Divergences]]", "[[08_Instructor_Library_Integration]]", "[[10_Heuristic_Complexity_Router]]", "[[14_Batch_Processing_ThreadPoolExecutor]]", "[[15_Multi_Backend_Support]]"]
---

# Base Implementation vs. Notebook — Comparison

> [!architecture] Context
> This comparison documents the evolution from a baseline intent parsing implementation to the full notebook architecture. It shows which capabilities were added and why — serving as a record of the incremental design decisions. See [[26_Production_vs_Prototype_Divergences]] for how the notebook further diverges from production.

---

## Full Comparison Table

| Aspect | Base Implementation | This Notebook |
|---|---|---|
| **JSON parsing** | `json.loads()` manual | [[08_Instructor_Library_Integration\|`instructor`]] automatic |
| **Validation** | Basic Pydantic types | + `@field_validator` (range, positivity) — see [[09_Pydantic_v2_Schema_Enforcement]] |
| **Retry on failure** | None — exception propagates | Automated feedback loop (up to `max_retries`) — see [[12_Retry_Mechanism_Validation_Feedback_Loop]] |
| **Intent vocabulary** | `Literal[...]` fixed enum | `str` open-ended — LLM synthesizes names — see [[04_Domain_Gating_Procurement_Intents]] |
| **Extracted fields** | 3 (`intent`, `product`, `confidence`) | 5 + nested (`+ quantity`, `reasoning`) + `BecknIntent` (6 fields) — see [[06_BecknIntent_Schema]] |
| **Domain specificity** | Generic classification | Beckn Protocol-aligned extraction — see [[23_Beckn_Protocol_Structured_Fields_Context]] |
| **Model selection** | Single model (fixed) | Heuristic router (complexity → model size) — see [[10_Heuristic_Complexity_Router]] |
| **Batch processing** | Sequential | `ThreadPoolExecutor` parallel — see [[14_Batch_Processing_ThreadPoolExecutor]] |
| **Backend support** | Ollama only | Ollama, OpenAI, Anthropic — see [[15_Multi_Backend_Support]] |

---

## Key Capability Additions Explained

### From Fixed Enum to Open Vocabulary
The base implementation used `Literal["SearchProduct", "RequestQuote", "PurchaseOrder"]`. Every unanticipated query type was forced into the nearest label — causing false positives on greetings and support requests. The notebook's `intent: str` + [[04_Domain_Gating_Procurement_Intents|`_PROCUREMENT_INTENTS` gate]] adds zero overhead in the happy path but eliminates the false-positive class entirely.

### From 3 Fields to 5 + BecknIntent
The base extracted `intent`, `product`, and `confidence` — sufficient for routing but insufficient for constructing a Beckn `discover` payload. The notebook adds:
- `quantity` and `reasoning` to `ParsedIntent`
- A complete second-stage schema (`BecknIntent`) with 6 fields including location coordinates, timeline, and budget

This closes the gap between "what the user said" and "what the Beckn protocol needs."

### From Sequential to Parallel Batch Processing
The base implementation classified queries one at a time. The notebook's `ThreadPoolExecutor` with `max_workers=4` runs up to 4 LLM calls concurrently — a 4× throughput improvement on I/O-bound workloads with no correctness change.

### From Ollama-Only to Multi-Backend
The base was hardcoded to Ollama. The notebook's `instructor.from_*()` adapter pattern makes backend swapping a one-line change — which is the same pattern used in production for the GPT-4o → Claude Sonnet 4.6 failover.

---

## What Stayed the Same

- Two-stage concept (Stage 1 classifies; Stage 2 extracts)
- Pydantic as the schema layer
- `instructor` as the LLM interface (present in both, but used more fully in the notebook)
- `qwen3:8b` as the primary local model

---

## Related Notes
- [[26_Production_vs_Prototype_Divergences]] — How the notebook itself then diverges from production
- [[08_Instructor_Library_Integration]] — The `instructor` capability that replaces manual JSON parsing
- [[09_Pydantic_v2_Schema_Enforcement]] — The `@field_validator` capability added over the base
- [[10_Heuristic_Complexity_Router]] — The model selection capability added over the base
- [[15_Multi_Backend_Support]] — The multi-backend capability added over the base
