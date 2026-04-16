---
tags: [component, ai, scoring, comparison, explainability, react-loop, hybrid-model, multi-criteria]
cssclasses: [procurement-doc, component-doc]
status: "#processed"
related: ["[[beckn_bap_client]]", "[[llm_providers]]", "[[agent_memory_learning]]", "[[approval_workflow]]", "[[audit_trail_system]]", "[[phase2_core_intelligence_transaction_flow]]", "[[comparison_scoring_model]]", "[[story2_high_value_it_equipment]]"]
---

# Component: AI Comparison & Scoring Engine

> [!architecture] Role in the System
> After the [[beckn_bap_client|BAP Client]] collects and normalizes seller responses, the Comparison & Scoring Engine evaluates all offers in parallel and produces a **ranked, explained recommendation**. It operates as a hybrid system: deterministic Python functions handle quantifiable metrics (price, delivery time), while [[llm_providers|GPT-4o in a ReAct loop]] handles qualitative assessment (compliance fit, holistic TCO reasoning). Every score is accompanied by a human-readable explanation — critical for [[audit_trail_system|audit compliance]] and user trust.

## Scoring Dimensions

| Dimension | Method | Notes |
|---|---|---|
| Price | Deterministic (Python) | Weighted by volume discounts and total cost of ownership (TCO) |
| Delivery reliability | Deterministic | Historical fulfillment rate + ETA (from [[agent_memory_learning\|vector memory]]) |
| Quality indicators | Hybrid | Ratings, certifications, return rates |
| Compliance | Hybrid | Enterprise-specific requirements (ISO certs, sustainability, geographic restrictions) |

> [!tech-stack] Why Hybrid Architecture
> A purely LLM-based scorer would be non-deterministic and expensive for high-volume use. A purely rule-based scorer cannot handle qualitative compliance assessment ("does this supplier's sustainability certification actually meet our ESG policy?"). The **hybrid approach** uses Python functions where determinism matters and LLM reasoning where judgment is required — giving the best of both. See full specification in [[comparison_scoring_model]].

## Explainability

Every recommendation includes a plain-language explanation from the ReAct loop. Example:
> *"Seller C recommended despite 4% higher unit price. Superior warranty (5-year vs. 3-year) and bulk discount at 200+ units produce 8% lower TCO over the contract period. Seller C also holds ISO 27001 certification required by your IT procurement policy."*

This explainability is captured in the [[audit_trail_system|Kafka audit event]] and displayed in the [[frontend_react_nextjs|comparison UI]].

## Weight Calibration

- Initial weights set from historical procurement data (from [[agent_memory_learning|Vector DB]]).
- User override data (captured via [[audit_trail_system]]) feeds back into calibration over time.

> [!milestone] Phase 2 Acceptance (Weeks 5–8)
> From [[phase2_core_intelligence_transaction_flow|Phase 2 Comparison Engine milestone]]:
> - Ranks sellers correctly for **10+ test scenarios**.
> - Clear, human-readable explanations provided for each ranking.
> - Comparison UI (in [[frontend_react_nextjs]]) shows side-by-side view with reasoning visible.

> [!guardrail] Accuracy & Override Monitoring
> Comparison quality target: **≥ 85% agreement** with human expert ranking (blind comparison test, per [[technical_performance_metrics]]).
> User override rate tracked via [[observability_stack]]: if > 30% of agent recommendations are overridden, [[model_governance_monitoring|scoring calibration review]] is triggered automatically.
