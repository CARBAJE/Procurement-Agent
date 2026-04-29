---
tags: [intent-parser, evaluation, testing, accuracy, governance, cicd]
cssclasses: [procurement-doc, ai-doc]
status: "#approved"
related: ["[[22_Accuracy_Target_Fallback_Policy]]", "[[18_Few_Shot_Prompting_Strategy]]", "[[16_Model_Configuration]]"]
---

# Evaluation Methodology

> [!milestone] Evaluation Overview
> From [[model_governance_monitoring|Model Governance]]:
> - **Test set:** 100 procurement requests × 15 categories.
> - **Success criteria:** Valid JSON + all extracted fields match expected values.
> - **Frequency:** Weekly automated run via [[cicd_pipeline|GitHub Actions]].
> - **Acceptance in [[phase1_foundation_protocol_integration|Phase 1]]:** 15+ diverse requests parsed correctly.

---

## Test Set Structure

**100 procurement requests** covering **15 product categories**:

| Category Group | Categories |
|---|---|
| Office supplies | Paper, pens, folders, printer cartridges, staplers |
| IT hardware | Laptops, monitors, keyboards, networking equipment, servers |
| Industrial | Valves, flanges, pumps, bearings, fasteners |
| Healthcare | Medical devices, consumables, PPE, reagents |
| Facilities | Furniture, cleaning supplies, safety equipment |

Within each category, queries vary across:
- Simple (item + quantity only)
- With location
- With delivery timeline
- With budget
- With technical specifications
- With edge-case modifiers (urgency, government L1)

This coverage ensures the evaluation reflects real procurement diversity, not just simple "buy X" queries.

---

## Success Criteria

A query is marked **successful** if and only if:

1. **Valid JSON output** — the model produces output that passes `model_validate()` without raising `ValidationError`
2. **All extracted fields match expected values:**
   - `intent` matches the ground-truth intent label
   - `item` is semantically equivalent to the expected item name (not necessarily lexically identical)
   - `descriptions` contains all expected spec tokens (order-independent)
   - `location_coordinates` resolves to the expected `"lat,lon"` string
   - `delivery_timeline` is within ±10% of the expected hours value
   - `budget_constraints.max` is within ±5% of the expected value

The tolerance bands on numeric fields account for minor variation in LLM extraction without penalizing semantically correct outputs.

---

## Evaluation Trigger — Weekly Automated Run

```
GitHub Actions CI/CD pipeline
├── Trigger: every Monday at 00:00 UTC
├── Process:
│   ├── 1. Load 100-request test set from the evaluation corpus
│   ├── 2. Run each query through the full two-stage pipeline
│   ├── 3. Compare output against ground-truth annotations
│   └── 4. Compute accuracy rate = successful_queries / 100
└── Outcome:
    ├── accuracy >= 0.95 → PASS → no action required
    └── accuracy < 0.95  → FAIL → alert to [[model_governance_monitoring|Model Governance]]
                                   → investigation within 48 hours
```

All results are logged to [[audit_trail_system|Kafka audit events]] and observable via [[observability_stack|LangSmith]].

---

## Phase 1 Acceptance Criterion

The minimum bar for [[phase1_foundation_protocol_integration|Phase 1]] sign-off is lower than the steady-state target:

> **15+ diverse requests parsed correctly** (out of the 100-request test set)

This threshold is intentionally lenient for the initial deployment — it validates that the pipeline works end-to-end and produces valid Beckn payloads for the most common procurement patterns. The full 95% accuracy target is enforced from Phase 2 onward as the few-shot example set matures.

---

## Failure Investigation Process

When the weekly evaluation drops below 95%:

1. **Category analysis:** Which of the 15 categories has the highest failure rate?
2. **Failure mode classification:** Wrong `intent`? Wrong `item` extraction? Wrong numeric values? `ValidationError` (structural failure)?
3. **Remediation priority:**
   - Structural failures (`ValidationError`) → [[08_Instructor_Library_Integration|`instructor`]] or [[09_Pydantic_v2_Schema_Enforcement|Pydantic schema]] issue
   - Semantic failures (wrong values) → [[18_Few_Shot_Prompting_Strategy|add few-shot examples]] for the failing category
   - Systemic failures (all categories) → LLM model update may have changed behavior; revert or adjust [[16_Model_Configuration|model configuration]]

---

## Related Notes
- [[22_Accuracy_Target_Fallback_Policy]] — The 95% accuracy target this methodology validates
- [[18_Few_Shot_Prompting_Strategy]] — Primary lever for improving accuracy on failing categories
- [[16_Model_Configuration]] — Model configuration that the evaluation validates
