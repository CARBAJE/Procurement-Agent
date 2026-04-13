---
tags: [ai-model, governance, monitoring, langsmith, evaluation, drift-detection, model-registry, override-tracking]
cssclasses: [procurement-doc, ai-doc]
status: "#processed"
related: ["[[observability_stack]]", "[[llm_providers]]", "[[cicd_pipeline]]", "[[intent_parsing_model]]", "[[comparison_scoring_model]]", "[[negotiation_strategy_model]]", "[[memory_retrieval_model]]", "[[technical_performance_metrics]]"]
---

# AI Model Governance & Monitoring

> [!architecture] Governance Architecture
> Model governance ensures that the AI system's behavior remains predictable, measurable, and improvable over time. It covers four domains: (1) the **Model Registry** tracks what was deployed when; (2) the **Evaluation Pipeline** measures ongoing accuracy; (3) **Drift Detection** alerts when behavior degrades; (4) **Human Override Tracking** closes the feedback loop from user behavior back into model improvement. All four domains feed the [[observability_stack|LangSmith + Prometheus]] observability stack.

## Model Registry

- All LLM configurations tracked in a **version-controlled registry**:
  - Model version (`gpt-4o-2024-11-20`, `claude-sonnet-4-6`, etc.)
  - Prompt template version (semantic versioning)
  - Temperature and sampling settings
- Every agent response is traceable to a specific **model version + prompt version**.
- No model or prompt change goes to production without passing the evaluation suite.

## Evaluation Pipeline

| Attribute | Detail |
|---|---|
| Frequency | Weekly automated run via [[cicd_pipeline\|GitHub Actions]] |
| Test suite | 100 curated procurement scenarios (ground truth annotated) |
| Models evaluated | [[intent_parsing_model\|Intent parsing]], [[comparison_scoring_model\|comparison quality]], [[negotiation_strategy_model\|negotiation outcomes]], response latency |

### Metric Targets

| Metric | Target |
|---|---|
| Intent parsing accuracy | ≥ **95%** |
| Comparison quality vs. human expert | ≥ **85%** agreement |
| Agent accuracy on full evaluation suite | ≥ **85%** |
| Negotiation cost savings | **8–15%** avg. vs. list price |
| Agent response P95 latency | `< 5 seconds` |

> [!guardrail] Drift Detection Thresholds
> Two automatic alert conditions — any trigger fires an alert to [[communication_slack_teams|Slack]] and creates a ServiceNow ticket:
> - Accuracy drops below **85%** on evaluation suite → **prompt review triggered within 48 hours**.
> - User override rate exceeds **30%** → **scoring calibration review triggered**.
> These are not informational alerts — they require documented investigation and resolution.

## Human Override Tracking

- Every user override is captured with the override reason (logged to [[audit_trail_system|Kafka → PostgreSQL]]).
- Aggregated override data feeds back into:
  - Prompt improvement (for the [[intent_parsing_model|intent parser]] and [[comparison_scoring_model|comparison model]]).
  - Scoring weight calibration (for the [[comparison_scoring_engine|comparison engine]]).
  - Negotiation strategy refinement (for [[negotiation_strategy_model]]).

## LLM Observability (LangSmith)

[[observability_stack|LangSmith]] traces every LLM call:
- Input prompt (version-stamped from Model Registry).
- Output (full model response).
- Latency (per-call and aggregate).
- Token usage (input + output tokens).
- Cost per call (API cost).

> [!insight] Continuous Improvement Loop
> The governance model creates a self-improving system: user overrides → calibration updates → better recommendations → fewer overrides → lower operational cost. Target: user override rate drops from < 40% at 6 months to < 25% at 12 months (per [[user_adoption_metrics]]). Each percentage point reduction in override rate is evidence of the model getting better at understanding enterprise procurement preferences.
