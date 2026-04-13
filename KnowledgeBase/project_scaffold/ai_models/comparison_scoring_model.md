---
tags: [ai-model, scoring, comparison, react-loop, hybrid-model, tco, explainability, evaluation]
cssclasses: [procurement-doc, ai-doc]
status: "#processed"
related: ["[[comparison_scoring_engine]]", "[[llm_providers]]", "[[agent_memory_learning]]", "[[model_governance_monitoring]]", "[[phase2_core_intelligence_transaction_flow]]", "[[story2_high_value_it_equipment]]", "[[technical_performance_metrics]]"]
---

# AI Model: Comparison & Scoring

> [!architecture] Role in the AI Stack
> The Comparison & Scoring Model powers the [[comparison_scoring_engine]] component. It evaluates every seller offer in a Beckn `/on_search` response set and produces a ranked list with plain-language explanations. The model is **hybrid** by design: deterministic Python functions handle quantifiable metrics, while [[llm_providers|GPT-4o in a ReAct loop]] handles qualitative assessment and holistic reasoning.

## Architecture — Hybrid Approach

| Component | Method | Handles |
|---|---|---|
| Numerical scoring functions (Python) | Deterministic | Price, delivery time, volume discounts, TCO calculation |
| LLM reasoning engine ([[llm_providers\|GPT-4o ReAct]]) | LLM | Compliance fit, supplier reliability interpretation, holistic recommendation |

> [!tech-stack] Key Design Principle: Hybrid, Not Pure LLM
> A purely LLM-based scorer is non-deterministic (different runs may rank sellers differently), expensive at scale, and opaque. A purely rule-based scorer cannot handle qualitative factors like "does this supplier's certification actually fit our ESG policy?". The hybrid approach gives determinism where it matters (price math) and judgment where it's needed (compliance, reliability). Full spec in [[comparison_scoring_engine]].

## Scoring Dimensions

| Dimension | Weight Basis | Notes |
|---|---|---|
| Price | Volume discounts + TCO | Total cost of ownership, not just unit price |
| Delivery reliability | Historical fulfillment rate + ETA | Augmented by [[agent_memory_learning\|vector memory]] |
| Quality indicators | Ratings, certifications, return rates | From ONDC seller profiles |
| Compliance | Enterprise-specific requirements | ISO certs, sustainability, geographic restrictions |

## Weight Calibration

- Initial weights from historical procurement data ([[databases_postgresql_redis|PostgreSQL]] + [[vector_db_qdrant_pinecone|Qdrant]]).
- User override data (from [[audit_trail_system]]) feeds back into calibration over time.

## Explainability Output

Every recommendation includes a plain-language explanation:
> *"Seller C recommended despite 4% higher unit price. Superior warranty terms and bulk discount at 200+ units produce 8% lower TCO. Seller C holds ISO 27001 required by your IT procurement policy."*

Example from [[story2_high_value_it_equipment|Story 2]].

> [!milestone] Phase 2 Accuracy Target
> From [[model_governance_monitoring|Model Governance]] and [[phase2_core_intelligence_transaction_flow|Phase 2]]:
> - Comparison quality target: **≥ 85% agreement** with human expert ranking.
> - Measured via blind comparison test: agent rankings vs. expert rankings for identical offer sets.
> - Weekly evaluation run by [[cicd_pipeline|GitHub Actions]].

> [!guardrail] Override Rate Monitoring
> If user override rate exceeds **30%** → [[observability_stack|Grafana alert]] fires → [[model_governance_monitoring|scoring calibration review]] triggered.
> Each override is captured with reason in [[audit_trail_system|Kafka audit events]] and aggregated for calibration input.
