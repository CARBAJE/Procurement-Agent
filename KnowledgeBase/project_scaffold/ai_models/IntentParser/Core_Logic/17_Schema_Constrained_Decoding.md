---
tags: [intent-parser, schema-constrained-decoding, json-mode, structured-output, llm, reliability]
cssclasses: [procurement-doc, ai-doc]
status: "#approved"
related: ["[[08_Instructor_Library_Integration]]", "[[16_Model_Configuration]]", "[[09_Pydantic_v2_Schema_Enforcement]]", "[[22_Accuracy_Target_Fallback_Policy]]"]
---

# Schema-Constrained Decoding

> [!tech-stack] Why Schema-Constrained Decoding
> Standard LLM generation can produce malformed JSON — a JSON syntax error here crashes the [[beckn_bap_client|BAP client]]. Schema-constrained decoding forces the LLM to output valid JSON conforming to the Beckn intent schema **by construction**, using structured output mode. This eliminates an entire class of runtime failures without requiring fine-tuning. Few-shot prompting with 50+ examples achieves 95%+ accuracy on the evaluation suite.

---

## The Problem It Solves

Without schema-constrained decoding, the raw LLM output for a procurement query might be:

```
Here is the procurement intent extracted from your query:
{
  "item": "SS flanged valve",
  "quantity": 500
  "delivery_timeline": "5 days"   ← missing comma, wrong type
}
Note: I couldn't determine the exact location.
```

This output fails JSON parsing (`json.loads()` raises `JSONDecodeError` on the missing comma), uses a string where an integer is required, and wraps the JSON in free-text prose.

Every such failure requires:
1. Detecting the failure (try/except around `json.loads()`)
2. Extracting the JSON from surrounding prose (regex)
3. Fixing syntax errors (hard)
4. Re-prompting (manual logic)
5. Handling persistent failures (retry budget management)

This is substantial application code that must be written, tested, and maintained.

---

## How Schema-Constrained Decoding Works

**JSON mode** (OpenAI, Ollama) constrains the LLM's token-by-token generation:
- The model tokenizer enforces that every token produced is a valid continuation of a JSON string
- Structural tokens (`{`, `}`, `[`, `]`, `:`, `,`) are forced at syntactically correct positions
- The schema is provided as a system constraint — the model's output must conform to the defined field structure

**`instructor`'s schema injection** extends this by:
1. Appending the full JSON Schema derived from the Pydantic model to the prompt context
2. Using `response_model=` to trigger the JSON mode constraint
3. Running Pydantic's `model_validate()` after generation for **semantic validation** (type coercion, `@field_validator` enforcement) — not just syntax validation

The result: the LLM physically cannot produce syntactically malformed JSON. Semantic failures (wrong types, out-of-range values) are caught by Pydantic and handled by the [[12_Retry_Mechanism_Validation_Feedback_Loop|`instructor` retry loop]].

---

## Why Not Fine-Tuning?

Fine-tuning would teach the model to produce the right *content* for procurement extraction tasks. Schema-constrained decoding guarantees the right *structure* regardless of content. They solve different problems:

| Approach | Guarantees | Requires |
|---|---|---|
| Fine-tuning | Correct content for known query patterns | Labeled dataset, retraining, model versioning |
| Schema-constrained decoding | Structurally valid JSON output always | Only the schema definition |
| **Both (ideal)** | Correct structure + correct content | Both of the above |

For the initial PoC: schema-constrained decoding + [[18_Few_Shot_Prompting_Strategy|50+ few-shot examples]] achieves the 95% accuracy target without the fine-tuning overhead. Fine-tuning is deferred until the few-shot approach plateaus.

---

## What Schema-Constrained Decoding Does NOT Guarantee

- **Semantic accuracy:** The LLM can still extract the wrong item name, wrong quantity, or wrong location — the JSON will be valid but semantically incorrect. Few-shot prompting and field descriptions address this.
- **Business rule compliance:** `delivery_timeline = 0` is syntactically valid JSON and a valid integer — the Pydantic `@field_validator` catches this semantic constraint.
- **Completeness:** If the query contains no location, the LLM may hallucinate one — valid JSON, but factually wrong. The `resolve_location()` validator normalizes known cities; unknown hallucinations pass through.

---

## Eliminating a Class of Failures

By construction, the following failures **cannot occur** with schema-constrained decoding + `instructor`:

- `JSONDecodeError` from malformed JSON
- `KeyError` from missing required fields (Pydantic enforces required fields)
- `TypeError` from wrong primitive types (Pydantic coerces compatible types, rejects incompatible ones)
- Prose-wrapped JSON (the model outputs only the JSON object, no surrounding text)

The failure space is reduced to:
- **Semantic extraction errors** (wrong values, but valid types) — addressed by few-shot prompting
- **Business constraint violations** (out-of-range, non-positive) — addressed by `@field_validator`
- **Persistent validation failures after 3 retries** — caught as `InstructorRetryException`

---

## Related Notes
- [[08_Instructor_Library_Integration]] — The library that implements schema injection and enforces JSON mode
- [[09_Pydantic_v2_Schema_Enforcement]] — Semantic validation layer on top of structural guarantees
- [[12_Retry_Mechanism_Validation_Feedback_Loop]] — What happens when semantic validation fails
- [[18_Few_Shot_Prompting_Strategy]] — The complementary approach that improves semantic accuracy
- [[22_Accuracy_Target_Fallback_Policy]] — The 95% accuracy target this mechanism helps achieve
