---
tags: [intent-parser, schema, pydantic, becknintent, stage2, structured-output, beckn]
cssclasses: [procurement-doc, ai-doc]
status: "#approved"
related: ["[[03_Stage2_BecknIntentParser]]", "[[07_BudgetConstraints_Schema]]", "[[09_Pydantic_v2_Schema_Enforcement]]", "[[13_Location_Resolution]]", "[[23_Beckn_Protocol_Structured_Fields_Context]]", "[[08_Instructor_Library_Integration]]"]
---

# `BecknIntent` — Stage 2 Output Schema

> [!architecture] Role
> `BecknIntent` is the Pydantic model produced by [[03_Stage2_BecknIntentParser|Stage 2]]. It is the **single structured output** of the entire intent parsing pipeline for procurement queries. It is also declared in `shared/models.py` as the **single source of truth** shared across all Lambda services in the microservices architecture. Every downstream step — [[beckn_bap_client|BAP `discover`]], [[comparison_scoring_engine|comparison]], [[negotiation_engine|negotiation]] — receives a `BecknIntent` as its input.

---

## Full Pydantic Definition

```python
class BudgetConstraints(BaseModel):
    max: float
    min: float = 0.0   # defaults to 0 when only an upper bound is stated

class BecknIntent(BaseModel):
    item: str
    descriptions: list[str]          # technical specs decomposed into a list
    quantity: int
    location_coordinates: str        # resolved to "lat,lon" by validator
    delivery_timeline: int           # normalized to hours
    budget_constraints: BudgetConstraints

    @field_validator("delivery_timeline")
    @classmethod
    def timeline_positive(cls, v: int) -> int:
        if v <= 0:
            raise ValueError(f"delivery_timeline must be > 0, got {v}")
        return v

    @field_validator("location_coordinates")
    @classmethod
    def apply_location_lookup(cls, v: str) -> str:
        return resolve_location(v)  # deterministic lookup before validator exits
```

---

## Field-by-Field Analysis

### `item: str`
The canonical item name extracted from the user's query. This is the primary search key used in the BAP `discover` query. It should be concise and representative — not a technical specification string.

**Examples:**
- `"A4 paper"` (not `"A4 80gsm paper for office printing"`)
- `"SS flanged valve"` (not the full specification)
- `"ergonomic office chair"` (not `"chair with lumbar support adjustable height armrests"`)

### `descriptions: list[str]`
Atomic technical specification tokens — each element is a single spec component:

```
User says: "200 A4 80gsm paper reams, ISO certified"
descriptions = ["A4", "80gsm", "ISO certified"]

User says: "500 SS316 flanged valve 2 inch ASME"
descriptions = ["SS316", "flanged", "2 inch", "ASME"]
```

This decomposition is deliberate: the Beckn `discover` query uses these tokens as attribute filters. A single concatenated string would be treated as a substring match; individual tokens enable structured filtering against BPP catalog attributes.

### `quantity: int`
Required (not Optional as in [[05_ParsedIntent_Schema|`ParsedIntent`]]). The Stage 2 schema enforces this — a procurement intent without a quantity is structurally incomplete.

### `location_coordinates: str`
Always resolved to `"lat,lon"` format by the `apply_location_lookup` validator before the field is finalized. See [[13_Location_Resolution]] for the full `resolve_location()` implementation.

**Why `str` not a `GPS` type:** The Beckn Protocol represents GPS coordinates as a string (`"lat,lon"`) in its JSON payloads. Using `str` directly avoids a type conversion step at the BAP client layer.

### `delivery_timeline: int`
Duration in **hours** — not days, not a relative string. The system prompt provides conversion rules:
- `"within 5 days"` → `120` (5 × 24)
- `"next week"` → `168` (7 × 24)
- `"72 hours"` → `72`

The `@field_validator("delivery_timeline")` enforces `> 0` — a timeline of 0 or negative hours is physically impossible and indicates extraction failure. This triggers the [[12_Retry_Mechanism_Validation_Feedback_Loop|instructor retry loop]].

### `budget_constraints: BudgetConstraints`
Nested model — see [[07_BudgetConstraints_Schema]] for the full `BudgetConstraints` definition.

---

## Runtime Validators as Anti-Corruption Layer

The two `@field_validator` decorators enforce the [[23_Beckn_Protocol_Structured_Fields_Context|Beckn Protocol's structural requirements]] at the LLM output boundary:

| Validator | Constraint | Effect of Failure |
|---|---|---|
| `timeline_positive` | `delivery_timeline > 0` | `ValueError` → [[12_Retry_Mechanism_Validation_Feedback_Loop\|instructor retry]] |
| `apply_location_lookup` | Deterministic city resolution | Normalizes LLM output; no failure for known cities |

See [[09_Pydantic_v2_Schema_Enforcement]] for how `@field_validator` interacts with `instructor`'s retry mechanism.

---

## `BecknIntent` in the Production Architecture

In production (the [[nl_intent_parser|NL Intent Parser]] microservice, Lambda 1), `BecknIntent` is defined in `shared/models.py` — the single source of truth shared across all services. The [[beckn_bap_client|BAP client]] imports `BecknIntent` from this shared module to build its `discover` request payload.

The notebook's `BecknIntent` definition (above) is the **prototype** — the production definition is identical in schema but adds LangSmith tracing instrumentation. See [[26_Production_vs_Prototype_Divergences]].

---

## Related Notes
- [[07_BudgetConstraints_Schema]] — Nested `BudgetConstraints` model
- [[03_Stage2_BecknIntentParser]] — The stage that produces `BecknIntent`
- [[13_Location_Resolution]] — `resolve_location()` called inside `apply_location_lookup`
- [[23_Beckn_Protocol_Structured_Fields_Context]] — Why these exact fields and types are required by the Beckn Protocol
- [[09_Pydantic_v2_Schema_Enforcement]] — How `Field(description=...)` guides LLM extraction
- [[05_ParsedIntent_Schema]] — Stage 1 schema (shallower; produced before this schema)
