---
tags: [intent-parser, stage1, classification, domain-gatekeeper, llm, parsedintent]
cssclasses: [procurement-doc, ai-doc]
status: "#approved"
related: ["[[01_Two_Stage_Pipeline_Overview]]", "[[04_Domain_Gating_Procurement_Intents]]", "[[05_ParsedIntent_Schema]]", "[[08_Instructor_Library_Integration]]", "[[12_Retry_Mechanism_Validation_Feedback_Loop]]"]
---

# Stage 1 — `IntentClassifier` (Domain Gatekeeper)

> [!architecture] Role
> Stage 1 is the **domain gatekeeper** of the pipeline. Its only purpose is to classify the query's intent category and extract shallow signals (product name, quantity, confidence). It runs on every query. Stage 2 is invoked only if Stage 1 determines the query is procurement-relevant.

---

## What Stage 1 Does

The `IntentClassifier` receives the raw natural-language user query and produces a [[05_ParsedIntent_Schema|`ParsedIntent`]] object:

- **`intent`** — open-ended PascalCase string synthesized by the LLM (e.g., `"SearchProduct"`, `"Greeting"`, `"CancelOrder"`)
- **`product_name`** — optional shallow extraction of the item being discussed
- **`quantity`** — optional numeric extraction
- **`confidence`** — LLM self-assessed classification confidence, bounded `[0.0, 1.0]` by `@field_validator`
- **`reasoning`** — LLM's free-text justification for the intent classification

The model used at Stage 1 is **`qwen3:8b` (fixed)** — the router heuristic does not apply here because classification is always lightweight compared to structured extraction, and consistency in Stage 1 output reduces variance in the [[04_Domain_Gating_Procurement_Intents|domain gating]] check.

---

## Open Intent Vocabulary — Design Decision

The `intent` field uses `str` instead of `Literal["SearchProduct", "RequestQuote", "PurchaseOrder"]`. This is **deliberate**:

> A fixed `Literal` enum would misclassify unanticipated queries. A user saying "Hello, can you help me?" would be forced into the nearest procurement label — a false positive that causes Stage 2 to run on non-procurement input, producing nonsensical Beckn fields.

With an open vocabulary, the LLM synthesizes names like `"Greeting"`, `"CancelOrder"`, `"TrackOrder"`, or `"SupportRequest"` freely. The [[04_Domain_Gating_Procurement_Intents|`_PROCUREMENT_INTENTS` set check]] then acts as the filter — only `"SearchProduct"`, `"RequestQuote"`, and `"PurchaseOrder"` advance to Stage 2.

**Trade-off accepted:** Higher recall at the cost of requiring the routing logic to filter. The alternative (a closed enum) would require redeployment every time a new intent class is encountered in production.

---

## System Prompt Strategy

The Stage 1 system prompt provides **domain context** rather than intent label definitions:

- Context given: industrial procurement domain, RFQ workflows, Beckn protocol network
- The LLM is instructed to reason about what constitutes a procurement intent in this specific domain
- It is NOT given a list of valid labels — this would bias it toward enumerated values and undermine the open-vocabulary design

This contextual prompting lets the LLM apply its knowledge of enterprise procurement workflows to produce meaningful, interpretable intent names — even for edge cases not seen in the few-shot examples.

---

## Stage 1 Output — Effect on Pipeline Routing

```
ParsedIntent.intent ∈ {"SearchProduct", "RequestQuote", "PurchaseOrder"}
        │
        YES → [[03_Stage2_BecknIntentParser]] is invoked
        │       → [[10_Heuristic_Complexity_Router]] determines model
        │
        NO  → Pipeline short-circuits
                → Return {"intent": <intent>, "beckn_intent": null}
                → Stage 2 never runs
```

Non-procurement intents that short-circuit the pipeline include (but are not limited to):
- `"Greeting"` — user greetings or conversational openers
- `"CancelOrder"` — order cancellation requests (handled by a different workflow)
- `"TrackOrder"` — delivery tracking queries
- `"SupportRequest"` — help or complaint queries

**Why this matters:** Preventing Stage 2 on these queries avoids extracting incomplete or nonsensical Beckn fields (e.g., `item = "Hello"`, `quantity = null`) that would silently produce bad `discover` calls downstream.

---

## Retry Behavior

[[08_Instructor_Library_Integration|`instructor`]] applies the [[12_Retry_Mechanism_Validation_Feedback_Loop|validation feedback loop]] at Stage 1 as well. If the `@field_validator` on `confidence` rejects the LLM's output (e.g., `confidence = 1.5`), the error is fed back to the model and re-attempted up to `max_retries=3`. If all retries fail, an `InstructorRetryException` is raised and propagates to the caller.

---

## Related Notes
- [[05_ParsedIntent_Schema]] — Full Pydantic model definition for `ParsedIntent`
- [[04_Domain_Gating_Procurement_Intents]] — The `_PROCUREMENT_INTENTS` set and short-circuit logic
- [[03_Stage2_BecknIntentParser]] — What happens when Stage 1 passes
- [[08_Instructor_Library_Integration]] — How `instructor` wraps the LLM call
- [[18_Few_Shot_Prompting_Strategy]] — The 50+ curated procurement examples used in Stage 1 prompting
