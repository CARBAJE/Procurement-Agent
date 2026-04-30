---
tags: [intent-parser, accuracy, fallback, reliability, governance, sla]
cssclasses: [procurement-doc, ai-doc]
status: "#approved"
related: ["[[16_Model_Configuration]]", "[[21_Evaluation_Methodology]]", "[[12_Retry_Mechanism_Validation_Feedback_Loop]]", "[[15_Multi_Backend_Support]]"]
---

# Accuracy Target and Fallback Policy

> [!guardrail] Accuracy Target & Fallback
> Intent parsing accuracy target: ≥ **95%** (per [[technical_performance_metrics]]).
> If primary model (`gpt-4o`) fails to produce valid JSON after 3 retries → fallback to `claude-sonnet-4-6` automatically.
> All parse failures are logged to [[audit_trail_system|Kafka audit events]] with the raw input for debugging via [[observability_stack|LangSmith]].

---

## The 95% Accuracy Target

The intent parsing step has the **highest accuracy requirement** of any model in the procurement pipeline. The justification is structural:

```
IntentParser accuracy degrades
        │
        ▼
BecknIntent.item is wrong / BecknIntent.quantity is wrong
        │
        ▼
BAP Client sends malformed discover query
        │
        ▼
Zero offerings returned (silent failure)
OR
Wrong category of items returned (silent false positive)
        │
        ▼
Comparison Engine scores irrelevant results
        │
        ▼
Procurement recommendation is wrong
```

Every downstream lambda in the Step Functions state machine amplifies an IntentParser error — there is no recovery mechanism downstream. Hence: **highest accuracy target, strictest SLA, most retries**.

---

## Fallback Chain

```
Attempt 1–4: gpt-4o (1 initial + 3 retries via instructor)
        │
        │ max_retries=3 exhausted → InstructorRetryException
        │
        ▼
Attempt 5–8: claude-sonnet-4-6 (1 initial + 3 retries)
        │
        │ All retries exhausted
        │
        ▼
Parse FAILURE
  → Log raw input + error to Kafka audit event
  → Return {intent: null, beckn_intent: null, error: "parse_failure"}
  → Orchestrator aborts pipeline and returns error to frontend
```

The fallback to `claude-sonnet-4-6` is handled by replacing the [[15_Multi_Backend_Support|`instructor` client adapter]] — no application logic changes. The same `BecknIntent` schema and retry parameters apply to the fallback model.

---

## 3-Retry Policy — Why 3?

The `max_retries=3` budget is chosen to balance:
- **Accuracy:** Most [[12_Retry_Mechanism_Validation_Feedback_Loop|validation feedback loop]] corrections succeed within 1–2 retries. 3 retries covers the tail of stubborn failures.
- **Latency:** Each retry adds one LLM round-trip (~500ms–2s for `gpt-4o`). 3 retries = maximum 3 extra seconds on top of the initial call.
- **Cost:** At $0.005/1K output tokens, 3 retries × 300 tokens ≈ $0.0045 extra per failed parse — acceptable.

The `claude-sonnet-4-6` fallback adds another 3 retries: total possible LLM calls per parse = 8.

---

## Failure Logging

Every failed parse (whether due to retry exhaustion or unexpected exceptions) is logged to [[audit_trail_system|Kafka audit events]] with:
- Raw user input (for debugging)
- Exception type and message
- Number of retries attempted
- Model used
- Timestamp

This data populates the [[observability_stack|LangSmith]] failure dashboard and feeds into the weekly [[21_Evaluation_Methodology|evaluation run]] as supplementary evidence for failing query categories.

---

## Accuracy Monitoring

The 95% target is monitored by:
1. **Weekly automated evaluation:** 100-request × 15-category test set via GitHub Actions — see [[21_Evaluation_Methodology]]
2. **Real-time failure rate:** Kafka consumer tracking `parse_failure` events; alert if > 5% over any 24-hour window
3. **LangSmith trace analysis:** Trace distribution of retry counts; if median retry count > 1, the LLM behavior has drifted and the few-shot examples need refreshing

---

## Related Notes
- [[16_Model_Configuration]] — Primary (GPT-4o), fallback (Claude Sonnet 4.6), lightweight (GPT-4o-mini) model definitions
- [[21_Evaluation_Methodology]] — Weekly test run validating the 95% target
- [[12_Retry_Mechanism_Validation_Feedback_Loop]] — The `instructor` retry mechanism (max 3 retries per model)
- [[15_Multi_Backend_Support]] — The `instructor` adapter swap enabling the GPT-4o → Claude fallback
