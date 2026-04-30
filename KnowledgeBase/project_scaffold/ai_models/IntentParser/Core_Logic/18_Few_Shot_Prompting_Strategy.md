---
tags: [intent-parser, few-shot, prompting, llm, accuracy, training]
cssclasses: [procurement-doc, ai-doc]
status: "#approved"
related: ["[[16_Model_Configuration]]", "[[17_Schema_Constrained_Decoding]]", "[[02_Stage1_IntentClassifier]]", "[[03_Stage2_BecknIntentParser]]", "[[21_Evaluation_Methodology]]"]
---

# Few-Shot Prompting Strategy

> [!architecture] Role
> Few-shot prompting provides the LLM with domain-specific examples in the prompt context before presenting the user's query. Combined with [[17_Schema_Constrained_Decoding|schema-constrained decoding]], 50+ curated procurement examples achieve ≥ 95% accuracy on the evaluation suite without fine-tuning.

---

## Scale and Scope

**50+ curated procurement examples** covering:
- Simple product queries ("500 A4 paper reams")
- Technical specification queries ("200 laptops, Intel Core i7, 16GB RAM, 512 SSD")
- Multi-numeric queries ("100 stainless flanged valves, 2 inch, SS316, ₹800 each")
- Budget-constrained queries ("office chairs under ₹5,000, ergonomic, lumbar support")
- Location-specific queries ("deliver to Mumbai office within 72 hours")
- Edge cases: `"URGENT:"` prefix, multi-location delivery, government L1 constraints

---

## Stage 1 vs. Stage 2 Prompt Strategies

### Stage 1 Prompting — Domain Context

The [[02_Stage1_IntentClassifier|Stage 1 classifier]] system prompt provides **domain context** rather than intent label definitions:

```
System: You are an enterprise procurement assistant operating on the Beckn 
Protocol network. Your job is to classify incoming queries from corporate 
procurement officers. Queries may involve searching for products, requesting 
quotes, placing orders, or other supply-chain activities.

Classify the following query using a PascalCase intent label that best 
describes the procurement action being requested.
```

**Why domain context, not label definitions:** Providing a list of valid intent labels would bias the LLM toward enumerated values and undermine the [[04_Domain_Gating_Procurement_Intents|open-vocabulary design]]. Domain context lets the LLM apply its knowledge of enterprise procurement workflows to synthesize meaningful intent names for edge cases (`"CancelOrder"`, `"TrackOrder"`) that a closed enum would misclassify.

### Stage 2 Prompting — Beckn-Specific Rules

The [[03_Stage2_BecknIntentParser|Stage 2 extractor]] system prompt is **Beckn-specific and rule-heavy**:

- Unit conversion rules: `"1 day = 24 hours, 1 week = 168 hours. Always output delivery_timeline as a positive integer in hours."`
- Currency stripping: `"Extract only numeric values for budget fields. Remove all currency symbols (₹, INR, USD, $) and separators (,)."`
- Spec decomposition: `"Decompose technical specifications into individual atomic tokens in the descriptions list. Each element must be one specification component."`
- Location resolution: Inline city-to-coordinates table (mirrors [[13_Location_Resolution|`_CITY_COORDINATES`]])

---

## Why Few-Shot Over Fine-Tuning

| Approach | When to Use | Overhead |
|---|---|---|
| **Few-shot (chosen)** | Accuracy target met with in-context examples | Zero: no training, no dataset curation beyond examples |
| Fine-tuning | Accuracy plateau below target with few-shot | High: labeled dataset, retraining infrastructure, model versioning, governance |

The 50+ examples cover the diversity of real procurement queries encountered in the [[phase1_foundation_protocol_integration|Phase 1]] evaluation set. As long as ≥ 95% accuracy is maintained, fine-tuning is deferred.

---

## Example Quality Requirements

Each few-shot example must demonstrate the complete extraction:

**Stage 1 example:**
```
Query: "We need 200 A4 80gsm paper reams for the Delhi office, budget ₹18,000"
Output: ParsedIntent(
  intent="SearchProduct",
  product_name="A4 80gsm paper",
  quantity=200,
  confidence=0.98,
  reasoning="This is a product search request with quantity, location, and budget specified."
)
```

**Stage 2 example:**
```
Query: "We need 200 A4 80gsm paper reams for the Delhi office, budget ₹18,000"
Output: BecknIntent(
  item="A4 paper",
  descriptions=["A4", "80gsm"],
  quantity=200,
  location_coordinates="28.7041,77.1025",
  delivery_timeline=72,            ← default when none specified
  budget_constraints={"min": 0.0, "max": 18000.0}
)
```

Poor examples (wrong field values, over-specified `item`, concatenated `descriptions`) directly degrade extraction accuracy — example quality is the primary accuracy lever before fine-tuning.

---

## Maintenance and Drift

When the [[21_Evaluation_Methodology|weekly evaluation run]] shows accuracy dropping below 95% for a specific category (e.g., industrial components), the first remediation step is adding 5–10 new few-shot examples for that category — before considering prompt restructuring, schema changes, or fine-tuning.

The few-shot example set is versioned alongside the prompt templates in the [[model_governance_monitoring|Model Registry]] in production.

---

## Related Notes
- [[16_Model_Configuration]] — Why fine-tuning is deferred in favor of few-shot
- [[17_Schema_Constrained_Decoding]] — The complementary structural guarantee that few-shot provides semantics for
- [[21_Evaluation_Methodology]] — The evaluation suite that validates few-shot effectiveness
- [[02_Stage1_IntentClassifier]] — Stage 1 system prompt strategy (domain context)
- [[03_Stage2_BecknIntentParser]] — Stage 2 system prompt strategy (Beckn-specific rules)
