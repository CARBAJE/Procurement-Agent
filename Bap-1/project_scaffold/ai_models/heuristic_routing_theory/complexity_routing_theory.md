---
tags: [theory, architecture, ai-models, model-routing, heuristics, compute-optimization, latency, llm-router]
cssclasses: [procurement-doc, theory-doc]
status: "#theory"
related: ["[[intent_parsing_model]]", "[[model_governance_monitoring]]", "[[llm_providers]]", "[[constrained_generation_theory]]", "[[beckn_data_theory]]", "[[user_adoption_metrics]]", "[[technical_performance_metrics]]"]
---

# Heuristic-Based Model Routing — Theory of Compute Allocation

#theory #architecture #ai-models #model-routing #heuristics

> [!abstract] Rationale
> In any system that serves multiple request complexity classes through a single inference pipeline, the question of **which model to invoke** is itself an optimization problem. The routing function is a policy: it maps a query to a computational resource. The theoretical framing of `is_complex_request()` is not a classification problem solved by ML — it is a **deterministic heuristic policy** that exploits observable surface features of the input to approximate the latent property of "extraction difficulty" at near-zero cost. This document analyzes why this choice is theoretically sound and where its boundaries lie.

---

## 1. The Routing Problem — Formal Statement

> [!theory] Mechanics — Why Routing Exists
> Given a set of models $M = \{m_1, m_2, ..., m_n\}$ ordered by capability $C(m_i)$ and compute cost $K(m_i)$ such that $C(m_1) < C(m_2) < ... < C(m_n)$ and $K(m_1) < K(m_2) < ... < K(m_n)$, the routing problem is:
>
> **Find a function $r: Q \rightarrow M$ that minimizes $\mathbb{E}[K(r(q))]$ subject to $\Pr[\text{valid output} | r(q), q] \geq \theta$**
>
> where $Q$ is the query space, $K$ is compute cost, and $\theta$ is a minimum success-rate threshold.
>
> In other words: route each query to the cheapest model that can still handle it correctly with probability above $\theta$.

The notebook instantiates this problem with two models:

| Model | Parameters | Role | Theoretical Position |
|---|---|---|---|
| `qwen3:1.7b` | ~1.7 billion | Simple extraction | $m_1$ — low cost, constrained capability |
| `qwen3:8b` | ~8 billion | Complex extraction | $m_2$ — high cost, higher capability |

The routing function is `is_complex_request(query: str) -> bool` — a binary classifier that determines whether to invoke $m_1$ or $m_2$.

---

## 2. The `is_complex_request` Heuristic — Signal Theory

> [!theory] Mechanics — What the Heuristic Actually Measures
> The function does not measure "complexity" as a psychological construct. It measures **proxy signals that correlate with extraction difficulty** — specifically, the number and type of structured fields the model must extract and transform from the query. Each signal corresponds to a class of extraction task that places greater demand on the model's reasoning capability.

### Signal 1: Length as Information Density Proxy

```python
if len(query) > 120:
    return True
```

**Theoretical basis:** Query length is a proxy for **semantic density** — the number of distinct facts embedded in the input. A 120-character query can contain at most 3-4 discrete entities. A query exceeding this threshold is statistically more likely to contain multiple fields that must be extracted simultaneously (item name, quantity, location, delivery timeline, budget). The constant `120` is a calibration parameter — not derived analytically, but consistent with the empirical observation that short queries typically contain 1-2 fields while long queries contain 3+.

**Information-theoretic interpretation:** A longer query has higher entropy in the query space — more bits of information — which increases the probability that the extraction task requires multi-step reasoning rather than direct pattern matching.

### Signal 2: Numeric Count as Multi-Field Indicator

```python
if len(re.findall(r"\b\d+(?:\.\d+)?\b", query)) >= 2:
    return True
```

**Theoretical basis:** Structured Beckn fields that require numeric values are: `quantity`, `delivery_timeline`, `budget_constraints.max`, `budget_constraints.min`. Each numeric token in the query is a **candidate value for one of these fields**. Two or more numeric tokens strongly suggest that at least two distinct numeric fields must be extracted, disambiguated, and mapped to the correct schema field — a task that requires multi-step reasoning.

The regex `\b\d+(?:\.\d+)?\b` matches integers and decimals at word boundaries. It correctly counts `500` (quantity), `5` (days), and `2` (rupees per sheet) in `"500 units... within 5 days, budget under 2 rupees per sheet"` as three separate signals — all present in the example query that is routed to `qwen3:8b`.

**Why 2 as threshold?** One numeric value (e.g., `"500 units of cable"`) is a single-field extraction. Two or more implies the model must hold multiple extraction targets in working context simultaneously and avoid cross-field assignment errors (assigning the budget value to quantity, for instance).

### Signal 3: Delivery Keywords as Temporal Reasoning Indicator

```python
_DELIVERY_KEYWORDS = frozenset({
    "delivery", "deliver", "timeline", "deadline",
    "days", "weeks", "hours", "within",
})
if any(kw in lower for kw in _DELIVERY_KEYWORDS):
    return True
```

**Theoretical basis:** The `delivery_timeline` field requires **unit conversion and temporal reasoning**: `"5 days"` → `120` hours, `"2 weeks"` → `336` hours. This is not a simple extraction; it is a two-step operation:
1. Parse the temporal expression (identify the numeric value and the unit).
2. Apply the conversion rule (multiply by the unit's hour-equivalent).

Unit conversion is a class of task where smaller models are known to be less reliable — they may perform the extraction but fail on the arithmetic, or they may apply the wrong conversion factor. The presence of delivery keywords signals that this reasoning chain is required, justifying the upgrade to the larger model.

**`frozenset` as implementation choice:** `frozenset` provides $O(1)$ average-case membership testing via hash lookup, compared to $O(k)$ for a list scan. At the throughput scale of this system (thousands of requests), the difference is negligible for a set of ~8 keywords, but the choice signals intent: this is a **constant-time lookup**, not a linear scan.

### Signal 4: Budget Keywords as Numeric Range Indicator

```python
_BUDGET_KEYWORDS = frozenset({
    "budget", "price", "cost", "rupee", "rupees",
    "inr", "usd", "per unit", "per sheet", "per meter",
    "under", "maximum", "max",
})
if any(kw in lower for kw in _BUDGET_KEYWORDS):
    return True
```

**Theoretical basis:** The `BudgetConstraints` model requires extracting a **numeric range** with currency stripping. The extraction challenge is twofold:
1. Identifying whether the constraint is one-sided (`"under 2 rupees"` → `{min: 0, max: 2.0}`) or two-sided (`"between 1 and 3 rupees"` → `{min: 1.0, max: 3.0}`).
2. Stripping currency symbols and unit qualifiers (`"rupees per sheet"` → `2.0`) to produce a bare float.

The keywords `"under"` and `"maximum"` are particularly significant: they indicate an asymmetric constraint (upper bound only), requiring the model to infer the `min: 0.0` default — a reasoning step that goes beyond extraction into **constraint interpretation**.

---

## 3. Signal Ordering — The Computational Cost Ladder

> [!theory] Mechanics — Why the Order of Checks Matters
> The four signals are evaluated in ascending order of computational cost:

```
1. len(query) > 120          →  O(1) — string length is pre-computed
2. re.findall(...) >= 2      →  O(n) — single regex pass over query length n
3. keyword ∈ _DELIVERY_KWS   →  O(n · k₁) in worst case — n tokens, k₁ = 8 keywords
4. keyword ∈ _BUDGET_KWS     →  O(n · k₂) in worst case — n tokens, k₂ = 13 keywords
```

Short-circuit evaluation (`or` semantics via early `return True`) means the costlier checks are only reached if the cheaper ones fail. A long query triggers `return True` on the first check, never reaching the regex or keyword scans. This is **branch prediction via signal hierarchy**: route the common case (long, multi-numeric queries) at minimal cost.

In practice, at the scale of 10,000+ requests/month ([[user_adoption_metrics]]), this function is called for every Stage 2 extraction. The total overhead of routing decisions is $O(n \cdot R)$ where $R$ is the request rate and $n$ is average query length — a linear function that scales cheaply compared to the $O(n \cdot T^2)$ attention cost of the transformer inference it gates.

---

## 4. Heuristic Routing vs. LLM Router — Theoretical Comparison

> [!warning] Trade-offs — Determinism vs. Accuracy
> An alternative to the heuristic approach is an **LLM-based router**: a dedicated, lightweight model that reads the query and predicts whether the complex model is needed. This approach is used in production systems like [[llm_providers|Martian]], RouteLLM, and MixRerank. The theoretical comparison:

| Dimension | Heuristic Router (`is_complex_request`) | LLM Router |
|---|---|---|
| **Latency overhead** | ~microseconds (pure Python) | ~50–200ms (additional LLM inference call) |
| **Compute cost** | Zero — no model inference | Requires a dedicated routing model (even a 1B model costs tokens) |
| **Determinism** | Fully deterministic — same input always produces same routing decision | Stochastic — same input can produce different routing decisions across calls |
| **Accuracy** | Approximate — based on surface features, not semantic understanding | Higher — can understand query intent, not just surface signals |
| **Failure modes** | False negatives (complex query misclassified as simple → validation failure → escalation fallback) | Routing model hallucination, routing model failure adds a new failure point |
| **Maintainability** | Keyword lists and thresholds require manual tuning | Routing model requires training data and retraining |
| **Cold start** | Immediate — no model loading required | Requires routing model to be loaded in memory |

**Why the heuristic is theoretically justified here:**

The heuristic's failure mode is **recoverable**: when a complex query is misrouted to `qwen3:1.7b`, the `max_retries=3` loop provides a self-correction opportunity, and the escalation fallback (`except Exception → re-route to qwen3:8b`) ensures no query permanently fails due to routing error. The cost of a false negative is 3 retry calls to the small model before escalation — significant but bounded.

An LLM router adds latency to **every** request (including simple ones), which defeats the optimization goal. The heuristic adds zero latency overhead on the fast path (simple queries correctly routed to `qwen3:1.7b`) and bounded overhead on the slow path (complex queries routed to `qwen3:8b`).

> [!theory] Mechanics — The Asymmetry of Routing Errors
> False positive (simple query routed to complex model): cost is excess compute on `qwen3:8b`, result is still correct. **Cost: efficiency loss.**
>
> False negative (complex query routed to simple model): cost is retry overhead (up to 3× simple model calls) plus potential escalation to complex model. **Cost: latency spike + efficiency loss.**
>
> Both errors are recoverable. This is a **graceful degradation** architecture: the worst case is not a wrong answer, but a delayed correct answer. The system trades routing accuracy for routing cost.

---

## 5. The 1.7b vs. 8b Boundary — Parameter Count as Capability Proxy

> [!theory] Mechanics — Why Parameter Count Matters for Extraction
> Parameter count is a rough proxy for model capability, but it correlates with specific relevant properties for structured extraction tasks:
>
> 1. **Working memory (effective context utilization):** Larger models leverage more of the available context window when constructing their output. A 1.7B model may "forget" constraints stated in the system prompt when the query is long or complex. An 8B model is more likely to maintain constraint awareness throughout its generation.
>
> 2. **Instruction following precision:** Multi-step instructions (extract specs, convert units, strip currency, apply lookup) require the model to track multiple concurrent tasks. Instruction-following ability scales with parameter count in the 1B–10B range.
>
> 3. **Arithmetic reliability:** Unit conversion (`5 days × 24 = 120 hours`) is a basic arithmetic task, but 1–2B models are known to make arithmetic errors under distribution shift (e.g., large multipliers, multi-step calculations). 8B models are significantly more reliable.
>
> The 1.7B model is theoretically adequate for single-field extraction (item name, quantity, location without conversion) — exactly the query class the heuristic routes to it. The 8B model is invoked when multi-field, multi-step reasoning is required — exactly the query class the heuristic identifies.

This analysis reveals that `is_complex_request()` is not arbitrary: it is a **feature function that approximates the boundary between single-step and multi-step extraction tasks** — the exact capability boundary between the two model sizes.

---

## 6. The Escalation Fallback — Second-Order Routing Theory

> [!theory] Mechanics — Graceful Degradation as Routing Layer 2
> The `BecknIntentParser.parse()` method implements a two-tier routing policy:

```
Tier 1 (heuristic gate):
  is_complex_request(query) == False → invoke qwen3:1.7b
  is_complex_request(query) == True  → invoke qwen3:8b

Tier 2 (fallback on Tier 1 failure):
  qwen3:1.7b raises Exception after max_retries → invoke qwen3:8b
  qwen3:8b raises Exception after max_retries  → propagate to caller
```

This creates a **routing DAG**, not a routing decision tree: the path through the system is not determined solely by the initial routing decision but also by runtime outcomes. The system can self-correct its routing decision based on observed model behavior.

The theoretical implication is that `is_complex_request()` does not need to be perfectly accurate. Its role is to **reduce expected latency** (by routing most queries to the fast model) while the escalation fallback **maintains correctness** (by ensuring complex queries eventually reach the capable model). The two layers have different optimization objectives: the heuristic optimizes for latency; the fallback optimizes for correctness.

---

## 7. Connection to Production Architecture

The `is_complex_request()` pattern in this notebook directly informs the production [[llm_providers|model routing strategy]]:

| Dimension | Notebook (local) | Production (cloud) |
|---|---|---|
| Simple model | `qwen3:1.7b` | GPT-4o-mini |
| Complex model | `qwen3:8b` | GPT-4o |
| Routing signal | Length + numeric count + keyword presence | Same heuristic + token budget estimation |
| Escalation fallback | `qwen3:8b` after retry exhaustion | GPT-4o after GPT-4o-mini failure |
| Cost differential | ~5× (parameter count ratio) | ~10–20× (API pricing differential) |

The cost differential is larger in production (API pricing for GPT-4o vs. GPT-4o-mini is roughly 20× per token), making accurate routing even more critical. A 5% false-negative rate at 10,000 requests/month means ~500 requests unnecessarily billed at GPT-4o rates — a meaningful cost impact at enterprise scale. See [[business_impact_metrics]] for cost modeling.
