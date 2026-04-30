---
tags: [intent-parser, schema, pydantic, budget, becknintent, stage2]
cssclasses: [procurement-doc, ai-doc]
status: "#approved"
related: ["[[06_BecknIntent_Schema]]", "[[03_Stage2_BecknIntentParser]]", "[[23_Beckn_Protocol_Structured_Fields_Context]]"]
---

# `BudgetConstraints` — Nested Budget Schema

> [!architecture] Role
> `BudgetConstraints` is the nested Pydantic model within [[06_BecknIntent_Schema|`BecknIntent`]] that encodes the buyer's budget range. It handles the common case where a user specifies only an upper bound — producing a valid numeric range that the [[beckn_bap_client|BAP client]] can use directly in a Beckn `discover` query filter.

---

## Full Pydantic Definition

```python
class BudgetConstraints(BaseModel):
    max: float
    min: float = 0.0   # defaults to 0 when only an upper bound is stated
```

---

## Field Analysis

### `max: float`
Required field. The upper limit of the buyer's acceptable price range. The LLM extracts this from expressions like:
- `"under ₹2,000 per unit"` → `max = 2000.0`
- `"budget of 50,000 INR total"` → `max = 50000.0`
- `"no more than $500 each"` → `max = 500.0`

The system prompt rule `"Use only numeric values, no currency symbols"` ensures the LLM strips `₹`, `INR`, `$`, and other currency markers before placing the value in `max`.

### `min: float = 0.0`
Optional field with a default of `0.0`. This handles the most common user input pattern: specifying only an upper bound.

```
User: "under 2 rupees per sheet"
→ BudgetConstraints(max=2.0, min=0.0)   ← min defaults to 0.0

User: "between 500 and 800 rupees"
→ BudgetConstraints(max=800.0, min=500.0)

User: "at least 1000 rupees quality"
→ BudgetConstraints(max=float('inf'), min=1000.0)   ← upper bound absent
```

---

## Why Not a Single `max_budget` Float?

A single field `max_budget: float` would force the pipeline to handle the two-sided budget case (`"between X and Y"`) with a separate field or string parsing. The `BudgetConstraints` nested model:

1. **Expresses both sides symmetrically** — `min` and `max` are equal citizens in the schema
2. **Maps directly to Beckn protocol filter syntax** — the BAP `discover` query accepts a price range, not a scalar
3. **Eliminates edge case logic** — the `min=0.0` default means any downstream code can always use `budget.min` safely without an `if budget.min is not None` guard

---

## Extraction Examples

| User Input | `min` | `max` |
|---|---|---|
| `"under 2 rupees"` | `0.0` (default) | `2.0` |
| `"budget: 50,000 INR"` | `0.0` (default) | `50000.0` |
| `"₹500–₹800 per unit"` | `500.0` | `800.0` |
| `"at least ₹1000 quality items"` | `1000.0` | `float('inf')` |
| `"no budget constraint"` | `0.0` (default) | `float('inf')` |

---

## Related Notes
- [[06_BecknIntent_Schema]] — Parent schema that contains `BudgetConstraints`
- [[03_Stage2_BecknIntentParser]] — Stage that extracts the budget values
- [[23_Beckn_Protocol_Structured_Fields_Context]] — Why numeric-only budget fields are required
