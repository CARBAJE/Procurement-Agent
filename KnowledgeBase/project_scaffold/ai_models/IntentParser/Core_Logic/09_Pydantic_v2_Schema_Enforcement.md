---
tags: [intent-parser, pydantic, schema-enforcement, field-validator, structured-output, llm]
cssclasses: [procurement-doc, ai-doc]
status: "#approved"
related: ["[[08_Instructor_Library_Integration]]", "[[05_ParsedIntent_Schema]]", "[[06_BecknIntent_Schema]]", "[[12_Retry_Mechanism_Validation_Feedback_Loop]]"]
---

# Pydantic v2 — Schema Enforcement at Runtime

> [!tech-stack] Pydantic v2 in This Context
> Pydantic v2 is the **contract layer** between the LLM's probabilistic output and the deterministic data structures the downstream [[beckn_bap_client|Beckn BAP client]] expects. Two Pydantic primitives are central to this pipeline:
>
> **`Field(description=...)`** — The description string is directly used by [[08_Instructor_Library_Integration|`instructor`]] when constructing the prompt schema. It is not documentation; it is a **runtime instruction to the LLM**. Precise, domain-specific field descriptions are the primary lever for improving extraction accuracy without fine-tuning.
>
> **`@field_validator`** — Runs after type coercion. Used here to enforce range constraints that Pydantic's type system alone cannot express. A `ValueError` raised inside a validator is intercepted by `instructor` and used as feedback for the next retry attempt.

---

## `Field(description=...)` — Instructions Embedded in Schema

When `instructor` injects the JSON Schema into the LLM prompt, the `description` attribute of each field becomes a direct instruction to the LLM. For example:

```python
class BecknIntent(BaseModel):
    item: str = Field(
        description="The canonical product name. Use a concise, searchable label, not the full specification."
    )
    descriptions: list[str] = Field(
        description="Decompose technical specifications into individual atomic tokens. "
                    "Each token is one spec component (e.g., ['SS316', 'flanged', '2 inch'])."
    )
    delivery_timeline: int = Field(
        description="Duration in hours. Convert: 1 day = 24h, 1 week = 168h."
    )
```

The description text becomes the `"description"` key in the JSON Schema object that the LLM receives. This means:
- `"Use a concise, searchable label"` guides `item` extraction quality
- `"Decompose technical specifications into individual atomic tokens"` teaches the LLM how to format `descriptions`
- `"Convert: 1 day = 24h, 1 week = 168h"` provides the unit conversion rule inline

**This is prompt engineering at the schema level** — precise field descriptions improve extraction accuracy without modifying the system prompt, maintaining a single source of truth.

---

## `@field_validator` — Runtime Constraint Enforcement

`@field_validator` functions run after Pydantic's type coercion. They enforce business constraints that the type system cannot express:

### Confidence Bounds (ParsedIntent)

```python
@field_validator("confidence")
@classmethod
def confidence_in_range(cls, v: float) -> float:
    if not 0.0 <= v <= 1.0:
        raise ValueError(f"confidence must be in [0, 1], got: {v}")
    return round(v, 2)
```

- Enforces `[0.0, 1.0]` range — a probability value outside this range is physically meaningless
- Rounds to 2 decimal places — prevents `0.97000000001` noise from floating-point arithmetic

### Timeline Positivity (BecknIntent)

```python
@field_validator("delivery_timeline")
@classmethod
def timeline_positive(cls, v: int) -> int:
    if v <= 0:
        raise ValueError(f"delivery_timeline must be > 0, got {v}")
    return v
```

- Rejects `0` or negative timelines — physically impossible delivery deadlines
- Common LLM error: extracting `"immediate"` as `0` hours

### Location Normalization (BecknIntent)

```python
@field_validator("location_coordinates")
@classmethod
def apply_location_lookup(cls, v: str) -> str:
    return resolve_location(v)  # deterministic lookup before validator exits
```

- Calls [[13_Location_Resolution|`resolve_location()`]] deterministically on every value
- The LLM may output `"Bangalore"`, `"12.9716, 77.5946"` (with space), or `"12.97,77.59"` (truncated) — the validator normalizes all forms to `"12.9716,77.5946"`

---

## `@field_validator` as an Intentional Retry Trigger

The `confidence` and `delivery_timeline` validators are designed as **intentional retry triggers**. When they raise `ValueError`, [[08_Instructor_Library_Integration|`instructor`]] does not surface the error to the caller — it captures the error text and uses it as correction feedback in the next LLM call.

```
LLM outputs: {"confidence": 1.5, ...}
                    │
                    ▼
Pydantic runs: confidence_in_range(1.5)
                    │
                    ▼
ValueError: "confidence must be in [0, 1], got: 1.5"
                    │
                    ▼
instructor appends to conversation:
  [assistant]: <the invalid JSON>
  [user]:      "Your previous answer was invalid: confidence must be in [0, 1], got: 1.5"
                    │
                    ▼
LLM retry: {"confidence": 0.97, ...}  ← corrected
```

See [[12_Retry_Mechanism_Validation_Feedback_Loop]] for the full closed-loop retry cycle.

---

## Why `@field_validator` Not `Annotated[float, Field(ge=0.0, le=1.0)]`

Pydantic v2 supports `Annotated` constraints for simple range validation. The custom `@field_validator` approach is used here because:

1. **Richer error messages:** `"confidence must be in [0, 1], got: 1.5"` vs `"Input should be less than or equal to 1"` — the former gives the LLM better correction context
2. **Side effects:** The `confidence_in_range` validator also rounds the value (`round(v, 2)`); `Annotated` constraints are read-only
3. **Composability:** Validators can call external functions (e.g., `resolve_location()`) — `Annotated` constraints cannot

---

## Related Notes
- [[08_Instructor_Library_Integration]] — How `instructor` uses `Field(description=...)` for schema injection and handles `ValidationError` from validators
- [[05_ParsedIntent_Schema]] — `ParsedIntent` applying `@field_validator("confidence")`
- [[06_BecknIntent_Schema]] — `BecknIntent` applying `@field_validator("delivery_timeline")` and `@field_validator("location_coordinates")`
- [[12_Retry_Mechanism_Validation_Feedback_Loop]] — The full retry mechanism triggered by validator failures
- [[13_Location_Resolution]] — The `resolve_location()` function called inside the location validator
