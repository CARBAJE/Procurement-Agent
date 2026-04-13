---
tags: [ai-model, nlp, gpt4o, claude, intent-parsing, structured-output, json-schema, few-shot, evaluation]
cssclasses: [procurement-doc, ai-doc]
status: "#processed"
related: ["[[nl_intent_parser]]", "[[llm_providers]]", "[[beckn_bap_client]]", "[[model_governance_monitoring]]", "[[phase1_foundation_protocol_integration]]", "[[story3_emergency_procurement]]", "[[story5_government_emarketplace]]"]
---

# AI Model: Intent Parsing

> [!architecture] Role in the AI Stack
> The Intent Parsing Model is the **first AI call** in every procurement workflow. It sits inside the [[nl_intent_parser]] component and converts natural language into Beckn-compatible JSON. Because every downstream step (Beckn `/search`, [[comparison_scoring_engine|comparison]], [[negotiation_engine|negotiation]]) depends on the quality of this parsing, it has the **highest accuracy target** of any model in the system: ≥ 95%.

## Model Configuration

| Attribute | Detail |
|---|---|
| Primary model | [[llm_providers\|GPT-4o]] with structured output (JSON mode) |
| Fallback model | [[llm_providers\|Claude Sonnet 4.6]] |
| Lightweight model | [[llm_providers\|GPT-4o-mini]] (simple, well-structured requests) |
| Approach | Schema-constrained decoding; guaranteed valid JSON output |
| Training | Few-shot prompting with 50+ curated procurement examples |
| Fine-tuning | Not needed initially |

> [!tech-stack] Schema-Constrained Decoding
> Standard LLM generation can produce malformed JSON — a JSON syntax error here crashes the [[beckn_bap_client|BAP client]]. Schema-constrained decoding forces the [[llm_providers|LLM]] to output valid JSON conforming to the Beckn intent schema by construction, using structured output mode. This eliminates an entire class of runtime failures without requiring fine-tuning. Few-shot prompting with 50+ examples achieves 95%+ accuracy on the evaluation suite.

## Fields Extracted

- Item name and technical specifications (gsm, RAM, SSD size, certifications)
- Quantity and unit of measure
- Delivery location (lat/lon coordinates or address)
- Delivery deadline (days)
- Budget constraints (per-unit or total)
- **Urgency flag** — `"URGENT:"` prefix → emergency mode activated ([[story3_emergency_procurement|Story 3]])
- Government compliance flags — L1 mode, quality floor ([[story5_government_emarketplace|Story 5]])

## Edge Cases Handled

- Multi-location delivery: [[story3_emergency_procurement|Story 3]] — 4 hospital locations simultaneously.
- Complex technical specs: [[story2_high_value_it_equipment|Story 2]] — 200 laptops with detailed hardware requirements.
- Government L1 constraints: [[story5_government_emarketplace|Story 5]] — quality floor ≥ 4.0 rating, L1 mandatory.
- Emergency urgency detection: [[story3_emergency_procurement|Story 3]] — "URGENT:" triggers emergency procurement mode.

> [!milestone] Evaluation Methodology
> From [[model_governance_monitoring|Model Governance]]:
> - Test set: 100 procurement requests × 15 categories.
> - **Success criteria:** Valid JSON + all extracted fields match expected values.
> - Frequency: weekly automated run via [[cicd_pipeline|GitHub Actions]].
> - Acceptance in [[phase1_foundation_protocol_integration|Phase 1]]: 15+ diverse requests parsed correctly.

> [!guardrail] Accuracy Target & Fallback
> Intent parsing accuracy target: ≥ **95%** (per [[technical_performance_metrics]]).
> If primary model (`gpt-4o`) fails to produce valid JSON after 3 retries → fallback to `claude-sonnet-4-6` automatically.
> All parse failures are logged to [[audit_trail_system|Kafka audit events]] with the raw input for debugging via [[observability_stack|LangSmith]].
