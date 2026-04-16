---
tags: [component, ai, nlp, intent-parsing, structured-output, gpt4o, json-schema, beckn]
cssclasses: [procurement-doc, component-doc]
status: "#processed"
related: ["[[llm_providers]]", "[[beckn_bap_client]]", "[[agent_framework_langchain_langgraph]]", "[[phase1_foundation_protocol_integration]]", "[[intent_parsing_model]]", "[[story1_routine_office_supply]]", "[[story3_emergency_procurement]]"]
---

# Component: Natural Language Intent Parser

> [!architecture] Role in the System
> The NL Intent Parser is the **entry gate** of the procurement pipeline. Every user request — typed into the [[frontend_react_nextjs|dashboard]] or sent via [[communication_slack_teams|Slack]] — passes through this component before anything else happens. It converts free-form natural language into a structured JSON object that maps directly to Beckn v2 `discover` query parameters. A bad parse here cascades into bad search results; hence it is the highest-priority component in [[phase1_foundation_protocol_integration|Phase 1]].

## Example Transformation

**Input (natural language):**
> "I need 500 units of A4 printer paper, 80gsm, delivered to our Bangalore office within 5 days, budget under ₹2 per sheet."

**Output (structured JSON):**
```json
{
  "item": "A4 printer paper",
  "specifications": { "gsm": 80 },
  "quantity": 500,
  "unit": "reams",
  "location": { "lat": 12.9716, "lon": 77.5946 },
  "delivery_deadline_days": 5,
  "budget_per_unit": 2.0,
  "currency": "INR"
}
```

## Implementation

- **Primary model:** [[llm_providers|GPT-4o]] with structured output (JSON mode).
- **Fallback model:** [[llm_providers|Claude Sonnet 4.6]].
- **Lightweight model:** [[llm_providers|GPT-4o-mini]] for simple, well-structured requests.
- **Approach:** Schema-constrained decoding guarantees valid JSON output conforming to the Beckn intent schema. No fine-tuning — few-shot prompting with 50+ curated procurement examples achieves 95%+ accuracy.
- Full model specification: [[intent_parsing_model]].

## Fields Extracted

- Item descriptors (name, specifications, certifications required)
- Quantity and unit of measure
- Delivery location (coordinates or address)
- Delivery timeline (days)
- Budget constraints (per-unit or total)
- **Urgency flag** — `"URGENT:"` prefix detected → activates emergency procurement mode in [[story3_emergency_procurement]]
- Compliance requirements (ISO certifications, geographic restrictions)

> [!milestone] Phase 1 Acceptance Criteria (Weeks 1–4)
> From [[phase1_foundation_protocol_integration|Phase 1 NL Intent Parser milestone]]:
> - Correctly parses **15+ diverse procurement requests** into valid Beckn-compatible intent JSON.
> - Evaluated against 100 procurement requests spanning 15 categories.
> - **Success criterion:** Valid JSON output matching expected schema with all extracted fields correct.
> - Full evaluation methodology: [[intent_parsing_model]].

> [!guardrail] Parsing Reliability
> The parser uses **schema-constrained decoding** — the [[llm_providers|LLM]] is forced to output valid JSON conforming to the Beckn intent schema. This eliminates the risk of malformed JSON crashing the downstream [[beckn_bap_client|BAP client]]. If the primary model fails to produce valid JSON after 3 retries, the fallback model (`claude-sonnet-4-6`) is invoked automatically. All parse failures are logged to [[audit_trail_system|Kafka audit events]].

> [!insight] Accuracy Target
> Intent parsing accuracy ≥ **95%** on the 100-scenario evaluation suite (per [[technical_performance_metrics]]). This is the highest accuracy target in the system — errors here compound through every downstream step.
