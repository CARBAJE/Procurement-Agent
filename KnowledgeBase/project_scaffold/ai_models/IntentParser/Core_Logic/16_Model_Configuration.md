---
tags: [intent-parser, model-config, gpt4o, claude, llm, production, fallback]
cssclasses: [procurement-doc, ai-doc]
status: "#approved"
related: ["[[17_Schema_Constrained_Decoding]]", "[[18_Few_Shot_Prompting_Strategy]]", "[[22_Accuracy_Target_Fallback_Policy]]", "[[15_Multi_Backend_Support]]", "[[26_Production_vs_Prototype_Divergences]]"]
---

# Model Configuration — Intent Parsing

> [!architecture] Role in the AI Stack
> The Intent Parsing Model is the **first AI call** in every procurement workflow. It sits inside the [[nl_intent_parser|NL Intent Parser]] component (Lambda 1, port 8001) and converts natural language into Beckn-compatible JSON. Because every downstream step — Beckn `discover`, [[comparison_scoring_engine|comparison]], [[negotiation_engine|negotiation]] — depends on the quality of this parsing, it has the **highest accuracy target** of any model in the system: ≥ 95%.

---

## Production Model Configuration

| Attribute | Detail |
|---|---|
| **Primary model** | GPT-4o with structured output (JSON mode) |
| **Fallback model** | Claude Sonnet 4.6 |
| **Lightweight model** | GPT-4o-mini (simple, well-structured requests) |
| **Approach** | [[17_Schema_Constrained_Decoding\|Schema-constrained decoding]]; guaranteed valid JSON output |
| **Training** | [[18_Few_Shot_Prompting_Strategy\|Few-shot prompting]] with 50+ curated procurement examples |
| **Fine-tuning** | Not needed initially |

---

## Model Roles

### GPT-4o — Primary
Used for all procurement queries except those the [[10_Heuristic_Complexity_Router|complexity router]] classifies as simple. GPT-4o is used because:
- Highest structured-output reliability on JSON schema compliance
- Strong performance on technical procurement vocabulary (industrial specs, chemical codes, standardized measurements)
- Native JSON mode eliminates LLM-side JSON formatting issues

### Claude Sonnet 4.6 — Fallback
Activated automatically when `gpt-4o` fails to produce valid JSON after 3 retries. The failover mechanism mirrors the [[15_Multi_Backend_Support|multi-backend `instructor` adapter swap]] demonstrated in the notebook. No application logic changes — only the `instructor` client object is replaced.

### GPT-4o-mini — Lightweight
Used for queries the [[10_Heuristic_Complexity_Router|heuristic router]] classifies as simple (short, few numerics, no delivery/budget keywords). Cost-optimized without sacrificing accuracy for straightforward extraction tasks.

---

## Model Routing in Production

The production routing mirrors the notebook's `is_complex_request()` heuristic, but maps to **model generation** rather than model size:

| Notebook | Production | Routing Signal |
|---|---|---|
| `qwen3:1.7b` | `gpt-4o-mini` | `is_complex_request() == False` |
| `qwen3:8b` | `gpt-4o` | `is_complex_request() == True` |
| *(no fallback)* | `claude-sonnet-4-6` | `gpt-4o` fails after 3 retries |

---

## Why No Fine-Tuning (Initially)

Fine-tuning is explicitly deferred for two reasons:
1. **[[17_Schema_Constrained_Decoding|Schema-constrained decoding]] + [[18_Few_Shot_Prompting_Strategy|50+ few-shot examples]]** achieves ≥95% accuracy on the evaluation suite without fine-tuning — the target is met without the overhead.
2. Fine-tuning requires a labeled dataset, retraining infrastructure, and model versioning. The governance overhead is not justified until the few-shot approach plateaus below the 95% threshold.

If the accuracy target is not met after exhausting few-shot and prompt improvements, fine-tuning on the 100-request × 15-category evaluation dataset is the next lever.

---

## Related Notes
- [[17_Schema_Constrained_Decoding]] — Why JSON mode / schema-constrained output is used instead of free-form generation
- [[18_Few_Shot_Prompting_Strategy]] — The 50+ curated examples that achieve the 95% target
- [[22_Accuracy_Target_Fallback_Policy]] — The 95% accuracy target, retry policy, and fallback trigger conditions
- [[15_Multi_Backend_Support]] — How the `instructor` adapter swap enables the GPT-4o → Claude fallback
- [[10_Heuristic_Complexity_Router]] — Model routing between lightweight and full-size models
- [[26_Production_vs_Prototype_Divergences]] — How notebook (`qwen3`) maps to production (GPT-4o/Claude)
