---
tags: [theory, architecture, nlp, structured-output, pydantic, instructor, llm, constrained-generation, self-correction]
cssclasses: [procurement-doc, theory-doc]
status: "#theory"
related: ["[[intent_parsing_model]]", "[[nl_intent_parser]]", "[[agent_framework_langchain_langgraph]]", "[[llm_providers]]", "[[heuristic_routing_theory]]", "[[beckn_data_theory]]"]
---

# Schema-Driven LLM Output — Theory of Constrained Generation

#theory #architecture #nlp #structured-output

> [!abstract] Rationale
> A Large Language Model is, by construction, a probabilistic function over a vocabulary. Left unconstrained, it samples from this distribution freely — producing prose, code, JSON, or hallucinated nonsense with equal facility. The engineering problem is not capability; it is **determinism at the output boundary**. This document explains the theoretical mechanisms by which `instructor` + Pydantic v2 collapses the LLM's unconstrained generation space into a verified, typed object — and how the system self-corrects when that collapse fails.

---

## 1. The Generation Space Problem

> [!theory] Mechanics — What an LLM Actually Produces
> At inference time, a transformer-based language model computes a probability distribution $P(t | t_{1..n})$ over the vocabulary $V$ at each step, where $t_{1..n}$ is the token history. The model samples from this distribution to emit the next token $t_{n+1}$, repeating until an end-of-sequence token is emitted.
>
> This means the model's raw output is a **sequence of tokens** — not a Python object, not a dictionary, not a validated record. It is a string. For most application code that must act on this output, a raw string is useless: you cannot call `.item` on a string, you cannot do range-checks on a string, and you cannot guarantee the string is even valid JSON.
>
> The naive solution — `json.loads(response.content)` — fails silently in at least three ways:
> 1. The model emits syntactically invalid JSON (trailing commas, missing quotes, markdown fences).
> 2. The model emits valid JSON that does not match the expected schema (wrong field names, wrong types).
> 3. The model emits valid, schema-conformant JSON but with semantically invalid values (e.g. `confidence: 1.7`).
>
> Each of these failure modes requires a distinct error handler, a re-prompt strategy, and retry logic. Without a framework, this becomes application-layer boilerplate that duplicates across every extraction use case.

The core claim of schema-driven extraction is that this boilerplate should be **structural**, not ad hoc. The schema is the specification; the framework enforces it.

---

## 2. How `instructor` Patches the Client — The Constrained Generation Wrapper

> [!theory] Mechanics — The Three-Layer Injection
> `instructor.from_openai(raw_client, mode=instructor.Mode.JSON)` does not replace the OpenAI client. It **wraps** it using the Decorator pattern, intercepting two moments in the request lifecycle: before the API call (schema injection) and after it (response parsing and validation).

### Layer 1: Schema Injection (Pre-Call)

When `response_model=ParsedIntent` is passed to `client.chat.completions.create()`, `instructor` introspects the Pydantic model class at runtime and calls `ParsedIntent.model_json_schema()`. This produces the JSON Schema object conforming to [JSON Schema Draft 2020-12](https://json-schema.org/):

```json
{
  "title": "ParsedIntent",
  "type": "object",
  "properties": {
    "intent":        { "type": "string",  "description": "Intención principal detectada..." },
    "product_name":  { "type": ["string", "null"], "description": "Nombre del producto..." },
    "quantity":      { "type": ["integer", "null"], "description": "Cantidad solicitada..." },
    "confidence":    { "type": "number",  "description": "Nivel de confianza [0.0, 1.0]..." },
    "reasoning":     { "type": "string",  "description": "Breve explicación..." }
  },
  "required": ["intent", "confidence", "reasoning"]
}
```

This schema is serialized and appended to the request — in `JSON` mode, instructor instructs the model to return a JSON object matching this schema exactly. The schema is not documentation for a human reader; **it is a runtime instruction to the generative model**. The `description` strings inside each `Field(description=...)` are surfaced verbatim in this schema, meaning every description string is prompt engineering embedded in the type system.

> [!warning] Trade-offs — Field Description as Implicit Prompt
> Because `Field(description=...)` becomes part of the LLM's context window at inference time, the quality of extraction is directly proportional to the precision of these strings. A vague description like `"the intent"` produces ambiguous outputs. A domain-specific description like `"Intención principal detectada. Usa PascalCase y sé específico, ej. 'SearchProduct', 'RequestQuote'. Si no encaja, inventa un nombre descriptivo."` acts as a few-shot example and a format constraint simultaneously — without increasing prompt length proportionally. This is the **schema-as-prompt** design pattern.

### Layer 2: Response Parsing (Post-Call)

After the LLM emits its JSON string, `instructor` passes it to `ParsedIntent.model_validate_json(raw_string)` (Pydantic v2 API). This call performs:
1. JSON deserialization (via Pydantic's Rust-backed parser in v2).
2. Type coercion (e.g., `"0.95"` → `float(0.95)`).
3. Field presence validation (required fields must exist).
4. `@field_validator` execution (custom business-rule constraints).

If all four steps succeed, `instructor` returns a fully typed `ParsedIntent` instance to the caller — never a `dict`, never a `str`.

### Layer 3: The Self-Correction Loop (Retry on ValidationError)

If Pydantic raises a `ValidationError` at any step, `instructor` intercepts the exception and executes its retry protocol. This is the mechanism that distinguishes `instructor` from a simple `json.loads()` wrapper.

---

## 3. The Self-Correction Loop — Mechanics of Automated Feedback

> [!theory] Mechanics — Closed-Loop Error Correction
> The retry mechanism is not a blind re-call. It is a **structured conversation extension**: the model is shown its own previous (invalid) output and the machine-generated error message, then asked to try again. This exploits the model's in-context learning capability to correct itself.

### Protocol of a Single Retry Iteration

```
Turn 1 (initial request):
  System:    [domain context + schema instruction]
  User:      "I need 500 units of A4 paper..."
  
LLM Response (invalid):
  Assistant: {"intent": "RequestQuote", "confidence": 1.7, ...}

Validation: Pydantic raises ValidationError:
  "confidence: value is not a valid float in range [0.0, 1.0]"
  
Turn 2 (instructor-injected retry):
  System:    [domain context + schema instruction]
  User:      "I need 500 units of A4 paper..."
  Assistant: {"intent": "RequestQuote", "confidence": 1.7, ...}   ← injected
  User:      "Validation failed: confidence must be in [0, 1], got: 1.7. Fix the errors." ← injected
  
LLM Response (corrected):
  Assistant: {"intent": "RequestQuote", "confidence": 0.95, ...}
```

The conversation is extended in-place. The model sees its previous invalid output as part of the message history, which provides the gradient of correction without requiring any weight updates. This is **few-shot self-correction** mediated by the validation framework.

> [!warning] Trade-offs — Retry Cost
> Each retry is a full LLM inference call. With `max_retries=3`, a single extraction can cost up to 4× the compute of a successful first-pass call. In practice, well-designed field descriptions and system prompts reduce retry frequency to near-zero for common query patterns, reserving retries for edge cases. The retry budget is therefore a **tail-cost insurance mechanism**, not an expected path.

### Maximum Retry Exhaustion

If all `max_retries` attempts fail, `instructor` raises `InstructorRetryException`. In the `BecknIntentParser`, this is the trigger for the **model escalation fallback**: the simple model (`qwen3:1.7b`) is abandoned and the complex model (`qwen3:8b`) is called instead. This creates a two-tier self-correction: first intra-model (retry), then inter-model (escalation).

```python
try:
    result = client.chat.completions.create(model=simple_model, ...)
    # SUCCESS → return result
except Exception:
    if model != self.complex_model:
        # ESCALATE → retry with complex model
        result = client.chat.completions.create(model=self.complex_model, ...)
        return result
    raise  # both tiers exhausted → propagate to caller
```

---

## 4. Pydantic as Validation Boundary — The Mathematical Constraint Model

> [!theory] Mechanics — What `@field_validator` Actually Enforces
> Pydantic's type system is isomorphic to a subset of type theory: `str`, `int`, `float`, `Optional[X]` correspond to standard type constructors. But type constraints are **necessary, not sufficient** for domain correctness. The type `float` admits all IEEE 754 doubles — including `NaN`, `Inf`, and values outside any meaningful business range.
>
> `@field_validator` is the mechanism to express **semantic constraints** that lie outside the type system: constraints derived from domain knowledge rather than from structural type properties.

### The `confidence` Constraint — Formal Analysis

```python
@field_validator("confidence")
@classmethod
def confidence_in_range(cls, v: float) -> float:
    if not 0.0 <= v <= 1.0:
        raise ValueError(f"confidence debe estar entre 0 y 1, recibido: {v}")
    return round(v, 2)
```

This validator enforces the closed interval $[0.0, 1.0]$ — mathematically, it checks that $v \in \mathbb{R}$ satisfies $0 \leq v \leq 1$. The type system guarantees $v \in \mathbb{R}$ (float); the validator adds the interval constraint. Together, they define a **bounded real interval** as the valid domain for `confidence`.

The `round(v, 2)` normalization is a secondary concern: it prevents floating-point precision noise (e.g., `0.9500000000000001`) from propagating downstream and creating inequality bugs in comparison logic.

**Why does this matter for the LLM?** Confidence is a probability-like scalar that the model synthesizes, not reads from the input. The model may output `confidence: 95` (interpreting the field as a percentage) rather than `confidence: 0.95`. The validator catches this (95 > 1.0) and triggers a retry, where `instructor`'s feedback message clarifies the expected range. The validator is the **formal specification** of the contract; the retry loop is the enforcement mechanism.

### The `delivery_timeline` Constraint

```python
@field_validator("delivery_timeline")
@classmethod
def timeline_positive(cls, v: int) -> int:
    if v <= 0:
        raise ValueError(f"delivery_timeline must be > 0, got {v}")
    return v
```

This enforces $v \in \mathbb{Z}^+$ (positive integers only). The type `int` already excludes non-integers; the validator adds the positivity constraint. A zero or negative delivery timeline is semantically nonsensical — it would indicate instantaneous or time-reversed delivery — and must be rejected before it reaches the Beckn protocol layer where it would cause a silent semantic error rather than an explicit validation failure.

### The `location_coordinates` Validator — Deterministic Side Effect

```python
@field_validator("location_coordinates")
@classmethod
def apply_location_lookup(cls, v: str) -> str:
    return resolve_location(v)
```

This validator has a different character: it does not check a constraint; it **transforms the value**. The field validator is used here as a hook for deterministic post-processing — the `resolve_location()` function applies a lookup table that converts city names to `"lat,lon"` strings. This is the [[beckn_data_theory|anti-corruption layer]] at the type boundary: the LLM's probabilistic location interpretation (which may be a city name, a partial address, or coordinates with formatting noise) is corrected to a canonical form before the value is finalized.

> [!warning] Trade-offs — Validator Side Effects
> Using `@field_validator` for transformations (rather than pure validation) couples domain logic to the schema definition. If `resolve_location()` changes its API, the validator breaks silently at runtime. A cleaner separation would place transformation logic in the calling code and reserve validators for pure constraint enforcement. The current design trades architectural cleanliness for conciseness — acceptable in a prototype, worth revisiting at production scale.

---

## 5. The `instructor.Mode.JSON` Constraint — Generation Mode Theory

> [!theory] Mechanics — JSON Mode vs. Tool-Call Mode
> `instructor` supports multiple generation modes: `JSON`, `TOOLS`, `MD_JSON`, and others. The mode determines **how the schema constraint is communicated to the model**.
>
> - **`JSON` mode**: The schema is injected into the system prompt as text instructions. The model is told to return a JSON object. The LLM's generation space is the full vocabulary, but the prompt creates strong contextual pressure toward valid JSON.
> - **`TOOLS` mode**: The schema is passed as an OpenAI Function/Tool definition. The model's generation is structurally guided by the API to produce a function call argument object — the generation space is more tightly constrained at the API level, not just via prompt.
>
> The notebook uses `JSON` mode because the Ollama-served `qwen3` models are accessed via an OpenAI-compatible endpoint that may not fully support the Tool Calling API. `JSON` mode is the most portable: it works with any model that can follow instruction-tuned prompts.

The theoretical implication is that `JSON` mode relies on **instruction following** (a learned capability) rather than **structural API enforcement** (a protocol-level guarantee). This means the constraint is softer — the model can still emit non-JSON if it decides to — but in practice, instruction-tuned models with good system prompts honor JSON mode reliably enough that the retry loop handles the residual failures.

---

## 6. The Open Vocabulary Trade-Off — `str` vs. `Literal[...]`

> [!theory] Mechanics — Type Constraint as Enumeration Boundary
> The `intent` field uses `str` rather than `Literal["SearchProduct", "RequestQuote", "PurchaseOrder", ...]`. This is a deliberate relaxation of the type constraint that trades **enumeration safety** for **generalization capability**.

| Approach | Type | LLM Behavior | Downstream Effect |
|---|---|---|---|
| Closed enum | `Literal["SearchProduct", "RequestQuote", "PurchaseOrder"]` | Model forced to pick from list; unknown intents get misclassified | Routing logic is fully deterministic; schema changes require code deploy |
| Open vocabulary | `str` | Model synthesizes descriptive names: `"CancelOrder"`, `"Greet"`, `"TrackOrder"` | Routing logic filters by set membership; unknown intents return `beckn_intent: null` gracefully |

The `_PROCUREMENT_INTENTS = {"SearchProduct", "RequestQuote", "PurchaseOrder"}` set in `parse_procurement_request()` acts as the **post-hoc enumeration boundary**. Instead of constraining the generation space at the schema level (which would force misclassifications), the system allows free generation and applies the filter after the fact. This is the **liberal input, conservative routing** pattern: accept any reasonable output from the model, act only on outputs that meet the routing criterion.

The cost of this approach is that the routing filter must be maintained separately from the schema — a two-point coupling that a `Literal` constraint would unify. It is the right trade-off when the intent vocabulary is expected to grow (new intents like `"BulkDiscount"` or `"FrameworkAgreement"` can be added to `_PROCUREMENT_INTENTS` without modifying the Pydantic schema).

---

## 7. Architectural Position in the Procurement System

```
User Query (str)
      │
      ▼
┌─────────────────────────────┐
│  instructor (wrapper)        │
│  ┌─────────────────────────┐│
│  │ Schema Injection (pre)  ││ ← Field(description=...) → JSON Schema → Prompt
│  └─────────────────────────┘│
│  ┌─────────────────────────┐│
│  │ LLM Inference           ││ ← qwen3:8b or qwen3:1.7b (see [[heuristic_routing_theory]])
│  └─────────────────────────┘│
│  ┌─────────────────────────┐│
│  │ Pydantic Validation     ││ ← type coercion + @field_validator
│  └─────────────────────────┘│
│  ┌─────────────────────────┐│
│  │ Retry Loop (on failure) ││ ← inject ValidationError → re-prompt → up to max_retries
│  └─────────────────────────┘│
└─────────────────────────────┘
      │
      ▼
ParsedIntent / BecknIntent (typed Python object)
      │
      ▼
[[beckn_bap_client]] /discover query builder
```

The schema-driven extraction layer is the **anti-corruption boundary** between the probabilistic world of the LLM and the deterministic world of the [[beckn_data_theory|Beckn Protocol]]. Everything downstream of `instructor` assumes it is operating on valid, typed data — no defensive null-checks, no format validation, no re-parsing.

> [!warning] Trade-offs — Coupling to Pydantic v2 API
> The entire mechanism depends on `model_validate_json()` and `model_json_schema()` being stable Pydantic v2 APIs. A migration to Pydantic v3 (when/if released) or a switch to `msgspec` / `attrs` would require rebuilding the schema-injection and retry logic. The `instructor` library abstracts this to some degree, but the underlying dependency is real. In a production system, pin `pydantic>=2.0,<3.0` explicitly.
