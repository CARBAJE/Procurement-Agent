---
tags: [intent-parser, routing, keywords, frozenset, heuristic, complexity]
cssclasses: [procurement-doc, ai-doc]
status: "#approved"
related: ["[[10_Heuristic_Complexity_Router]]"]
---

# Routing Keyword Signal Sets

> [!architecture] Role
> These two `frozenset` constants are the vocabulary-matching layer of the [[10_Heuristic_Complexity_Router|`is_complex_request()` heuristic]]. They detect delivery timeline and budget signals in the user query, which trigger routing to the heavier `qwen3:8b` model for [[03_Stage2_BecknIntentParser|Stage 2]] extraction.

---

## `_DELIVERY_KEYWORDS`

```python
_DELIVERY_KEYWORDS = frozenset({
    "delivery", "deliver", "timeline", "deadline",
    "days", "weeks", "hours", "within",
})
```

**What it catches:** Any query that implies a temporal constraint on delivery — phrases like:
- `"deliver within 5 days"`
- `"weekly deadline"`
- `"within the next 72 hours"`
- `"delivery by Friday"`

**Why these keywords trigger `complex = True`:** A query containing delivery vocabulary requires the LLM to:
1. Identify the temporal value (`5`, `72`, `next week`)
2. Identify the unit (`days`, `hours`, `weeks`)
3. Apply the unit conversion rule (`1 day = 24h`) from the system prompt
4. Output an integer `delivery_timeline` in hours

This is multi-step reasoning — the small model (`qwen3:1.7b`) may fail on unit conversion edge cases, especially for relative expressions like `"within the week"`.

---

## `_BUDGET_KEYWORDS`

```python
_BUDGET_KEYWORDS = frozenset({
    "budget", "price", "cost", "rupee", "rupees",
    "inr", "usd", "per unit", "per sheet", "per meter",
    "under", "maximum", "max",
})
```

**What it catches:** Any query that includes a monetary constraint — phrases like:
- `"under ₹500 per unit"` → `"under"` matches
- `"total budget 10,000 INR"` → `"inr"` matches
- `"max price 200"` → `"max"` matches
- `"cost per sheet under 2 rupees"` → `"rupees"` and `"under"` match

**Why these keywords trigger `complex = True`:** Budget extraction requires:
1. Stripping currency symbols and identifiers
2. Identifying the bounding direction (`under` = upper bound, `minimum` = lower bound)
3. Assigning values correctly to `BudgetConstraints.min` and `.max`
4. Handling implicit lower bounds (defaulting to `0.0`)

This is structurally more complex than plain quantity or item extraction.

---

## Why `frozenset`

`frozenset` is used instead of `list` or `set` for two reasons:

1. **`O(1)` average-case membership testing:** The `in` operator on a `frozenset` is a hash lookup — `O(1)` average case vs `O(n)` for a `list`. With `_BUDGET_KEYWORDS` containing 12 elements and `_DELIVERY_KEYWORDS` containing 8, the difference is marginal at this scale — but the `frozenset` choice signals intent: this collection is for membership testing, not iteration.

2. **Immutability:** `frozenset` cannot be modified after creation. This prevents accidental mutation of the keyword constants in hot paths — relevant when the classification function is called in a `ThreadPoolExecutor` with concurrent threads.

---

## Extending the Keyword Sets

To add coverage for new signal vocabulary (e.g., `"urgent"` → delivery signal, `"budget cap"` → budget signal), extend the appropriate `frozenset` by replacing it with a new set literal:

```python
_DELIVERY_KEYWORDS = frozenset({
    "delivery", "deliver", "timeline", "deadline",
    "days", "weeks", "hours", "within",
    "urgent", "asap", "immediately",  # ← added
})
```

No other changes are required — the [[10_Heuristic_Complexity_Router|`is_complex_request()` function]] reads the constants directly.

---

## Related Notes
- [[10_Heuristic_Complexity_Router]] — The full `is_complex_request()` function that uses these constants
- [[03_Stage2_BecknIntentParser]] — Stage 2 whose model selection depends on `is_complex_request()`
