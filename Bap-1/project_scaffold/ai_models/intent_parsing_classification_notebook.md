---
tags: [ai-architecture, instructor, pydantic, beckn, nlp, llm-routing, structured-extraction, qwen3, ollama, local-llm]
cssclasses: [procurement-doc, ai-doc]
status: "#documented"
related: ["[[nl_intent_parser]]", "[[intent_parsing_model]]", "[[beckn_bap_client]]", "[[llm_providers]]", "[[agent_framework_langchain_langgraph]]", "[[model_governance_monitoring]]", "[[negotiation_engine]]"]
notebook: "Playground/intent_parsing_classification.ipynb"
---

# Intent Parsing & Classification — Notebook Architecture

> [!abstract] Architecture Summary
> This notebook implements a **two-stage, schema-validated NLP pipeline** for enterprise procurement intent extraction on the [[beckn_bap_client|Beckn Protocol]]. Stage 1 classifies free-form user queries into procurement intent categories (`ParsedIntent`). Stage 2 — activated only for procurement-relevant intents — extracts a fully structured, Beckn-compatible `BecknIntent` object. The pipeline is built on three interlocking mechanisms: **`instructor`** for guaranteed structured LLM output, **Pydantic v2** for schema enforcement with runtime validators, and a **heuristic complexity router** that dynamically selects between `qwen3:8b` and `qwen3:1.7b` to optimize compute allocation per request. The entire stack runs locally via [[llm_providers|Ollama]], with drop-in compatibility for OpenAI and Anthropic backends.

---

## 1. Core Technology Stack

### 1.1 `instructor` — Structured Output from LLMs

> [!tech-stack] How `instructor` Patches the OpenAI Client
> `instructor` wraps the standard OpenAI-compatible client (`instructor.from_openai(raw_client, mode=instructor.Mode.JSON)`) and injects three layers of behavior over the raw chat completion API:
>
> 1. **Schema injection:** The JSON Schema derived from the target Pydantic model is automatically appended to the prompt context, instructing the LLM to return a JSON object conforming to that schema.
> 2. **Response parsing:** The raw LLM string response is deserialized and passed to `model.model_validate()` (Pydantic v2 API).
> 3. **Automatic retry loop:** If `model_validate()` raises a `ValidationError`, `instructor` captures the error message and re-prompts the LLM with the validation failure as feedback — repeating up to `max_retries` times (default: 3).
>
> This eliminates all manual `json.loads()`, error handling, and re-prompt logic that would otherwise be written in application code. The calling interface is identical to the standard OpenAI `chat.completions.create()` — the only addition is the `response_model=` parameter.

```python
client = instructor.from_openai(raw_client, mode=instructor.Mode.JSON)

result = client.chat.completions.create(
    model=MODEL,
    messages=[...],
    response_model=ParsedIntent,   # ← the instructor-specific parameter
    max_retries=3,
)
# result is already a validated ParsedIntent instance — not a string
```

**Backend portability:** `instructor` supports `from_openai()`, `from_anthropic()`, and other adapters. The same `ParsedIntent` Pydantic model works unchanged across all backends — only the client initialization changes.

---

### 1.2 Pydantic v2 — Schema Enforcement at Runtime

> [!tech-stack] Pydantic v2 in This Context
> Pydantic v2 is the **contract layer** between the LLM's probabilistic output and the deterministic data structures the downstream [[beckn_bap_client|Beckn BAP client]] expects. Two Pydantic primitives are used:
>
> **`Field(description=...)`** — The description string is directly used by `instructor` when constructing the prompt schema. It is not documentation; it is a **runtime instruction to the LLM**. Precise, domain-specific field descriptions are the primary lever for improving extraction accuracy without fine-tuning.
>
> **`@field_validator`** — Runs after type coercion. Used here to enforce range constraints that Pydantic's type system alone cannot express. A `ValueError` raised inside a validator is intercepted by `instructor` and used as feedback for the next retry attempt.

#### `ParsedIntent` Schema

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

**Design decision — open `str` vs. `Literal[...]` for `intent`:** Using `str` instead of a fixed enum allows the LLM to synthesize intent names not anticipated at design time (e.g., `"Greeting"`, `"CancelOrder"`). This is a deliberate trade-off: higher recall at the cost of requiring the downstream routing logic (`_PROCUREMENT_INTENTS` set membership check) to filter for procurement-relevant intents.

#### `BecknIntent` + `BudgetConstraints` Schema

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

### 1.3 Beckn Protocol — Why Structured Procurement Fields Are Non-Negotiable

> [!info] Beckn Protocol Context
> The **Beckn Protocol** is a decentralized, open-specification commerce network designed so that any buyer application (BAP) can discover and transact with any seller application (BPP) without a central marketplace intermediary. Message exchange happens via standardized JSON payloads sent to protocol endpoints (`discover`, `publish`, `select`, `init`, `confirm`, `status`) — see [[beckn_bap_client]].
>
> The `discover` query requires structured, typed fields:
> - **`location`** as a `GPS` object (`lat,lon` string) — free-text city names are not valid. The `resolve_location()` function and the `apply_location_lookup` validator handle this transformation deterministically before the payload is constructed.
> - **`delivery_timeline`** as a numeric duration in hours — the protocol does not accept relative strings like "5 days". The system prompt instructs the LLM with the conversion rules: `1 day = 24h`, `1 week = 168h`.
> - **`budget_constraints`** as a numeric range with `min` and `max` — currency symbols are stripped by the extraction prompt; only float values are valid in the schema.
>
> Without `BecknIntent` enforcing these constraints at extraction time, every downstream [[beckn_bap_client|BAP client]] call would require defensive transformation code. The Pydantic schema acts as an **anti-corruption layer** at the LLM output boundary, ensuring the [[nl_intent_parser|NL Intent Parser]] component produces Beckn-ready data directly.

---

## 2. Pipeline Architecture

```
User Query (natural language)
        │
        ▼
┌───────────────────────────────────────┐
│  Stage 1: IntentClassifier            │
│  Model: qwen3:8b (fixed)              │
│  Output: ParsedIntent                 │
│  - intent (open PascalCase str)       │
│  - product_name, quantity             │
│  - confidence [0.0, 1.0]             │
│  - reasoning                          │
└───────────────────────────────────────┘
        │
        ▼ intent ∈ {"SearchProduct","RequestQuote","PurchaseOrder"}?
        │
    ┌───┴──────┐
    │ NO       │ YES
    │          ▼
    │  ┌────────────────────────────────────────────┐
    │  │  is_complex_request(query) heuristic       │
    │  │  ┌─ len > 120  → complex                  │
    │  │  ├─ ≥ 2 numerics → complex               │
    │  │  ├─ delivery keywords → complex           │
    │  │  └─ budget keywords → complex             │
    │  └────────────────────────────────────────────┘
    │          │
    │    complex?──┬──No──► qwen3:1.7b
    │              └──Yes─► qwen3:8b
    │          │
    │          ▼
    │  ┌───────────────────────────────────────────┐
    │  │  Stage 2: BecknIntentParser               │
    │  │  Output: BecknIntent                      │
    │  │  - item, descriptions, quantity           │
    │  │  - location_coordinates (lat,lon)         │
    │  │  - delivery_timeline (hours)              │
    │  │  - budget_constraints {min, max}          │
    │  └───────────────────────────────────────────┘
    │          │
    ▼          ▼
{"intent": ..., "beckn_intent": None}   {"intent": ..., "beckn_intent": {...}, "routed_to": ...}
```

### 2.1 Stage 1 — `IntentClassifier` (ParsedIntent)

The first stage operates as a **domain gatekeeper**. Its only purpose is to classify the query's intent category and extract shallow signals (product name, quantity, confidence). The intent vocabulary is intentionally open-ended — the LLM synthesizes names in PascalCase without a fixed `Literal` constraint. This handles edge cases like `"Greeting"` or `"CancelOrder"` that a closed enum would misclassify.

The output is evaluated against `_PROCUREMENT_INTENTS = {"SearchProduct", "RequestQuote", "PurchaseOrder"}`. Non-procurement intents (greetings, tracking queries, cancellations) short-circuit the pipeline and return `beckn_intent: null` — Stage 2 is never invoked. This prevents wasteful compute on queries that would produce incomplete or nonsensical Beckn payloads.

**System prompt strategy:** The classifier receives domain context (industrial products, RFQ workflows, Beckn network) rather than intent label definitions. This lets the LLM apply contextual reasoning about what constitutes a procurement intent in this specific domain.

---

### 2.2 Stage 2 — `BecknIntentParser` (BecknIntent)

Stage 2 performs **deep structured extraction** of Beckn-protocol-compatible fields. Unlike Stage 1, this extraction is not about classification — it is about transforming unstructured natural language into a machine-actionable JSON payload ready for the [[beckn_bap_client|BAP `discover` query]].

Key extraction challenges handled by schema + system prompt engineering:

| Challenge | Mechanism |
|---|---|
| Technical spec decomposition | `descriptions: list[str]` — LLM decomposes "A4 80gsm" into `["A4", "80gsm"]` |
| Location normalization | `apply_location_lookup` validator + inline lookup table in system prompt |
| Time unit normalization | System prompt rule: `1 day = 24h`, `1 week = 168h` → `delivery_timeline: int` |
| Budget extraction | `BudgetConstraints` nested model; one-sided budget ("under 2 rupees") → `{min: 0, max: 2.0}` |
| Currency stripping | System prompt rule: "Use only numeric values, no currency symbols" |

---

## 3. Heuristic Routing — `is_complex_request`

> [!important] Heuristic Routing Logic
> The `is_complex_request(query: str) -> bool` function is the **compute allocation policy** of the pipeline. It determines which model variant handles Stage 2 extraction: the resource-intensive `qwen3:8b` for complex queries, or the lightweight `qwen3:1.7b` for simple ones. This is a critical production optimization — at 10,000+ requests/month ([[user_adoption_metrics]]), the latency and compute differential between these two model sizes becomes significant.
>
> ```python
> def is_complex_request(query: str) -> bool:
>     # Signal 1: Length proxy for information density
>     if len(query) > 120:
>         return True
>     # Signal 2: Multiple numeric values → multiple fields to extract
>     if len(re.findall(r"\b\d+(?:\.\d+)?\b", query)) >= 2:
>         return True
>     # Signal 3: Delivery timeline present → temporal reasoning required
>     lower = query.lower()
>     if any(kw in lower for kw in _DELIVERY_KEYWORDS):
>         return True
>     # Signal 4: Budget constraint present → numeric range extraction required
>     if any(kw in lower for kw in _BUDGET_KEYWORDS):
>         return True
>     return False
> ```
>
> The four signals are **ordered by computational cost** (cheapest check first):
> - `len(query) > 120` — `O(1)`, catches verbosity-as-complexity.
> - `re.findall(r"\b\d+(?:\.\d+)?\b", ...) >= 2` — `O(n)` regex, catches multi-field numeric queries.
> - Keyword set membership — `O(k)` where `k` = keyword count, catches delivery and budget signals explicitly.
>
> **Fallback escalation:** If the simple model (`qwen3:1.7b`) fails validation after `max_retries=3` attempts, `BecknIntentParser.parse()` catches the exception and re-routes the query to `qwen3:8b` automatically — a graceful degradation path that prevents `ValidationError` from propagating to the caller.

### Keyword Signal Sets

```python
_DELIVERY_KEYWORDS = frozenset({
    "delivery", "deliver", "timeline", "deadline",
    "days", "weeks", "hours", "within",
})

_BUDGET_KEYWORDS = frozenset({
    "budget", "price", "cost", "rupee", "rupees",
    "inr", "usd", "per unit", "per sheet", "per meter",
    "under", "maximum", "max",
})
```

`frozenset` is used for `O(1)` average-case membership testing — relevant when this function is called on every Stage 2 request in a high-throughput batch.

---

## 4. Retry Mechanism — `instructor`'s Validation Feedback Loop

> [!guardrail] Automatic Retry on Validation Failure
> When the LLM produces output that fails Pydantic validation (e.g., `confidence=1.5`, `delivery_timeline=-1`, malformed JSON), `instructor` executes the following retry loop:
>
> 1. Capture the `ValidationError` exception from Pydantic.
> 2. Serialize the error detail (field name, value, error message).
> 3. Append the error as an **assistant/user message pair** to the conversation: the assistant "said" the invalid JSON, the user replies with the validation error message.
> 4. Call the LLM again with this extended context — the model sees its own mistake and the correction requirement.
> 5. Repeat up to `max_retries` (default: 3).
>
> This is **closed-loop error correction without application code**. The mechanism is equivalent to a human prompt engineer manually re-prompting with "Your previous answer was invalid because: [error]" — automated and transparent.
>
> ```python
> # instructor handles this internally — from the caller's perspective:
> result = client.chat.completions.create(
>     model=model,
>     messages=messages,
>     response_model=BecknIntent,
>     max_retries=3,  # ← retry budget
> )
> # If all 3 retries fail, instructor raises InstructorRetryException
> ```
>
> The `@field_validator` on `confidence` and `delivery_timeline` are **intentional retry triggers** — they enforce business constraints that the LLM cannot reliably satisfy without feedback.

---

## 5. Batch Processing — `ThreadPoolExecutor`

For high-volume classification, the notebook exposes `classify_batch()`:

```python
def classify_batch(queries: list[str], max_workers: int = 4) -> pd.DataFrame:
    results = {}
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(classifier.classify, q): q for q in queries}
        for future in as_completed(futures):
            query = futures[future]
            try:
                r = future.result()
                results[query] = {
                    "intent": r.intent,
                    "product_name": r.product_name,
                    "quantity": r.quantity,
                    "confidence": r.confidence,
                    "reasoning": r.reasoning,
                    "error": None,
                }
            except Exception as e:
                results[query] = {"intent": None, "error": str(e)}
    return pd.DataFrame.from_dict(results, orient="index")
```

**Concurrency model:** Each LLM call is I/O-bound (HTTP request to local Ollama server). `ThreadPoolExecutor` with `max_workers=4` allows up to 4 concurrent requests. The GIL is not a bottleneck here because threads release it during I/O waits. For CPU-bound workloads (e.g., heavy Pydantic validation on large schemas), `ProcessPoolExecutor` would be preferred.

**Error isolation:** Each `future.result()` call is wrapped in `try/except` — a single failed classification (e.g., instructor exhausting all retries) does not abort the batch. The error is recorded in the `"error"` column of the resulting DataFrame.

> [!insight] Production Scaling Consideration
> At the [[user_adoption_metrics|10,000 requests/month]] target, `ThreadPoolExecutor` with 4 workers processes queries in batches. The actual throughput depends on `qwen3:8b`'s tokens/second on the local hardware. For production scale, this batch processor would be replaced by an async queue (e.g., `asyncio` + `aiohttp` matching the pattern in [[beckn_client|the Beckn async client]]) or a dedicated inference server (vLLM, Triton) with async HTTP.

---

## 6. Multi-Backend Support

The `instructor` abstraction makes backend swapping trivial. The same `ParsedIntent` and `BecknIntent` schemas work unchanged across all providers:

| Backend | Client Initialization |
|---|---|
| Ollama (local, `qwen3`) | `instructor.from_openai(OpenAI(base_url="http://localhost:11434/v1", api_key="ollama"))` |
| OpenAI (cloud) | `instructor.from_openai(OpenAI(api_key="sk-..."))` |
| Anthropic (cloud) | `instructor.from_anthropic(anthropic.Anthropic(api_key="sk-ant-..."))` |

For the Anthropic backend, note that `instructor` uses `messages.create()` (the Anthropic SDK method) instead of `chat.completions.create()` — this is handled transparently by the `from_anthropic()` adapter. The `response_model=` parameter and retry logic behave identically.

**Relevance to production deployment:** The [[llm_providers|multi-provider LLM strategy]] (GPT-4o primary, Claude Sonnet 4.6 fallback) mirrors this notebook's multi-backend design. The `instructor` client swap pattern demonstrated here is the same mechanism used for production failover — no application logic changes when the backend changes.

---

## 7. Location Resolution — Deterministic Pre-Processing

```python
_CITY_COORDINATES: dict[str, str] = {
    "bangalore":  "12.9716,77.5946",
    "bengaluru":  "12.9716,77.5946",
    "mumbai":     "19.0760,72.8777",
    "delhi":      "28.7041,77.1025",
    "new delhi":  "28.6139,77.2090",
    "chennai":    "13.0827,80.2707",
    "hyderabad":  "17.3850,78.4867",
    "pune":       "18.5204,73.8567",
    "kolkata":    "22.5726,88.3639",
}

def resolve_location(text: str) -> str:
    normalized = text.strip().lower()
    for city, coords in _CITY_COORDINATES.items():
        if city in normalized:
            return coords
    return text  # passthrough for unknown locations
```

This function is called inside the `@field_validator("location_coordinates")` — meaning it runs **after** the LLM has produced its location string, but **before** the field value is finalized. This is a **hybrid resolution strategy**: the LLM is instructed via system prompt to attempt coordinate resolution, and the validator ensures correctness deterministically for known Indian cities. Unknown locations pass through as raw strings — a deliberate fallback that avoids hard failures for edge cases.

> [!guardrail] Reliability Constraint
> The lookup table is the **authoritative source** for supported Indian cities. If the LLM hallucinates coordinates (e.g., `"12.97, 77.59"` with a space), the substring match `if city in normalized` still fires because the city name itself appears in the query text — the validator normalizes the LLM's output regardless. For cities not in the table, the raw LLM output passes through — the [[beckn_bap_client|BAP client]] will reject a malformed location at the protocol validation layer, surfacing the issue explicitly.

---

## 8. Design Patterns & Architectural Decisions

| Pattern | Implementation | Rationale |
|---|---|---|
| Open intent vocabulary | `intent: str` (not `Literal`) | Handles unanticipated intents without redeployment |
| Two-stage pipeline | `IntentClassifier` → `BecknIntentParser` | Separation of concerns; avoids extracting Beckn fields for non-procurement queries |
| Heuristic model routing | `is_complex_request()` | Compute cost optimization; routes lightweight queries to smaller model |
| Schema-as-prompt | `Field(description=...)` | Instructions embedded in schema; no separate prompt engineering file |
| Validator-as-guardrail | `@field_validator` | Runtime constraint enforcement; triggers instructor retry loop |
| Deterministic post-processing | `resolve_location()` in validator | Removes LLM uncertainty from location coordinates |
| Batch isolation | `try/except` per future | Single query failures don't abort batch |
| Backend portability | `instructor.from_*()` adapters | Same schemas work across Ollama, OpenAI, Anthropic |

---

## 9. Comparison: Base Implementation vs. This Notebook

| Aspect | Base Implementation | This Notebook |
|---|---|---|
| JSON parsing | `json.loads()` manual | `instructor` automatic |
| Validation | Basic Pydantic types | + `@field_validator` (range, positivity) |
| Retry on failure | None — exception propagates | Automated feedback loop (up to `max_retries`) |
| Intent vocabulary | `Literal[...]` fixed enum | `str` open-ended — LLM synthesizes names |
| Extracted fields | 3 (`intent`, `product`, `confidence`) | 5 + nested (`+ quantity`, `reasoning`) + `BecknIntent` (6 fields) |
| Domain specificity | Generic classification | Beckn Protocol-aligned extraction |
| Model selection | Single model (fixed) | Heuristic router (complexity → model size) |
| Batch processing | Sequential | `ThreadPoolExecutor` parallel |
| Backend support | Ollama only | Ollama, OpenAI, Anthropic |

---

## 10. Relationship to Production Architecture

This notebook is the **experimental prototype** for the [[nl_intent_parser]] component in the production system. The production component diverges in the following ways:

- **Model provider:** Production uses [[llm_providers|GPT-4o (primary) + Claude Sonnet 4.6 (fallback)]] via enterprise API agreements, not local Ollama.
- **Schema:** The production `BecknIntent` JSON feeds directly into the [[beckn_bap_client|BAP Client's `discover` query builder]] — this notebook demonstrates the transformation logic that production codifies.
- **Observability:** Production wraps every LLM call with [[observability_stack|LangSmith tracing]]; this notebook lacks tracing instrumentation.
- **Batch processing:** Production uses async `aiohttp` queues rather than `ThreadPoolExecutor` for compatibility with the [[beckn_client|async Beckn HTTP client]].
- **Governance:** Model versions and prompt templates are tracked in the [[model_governance_monitoring|Model Registry]]; this notebook has `MODEL = "qwen3:8b"` hardcoded.

The `is_complex_request()` routing heuristic from this notebook directly informs the [[llm_providers|production model routing logic]] (GPT-4o-mini for simple requests, GPT-4o for complex ones) — replacing model size with model generation as the routing dimension.
