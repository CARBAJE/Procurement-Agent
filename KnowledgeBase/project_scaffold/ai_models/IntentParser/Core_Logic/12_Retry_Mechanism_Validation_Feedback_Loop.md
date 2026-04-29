---
tags: [intent-parser, retry, instructor, validation, feedback-loop, reliability]
cssclasses: [procurement-doc, ai-doc]
status: "#approved"
related: ["[[08_Instructor_Library_Integration]]", "[[09_Pydantic_v2_Schema_Enforcement]]", "[[05_ParsedIntent_Schema]]", "[[06_BecknIntent_Schema]]", "[[10_Heuristic_Complexity_Router]]"]
---

# Retry Mechanism — `instructor`'s Validation Feedback Loop

> [!guardrail] Automatic Retry on Validation Failure
> When the LLM produces output that fails Pydantic validation (e.g., `confidence=1.5`, `delivery_timeline=-1`, malformed JSON), `instructor` executes a **closed-loop error correction cycle** without any application code. This is equivalent to a human prompt engineer manually re-prompting with `"Your previous answer was invalid because: [error]"` — but automated and transparent.

---

## The Retry Cycle — Step by Step

```
Step 1: LLM produces raw JSON string
          │
          ▼
Step 2: instructor calls model.model_validate(json_dict)
          │
          │─── SUCCESS → return validated model instance to caller ✓
          │
          │─── FAILURE → ValidationError raised
                    │
                    ▼
Step 3: instructor captures the ValidationError detail:
        - field name
        - value that failed
        - error message (from @field_validator or Pydantic type system)
          │
          ▼
Step 4: instructor appends to the conversation history:
        [assistant]: <the invalid JSON the LLM just produced>
        [user]:      "Your previous answer was invalid because: <error_message>"
          │
          ▼
Step 5: LLM re-invoked with extended context
        - model sees its own previous (invalid) response
        - model sees the correction requirement
        - model self-corrects and produces a new JSON response
          │
          ▼
Step 6: Repeat from Step 2, up to max_retries times
          │
          │─── SUCCESS on any attempt → return validated instance ✓
          │
          └─── All retries exhausted → raise InstructorRetryException
```

---

## Caller Interface

From the calling code's perspective, the retry loop is completely invisible:

```python
# instructor handles all retry logic internally — from the caller's perspective:
result = client.chat.completions.create(
    model=model,
    messages=messages,
    response_model=BecknIntent,
    max_retries=3,  # ← retry budget
)
# If all 3 retries fail, instructor raises InstructorRetryException
```

The caller either receives a fully validated `BecknIntent` instance, or catches `InstructorRetryException` for failure handling — no intermediate states, no partial objects.

---

## `@field_validator` as Intentional Retry Triggers

The validators in [[05_ParsedIntent_Schema|`ParsedIntent`]] and [[06_BecknIntent_Schema|`BecknIntent`]] are specifically designed to produce informative `ValueError` messages that give the LLM actionable correction context:

| Validator | LLM Error Input | LLM Correction Signal |
|---|---|---|
| `confidence_in_range` | `{"confidence": 1.5}` | `"confidence must be in [0, 1], got: 1.5"` |
| `timeline_positive` | `{"delivery_timeline": -24}` | `"delivery_timeline must be > 0, got -24"` |
| `apply_location_lookup` | *(no failure — passthrough for unknowns)* | *(N/A)* |

The error message precision matters: `"must be in [0, 1]"` is clearer than `"value error"` as a correction directive.

---

## What Gets Retried

`instructor` retries on:
- `ValidationError` from Pydantic (type mismatch, failed `@field_validator`, missing required field)
- Malformed JSON (LLM produces non-JSON text, truncated JSON, JSON with comments)

`instructor` does **not** retry on:
- Network errors (HTTP 5xx, timeouts) — these propagate as-is
- `InstructorRetryException` (all retries exhausted) — caller must handle
- `KeyboardInterrupt`, `SystemExit` — these are never caught

---

## Retry Budget and InstructorRetryException

`max_retries=3` means the LLM is called at most **4 times** total (1 initial + 3 retries). If all 4 calls produce invalid output:

```python
# In Stage 2 BecknIntentParser:
try:
    result = client.chat.completions.create(
        model="qwen3:1.7b",
        ...,
        max_retries=3,
    )
except InstructorRetryException:
    # Fallback to larger model — see is_complex_request() fallback escalation
    result = client.chat.completions.create(
        model="qwen3:8b",
        ...,
        max_retries=3,
    )
```

This is the **fallback escalation path** described in [[10_Heuristic_Complexity_Router]]. The `InstructorRetryException` from the small model triggers a re-attempt with the large model.

---

## Comparison: With vs. Without `instructor`

| Failure Case | Without `instructor` | With `instructor` |
|---|---|---|
| `confidence = 1.5` | `ValidationError` propagates to caller | Retry with correction → `0.97` returned |
| Missing required field | `ValidationError` → caller error | Retry → field included on second attempt |
| Malformed JSON | `json.loads()` → `JSONDecodeError` | Retry → valid JSON on second attempt |
| All retries exhausted | N/A (no retries) | `InstructorRetryException` → fallback model |

---

## Related Notes
- [[08_Instructor_Library_Integration]] — How `instructor` wraps the OpenAI client to enable this behavior
- [[09_Pydantic_v2_Schema_Enforcement]] — How `@field_validator` produces the error messages used as correction prompts
- [[05_ParsedIntent_Schema]] — `@field_validator("confidence")` — intentional retry trigger
- [[06_BecknIntent_Schema]] — `@field_validator("delivery_timeline")` — intentional retry trigger
- [[10_Heuristic_Complexity_Router]] — Fallback escalation: `qwen3:1.7b` retry exhaustion → `qwen3:8b`
