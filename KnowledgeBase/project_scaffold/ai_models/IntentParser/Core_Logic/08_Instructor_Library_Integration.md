---
tags: [intent-parser, instructor, structured-output, llm, pydantic, retry, backend-portability]
cssclasses: [procurement-doc, ai-doc]
status: "#approved"
related: ["[[09_Pydantic_v2_Schema_Enforcement]]", "[[12_Retry_Mechanism_Validation_Feedback_Loop]]", "[[15_Multi_Backend_Support]]", "[[05_ParsedIntent_Schema]]", "[[06_BecknIntent_Schema]]"]
---

# `instructor` — Structured Output from LLMs

> [!tech-stack] How `instructor` Patches the OpenAI Client
> `instructor` wraps the standard OpenAI-compatible client (`instructor.from_openai(raw_client, mode=instructor.Mode.JSON)`) and injects **three layers of behavior** over the raw chat completion API:
>
> 1. **Schema injection:** The JSON Schema derived from the target Pydantic model is automatically appended to the prompt context, instructing the LLM to return a JSON object conforming to that schema.
> 2. **Response parsing:** The raw LLM string response is deserialized and passed to `model.model_validate()` (Pydantic v2 API).
> 3. **Automatic retry loop:** If `model_validate()` raises a `ValidationError`, `instructor` captures the error message and re-prompts the LLM with the validation failure as feedback — repeating up to `max_retries` times (default: 3).
>
> This eliminates all manual `json.loads()`, error handling, and re-prompt logic that would otherwise be written in application code. The calling interface is identical to the standard OpenAI `chat.completions.create()` — the only addition is the `response_model=` parameter.

---

## Usage Pattern

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

The caller receives a fully validated `ParsedIntent` (or `BecknIntent`) Pydantic instance directly. There is no raw string to parse, no `json.loads()` call, no try/except for malformed JSON at the application layer.

---

## The Three Layers in Detail

### Layer 1 — Schema Injection

`instructor` extracts the JSON Schema from the Pydantic model and appends it to the system prompt context. For `ParsedIntent`, this adds something like:

```json
{
  "type": "object",
  "properties": {
    "intent": {"type": "string", "description": "..."},
    "product_name": {"type": "string", "description": "..."},
    "confidence": {"type": "number", "description": "..."},
    ...
  },
  "required": ["intent", "confidence", "reasoning"]
}
```

The `Field(description=...)` text on each field (see [[09_Pydantic_v2_Schema_Enforcement]]) populates the `"description"` keys — making each description a **runtime instruction to the LLM**, not just documentation.

### Layer 2 — Response Parsing

After the LLM produces a JSON string, `instructor` calls `model.model_validate(json_dict)`. Pydantic v2's `model_validate()` applies all field type coercions and runs all `@field_validator` functions. If this succeeds, the validated model instance is returned to the caller.

### Layer 3 — Automatic Retry Loop

If `model_validate()` raises a `ValidationError`, `instructor` does NOT raise the exception to the caller. Instead, it:

1. Captures the `ValidationError` detail (field name, value, error message)
2. Appends an **assistant/user message pair** to the conversation: the assistant "said" the invalid JSON; the user replies with the validation error
3. Re-invokes the LLM with this extended context (the model sees its own mistake)
4. Repeats up to `max_retries` times

See [[12_Retry_Mechanism_Validation_Feedback_Loop]] for the complete retry cycle description.

---

## Why This Eliminates an Entire Class of Failures

Without `instructor`, a production intent parser must handle:
- `json.loads()` raising `JSONDecodeError` when the LLM produces malformed JSON
- Missing required fields (KeyError)
- Wrong types (`"5"` instead of `5`)
- Out-of-range values (`confidence = 1.5`)
- Each of these requiring manual re-prompt logic

With `instructor`, all of these cases are handled by the library. The application code contains zero JSON parsing, zero retry logic, and zero fallback prompts for validation failures. The [[17_Schema_Constrained_Decoding|schema-constrained decoding]] guarantees valid output by construction.

---

## Backend Portability

`instructor` supports multiple adapters. The same [[05_ParsedIntent_Schema|`ParsedIntent`]] and [[06_BecknIntent_Schema|`BecknIntent`]] schemas work unchanged across all providers — only the client initialization changes:

| Backend | Initialization |
|---|---|
| Ollama (local, `qwen3`) | `instructor.from_openai(OpenAI(base_url="http://localhost:11434/v1", api_key="ollama"))` |
| OpenAI (cloud) | `instructor.from_openai(OpenAI(api_key="sk-..."))` |
| Anthropic (cloud) | `instructor.from_anthropic(anthropic.Anthropic(api_key="sk-ant-..."))` |

For the Anthropic backend, `instructor` uses `messages.create()` (the Anthropic SDK method) instead of `chat.completions.create()` — this is handled transparently by the `from_anthropic()` adapter. The `response_model=` parameter and retry logic behave identically. See [[15_Multi_Backend_Support]] for full multi-backend details and production relevance.

---

## What `instructor` Does NOT Do

- Does not change model behavior — it wraps the API call, not the model
- Does not guarantee semantically correct extraction — only structurally valid output
- Does not log or observe failures — tracing is added separately via [[observability_stack|LangSmith]]
- Does not handle network errors — only `ValidationError` from Pydantic

---

## Related Notes
- [[09_Pydantic_v2_Schema_Enforcement]] — How `Field(description=...)` and `@field_validator` interact with `instructor`
- [[12_Retry_Mechanism_Validation_Feedback_Loop]] — Full detail on the retry cycle
- [[15_Multi_Backend_Support]] — Switching between Ollama, OpenAI, and Anthropic backends
- [[17_Schema_Constrained_Decoding]] — Why schema-constrained decoding is chosen over fine-tuning
