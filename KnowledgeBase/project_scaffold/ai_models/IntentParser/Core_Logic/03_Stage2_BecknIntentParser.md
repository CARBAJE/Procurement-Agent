---
tags: [intent-parser, stage2, structured-extraction, beckn, becknintent, llm]
cssclasses: [procurement-doc, ai-doc]
status: "#approved"
related: ["[[01_Two_Stage_Pipeline_Overview]]", "[[06_BecknIntent_Schema]]", "[[10_Heuristic_Complexity_Router]]", "[[09_Pydantic_v2_Schema_Enforcement]]", "[[23_Beckn_Protocol_Structured_Fields_Context]]", "[[12_Retry_Mechanism_Validation_Feedback_Loop]]"]
---

# Stage 2 — `BecknIntentParser` (Deep Structured Extraction)

> [!architecture] Role
> Stage 2 performs **deep structured extraction** of Beckn-protocol-compatible fields. Unlike Stage 1 (which classifies), this stage transforms unstructured natural language into a machine-actionable JSON payload ready for the [[beckn_bap_client|BAP `discover` query]]. It is invoked **only when Stage 1 returns a procurement intent** (`SearchProduct`, `RequestQuote`, or `PurchaseOrder`).

---

## What Stage 2 Extracts

Stage 2 produces a fully validated [[06_BecknIntent_Schema|`BecknIntent`]] object with six fields:

| Field | Type | Description |
|---|---|---|
| `item` | `str` | Canonical item name (e.g., `"SS flanged valve"`) |
| `descriptions` | `list[str]` | Atomic technical spec tokens (e.g., `["SS316", "flanged", "2 inch"]`) |
| `quantity` | `int` | Numeric quantity |
| `location_coordinates` | `str` | `"lat,lon"` string — resolved by [[13_Location_Resolution\|`resolve_location()`]] validator |
| `delivery_timeline` | `int` | Duration in hours — normalized from natural language |
| `budget_constraints` | `BudgetConstraints` | `{min: float, max: float}` — see [[07_BudgetConstraints_Schema]] |

---

## Extraction Challenges and Mechanisms

Each extraction challenge is handled by a combination of system prompt engineering and Pydantic schema enforcement:

| Challenge | Mechanism |
|---|---|
| **Technical spec decomposition** | `descriptions: list[str]` — LLM decomposes `"A4 80gsm"` into `["A4", "80gsm"]` |
| **Location normalization** | `apply_location_lookup` validator + inline lookup table in system prompt (see [[13_Location_Resolution]]) |
| **Time unit normalization** | System prompt rule: `1 day = 24h`, `1 week = 168h` → `delivery_timeline: int` |
| **Budget extraction** | [[07_BudgetConstraints_Schema\|`BudgetConstraints`]] nested model; one-sided budget (`"under 2 rupees"`) → `{min: 0, max: 2.0}` |
| **Currency stripping** | System prompt rule: `"Use only numeric values, no currency symbols"` |

---

## Model Selection at Stage 2

Before invoking Stage 2, the [[10_Heuristic_Complexity_Router|`is_complex_request()` heuristic]] determines which model variant to use:

- **Simple query** (short, few numerics, no delivery/budget keywords) → `qwen3:1.7b`
- **Complex query** (long, multiple numerics, delivery or budget signals) → `qwen3:8b`

If `qwen3:1.7b` fails validation after 3 retries, Stage 2 automatically escalates to `qwen3:8b`. See [[12_Retry_Mechanism_Validation_Feedback_Loop]] for the full retry cycle.

---

## System Prompt Engineering at Stage 2

The Stage 2 system prompt is **Beckn-specific and schema-aligned**:

- Provides unit conversion rules (days → hours, weeks → hours)
- Instructs the LLM to strip currency symbols and use only float values
- Includes the [[13_Location_Resolution|city-to-coordinates lookup]] table for supported Indian cities
- Specifies that `descriptions` must be **atomic tokens** — individual spec components, not a concatenated string
- The `Field(description=...)` text on each [[06_BecknIntent_Schema|`BecknIntent`]] field acts as an inline instruction via [[09_Pydantic_v2_Schema_Enforcement|`instructor`'s schema injection]]

---

## Anti-Corruption Layer

The [[09_Pydantic_v2_Schema_Enforcement|`@field_validator`]] decorators on `delivery_timeline` and `location_coordinates` act as an **anti-corruption layer** at the LLM output boundary — see [[23_Beckn_Protocol_Structured_Fields_Context]]:

- `timeline_positive`: Rejects `delivery_timeline ≤ 0`; triggers [[12_Retry_Mechanism_Validation_Feedback_Loop|instructor retry]]
- `apply_location_lookup`: Runs `resolve_location()` deterministically, ensuring known Indian cities always become `"lat,lon"` regardless of LLM output format

This design ensures the [[nl_intent_parser|NL Intent Parser]] component produces Beckn-ready data directly — no defensive transformation code is needed in the [[beckn_bap_client|BAP client]].

---

## Output

When Stage 2 completes successfully, the pipeline returns:

```json
{
  "intent": "SearchProduct",
  "confidence": 0.97,
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

The `routed_to` field indicates which model was used for Stage 2. In production, this value records the actual LLM used (e.g., `"gpt-4o"`, `"claude-sonnet-4-6"`).

---

## Related Notes
- [[06_BecknIntent_Schema]] — Full Pydantic model definition
- [[07_BudgetConstraints_Schema]] — Nested budget model
- [[10_Heuristic_Complexity_Router]] — Model selection logic
- [[13_Location_Resolution]] — `resolve_location()` deterministic lookup
- [[23_Beckn_Protocol_Structured_Fields_Context]] — Why these exact fields are required by the Beckn Protocol
- [[12_Retry_Mechanism_Validation_Feedback_Loop]] — Automatic retry on validation failure
