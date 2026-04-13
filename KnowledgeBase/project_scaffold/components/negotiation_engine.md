---
tags: [component, ai, negotiation, automation, beckn, select, strategy, reinforcement-learning]
cssclasses: [procurement-doc, component-doc]
status: "#processed"
related: ["[[beckn_bap_client]]", "[[llm_providers]]", "[[approval_workflow]]", "[[audit_trail_system]]", "[[phase3_advanced_intelligence_enterprise_features]]", "[[negotiation_strategy_model]]", "[[story1_routine_office_supply]]"]
---

# Component: Negotiation Engine

> [!architecture] Role in the System
> The Negotiation Engine automates price and delivery term negotiation with sellers using Beckn's `/select` flow. After the [[comparison_scoring_engine]] ranks sellers, the agent invokes the negotiation engine to send counter-offers to the top candidates before proceeding to `/init`. This component is what transforms the system from a "smart search tool" into a genuine autonomous procurement agent — it actively improves the deal rather than just selecting the best available option.

## Mechanism

Beckn's `/select` flow supports term modification — the buyer proposes different prices, quantities, or delivery terms. The negotiation engine drives this via [[beckn_bap_client|BAP Client]].

## Strategy Types

| Strategy | Trigger Condition | Action |
|---|---|---|
| Counter-offer | Commodity category, price above budget | Send `/select` with `X%` discount request |
| Accept within margin | Price within `N%` of budget | Accept without counter-offer |
| Escalate to human | Gap exceeds configured limit | Route to [[approval_workflow\|procurement manager]] |
| Advisory only | Specialized/high-value category | No negotiation; provide recommendation only |

> [!tech-stack] Strategy Configuration Model
> Strategies are configured **per procurement category** by the enterprise via the admin interface. Full spec in [[negotiation_strategy_model]].
> - Commodity items (office supplies, stationery) → aggressive automated negotiation.
> - Specialized equipment (enterprise laptops, medical devices) → advisory mode, human decides.
> - [[llm_providers|GPT-4o]] provides strategy selection guidance for ambiguous cases where rules don't clearly apply.

## Example (Story 1 — Office Supply)

From [[story1_routine_office_supply|Story 1]]:
- Agent counter-offers top 3 sellers via `/select` with 5% discount.
- Seller B accepts ₹180/ream (from ₹189/ream listed).
- Total: ₹90,000 — within auto-approval threshold → proceeds directly to `/confirm`.

## Learning

- Phase 1: Expert-defined rules.
- Phase 2+: Reinforcement learning from negotiation outcomes refines strategies (see [[negotiation_strategy_model]]).
- Outcomes stored in [[vector_db_qdrant_pinecone|Qdrant]] → retrieved by [[agent_memory_learning]] for future decisions.

> [!milestone] Phase 3 Acceptance (Weeks 9–12)
> From [[phase3_advanced_intelligence_enterprise_features|Phase 3 Negotiation Engine milestone]]:
> - Agent negotiates price and delivery terms autonomously.
> - Configurable strategies work correctly per category.
> - Negotiation actions logged with full reasoning to [[audit_trail_system|Kafka audit events]].

> [!guardrail] Hard Negotiation Limits
> From [[negotiation_strategy_model]]:
> - Maximum discount request hard-capped at **20%** — agent cannot request more.
> - Agent **cannot** agree to terms outside pre-defined policy boundaries.
> - All negotiation actions require policy compliance check before execution.
> - Violations are rejected and logged to [[audit_trail_system]].
