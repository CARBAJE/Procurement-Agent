---
tags: [intent-parser, routing, heuristic, model-selection, compute-optimization, complexity]
cssclasses: [procurement-doc, ai-doc]
status: "#approved"
related: ["[[01_Two_Stage_Pipeline_Overview]]", "[[11_Routing_Keyword_Signal_Sets]]", "[[03_Stage2_BecknIntentParser]]", "[[12_Retry_Mechanism_Validation_Feedback_Loop]]", "[[26_Production_vs_Prototype_Divergences]]"]
---

# Heuristic Complexity Router — `is_complex_request`

> [!important] Compute Allocation Policy
> The `is_complex_request(query: str) -> bool` function is the **compute allocation policy** of the pipeline. It determines which model variant handles [[03_Stage2_BecknIntentParser|Stage 2]] extraction: the resource-intensive `qwen3:8b` for complex queries, or the lightweight `qwen3:1.7b` for simple ones. This is a critical production optimization — at 10,000+ requests/month, the latency and compute differential between these two model sizes becomes significant.

---

## Full Implementation

```python
def is_complex_request(query: str) -> bool:
    # Signal 1: Length proxy for information density
    if len(query) > 120:
        return True
    # Signal 2: Multiple numeric values → multiple fields to extract
    if len(re.findall(r"\b\d+(?:\.\d+)?\b", query)) >= 2:
        return True
    # Signal 3: Delivery timeline present → temporal reasoning required
    lower = query.lower()
    if any(kw in lower for kw in _DELIVERY_KEYWORDS):
        return True
    # Signal 4: Budget constraint present → numeric range extraction required
    if any(kw in lower for kw in _BUDGET_KEYWORDS):
        return True
    return False
```

---

## The Four Signals

### Signal 1 — Length (`len(query) > 120`)
**Complexity proxy:** Longer queries carry more information density — more fields, more specifications, more disambiguation needed.

**Cost:** `O(1)` — cheapest possible check; evaluated first.

**Example:** `"We need 200 units of A4 80gsm paper, ISO certified, delivered to our Bangalore office within 5 working days, budget under ₹2,000 total"` (152 chars) → complex.

### Signal 2 — Multiple Numerics (`re.findall(r"\b\d+(?:\.\d+)?\b", ...) >= 2`)
**Complexity proxy:** Multiple numeric values in a query signal multiple extraction targets (quantity + price, or quantity + quantity + delivery days).

**Cost:** `O(n)` regex scan.

**Example:** `"500 units at ₹150 each"` → matches `500` and `150` → complex.

**Note:** A single numeric (`"100 pens"`) does NOT trigger this signal — quantity-only queries are simple.

### Signal 3 — Delivery Keywords
**Complexity proxy:** Presence of delivery/timeline vocabulary signals that the LLM must perform temporal reasoning and unit conversion to produce `delivery_timeline: int` in hours.

**Cost:** `O(k)` keyword set membership, where `k` = keyword count. `frozenset` provides `O(1)` average case — see [[11_Routing_Keyword_Signal_Sets]].

**Example:** `"need it within 3 days"` → `"within"` in `_DELIVERY_KEYWORDS` → complex.

### Signal 4 — Budget Keywords
**Complexity proxy:** Budget vocabulary signals numeric range extraction with currency stripping and min/max assignment.

**Cost:** `O(k)` keyword set membership.

**Example:** `"under ₹500 per unit"` → `"under"` in `_BUDGET_KEYWORDS` → complex.

---

## Signal Ordering — Why This Order Matters

The four signals are ordered by **computational cost** (cheapest first):

```
Signal 1: len()          — O(1)    — no iteration
Signal 2: re.findall()   — O(n)    — single pass over query string
Signal 3/4: frozenset    — O(k)    — keyword set membership
```

Python's short-circuit evaluation means Signal 1 aborts the function immediately for long queries — the `re.findall()` and keyword lookups are never executed. For the majority of complex queries (which are long), this saves two O(n) operations per call.

---

## Fallback Escalation

The routing decision is a **soft guide**, not a hard boundary. If `qwen3:1.7b` is selected but exhausts all retries without producing valid `BecknIntent` output, `BecknIntentParser.parse()` catches the `InstructorRetryException` and re-routes the query to `qwen3:8b` automatically.

```
is_complex_request() → False → qwen3:1.7b
        │
        │ max_retries=3 exhausted → InstructorRetryException
        │
        ▼
fallback to qwen3:8b
        │
        │ retry cycle runs again with qwen3:8b
        ▼
BecknIntent returned to caller
```

This is a **graceful degradation path** — it prevents `ValidationError` from propagating to the caller in edge cases where a query appears simple (short, no keywords) but contains unusual extraction requirements that the small model cannot handle.

---

## Heuristic Limitations

The four signals are **proxies**, not perfect complexity measures:
- A 10-word query with 3 numerics and a delivery keyword is marked complex — correctly
- A 200-character query in a foreign language may lack keywords — incorrectly marked simple
- Queries with implicit budget (no keyword) are underclassified — the fallback escalation handles these

The heuristic is intentionally simple: low compute cost, no ML inference, and the fallback escalation handles misclassifications without surfacing errors to the user.

---

## Production Mapping

In production (GPT-4o ecosystem), the complexity dimension maps to **model generation** rather than model size:

| Notebook | Production |
|---|---|
| Simple → `qwen3:1.7b` | Simple → `GPT-4o-mini` |
| Complex → `qwen3:8b` | Complex → `GPT-4o` |

The same `is_complex_request()` heuristic logic is used in production — the routing signals remain valid regardless of the model backend. See [[26_Production_vs_Prototype_Divergences]].

---

## Related Notes
- [[11_Routing_Keyword_Signal_Sets]] — `_DELIVERY_KEYWORDS` and `_BUDGET_KEYWORDS` frozensets
- [[01_Two_Stage_Pipeline_Overview]] — Full pipeline diagram showing router position
- [[03_Stage2_BecknIntentParser]] — Stage that uses the routing decision
- [[12_Retry_Mechanism_Validation_Feedback_Loop]] — The fallback escalation triggered on retry exhaustion
