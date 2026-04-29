---
tags: [intent-parser, schema, pydantic, parsedintent, stage1, structured-output]
cssclasses: [procurement-doc, ai-doc]
status: "#approved"
related: ["[[02_Stage1_IntentClassifier]]", "[[09_Pydantic_v2_Schema_Enforcement]]", "[[08_Instructor_Library_Integration]]", "[[04_Domain_Gating_Procurement_Intents]]", "[[12_Retry_Mechanism_Validation_Feedback_Loop]]"]
---

# `ParsedIntent` — Stage 1 Output Schema

> [!architecture] Role
> `ParsedIntent` is the Pydantic model produced by [[02_Stage1_IntentClassifier|Stage 1]]. It captures the raw classification result before the pipeline decides whether to invoke [[03_Stage2_BecknIntentParser|Stage 2]]. It is a **shallow extraction schema** — it does not attempt to extract Beckn-specific fields.

---

## Full Pydantic Definition

```python
class ParsedIntent(BaseModel):
    intent: str          # open-ended PascalCase; no Literal[] constraint
    product_name: Optional[str]
    quantity: Optional[int]
    confidence: float    # bounded [0.0, 1.0] via @field_validator
    reasoning: str

    @field_validator("confidence")
    @classmethod
    def confidence_in_range(cls, v: float) -> float:
        if not 0.0 <= v <= 1.0:
            raise ValueError(f"confidence must be in [0, 1], got: {v}")
        return round(v, 2)
```

---

## Field-by-Field Analysis

### `intent: str`
The LLM-synthesized intent label in PascalCase. **No `Literal` constraint** — see design decision below.

### `product_name: Optional[str]`
Shallow extraction of the item name. Optional because not all queries reference a product (e.g., `"CancelOrder"`). This is a preliminary signal — the canonical item extraction happens in [[03_Stage2_BecknIntentParser|Stage 2]]'s `BecknIntent.item` field.

### `quantity: Optional[int]`
Shallow extraction of a numeric quantity. Optional for the same reasons as `product_name`. Stage 2 extracts a required, validated `quantity: int` from `BecknIntent`.

### `confidence: float`
The LLM's self-assessed confidence in its intent classification, bounded `[0.0, 1.0]`. The `@field_validator` enforces this range at runtime and rounds to 2 decimal places.

**Why `@field_validator` instead of `Annotated[float, Field(ge=0.0, le=1.0)]`:** The validator raises a descriptive `ValueError` that [[08_Instructor_Library_Integration|`instructor`]] captures and feeds back to the LLM as an explicit correction. Pydantic's built-in `ge`/`le` constraints produce less informative error messages — the custom validator produces `"confidence must be in [0, 1], got: 1.5"`, which is clearer feedback for the model's retry loop.

### `reasoning: str`
The LLM's free-text justification for its classification. This field serves two purposes:
1. **Interpretability** — the reasoning string can be logged and audited to understand why a query was classified a certain way
2. **Chain-of-thought effect** — requiring the LLM to produce a reasoning string before the intent label improves classification accuracy (implicit chain-of-thought prompting)

---

## Design Decision — `intent: str` vs. `Literal[...]`

Using `str` instead of a fixed `Literal["SearchProduct", "RequestQuote", "PurchaseOrder"]`:

| Aspect | `str` (chosen) | `Literal[...]` |
|---|---|---|
| **Unanticipated intents** | LLM synthesizes `"Greeting"`, `"CancelOrder"` — handled cleanly | Forced into nearest procurement label — false positives |
| **Extensibility** | New intent classes handled without redeployment | Requires schema change + redeployment |
| **Gate dependency** | Requires explicit [[04_Domain_Gating_Procurement_Intents\|`_PROCUREMENT_INTENTS` set check]] | Gate is implicit (enum enforces it) |
| **Recall** | Higher — no intent is silently misclassified | Lower — edge cases collapse into wrong labels |

The trade-off is accepted: higher recall requires an explicit domain gate, but eliminates false positives on non-procurement queries.

---

## `@field_validator("confidence")` as a Retry Trigger

This validator is an **intentional retry trigger**, not just a data quality guard. When the LLM outputs `confidence = 1.5` (a common LLM overshoot), the validator raises:

```
ValueError: confidence must be in [0, 1], got: 1.5
```

[[08_Instructor_Library_Integration|`instructor`]] intercepts this `ValidationError`, formats it as a correction prompt (`"Your previous answer was invalid because: confidence must be in [0, 1], got: 1.5"`), and re-invokes the LLM. The model self-corrects on the next attempt. See [[12_Retry_Mechanism_Validation_Feedback_Loop]] for the full retry cycle.

---

## Related Notes
- [[02_Stage1_IntentClassifier]] — Stage that produces `ParsedIntent`
- [[09_Pydantic_v2_Schema_Enforcement]] — How `Field(description=...)` and `@field_validator` work in this context
- [[08_Instructor_Library_Integration]] — How `instructor` uses this schema for output parsing and retry
- [[04_Domain_Gating_Procurement_Intents]] — How `ParsedIntent.intent` is evaluated for pipeline routing
- [[06_BecknIntent_Schema]] — The Stage 2 schema produced when `ParsedIntent.intent` passes the domain gate
