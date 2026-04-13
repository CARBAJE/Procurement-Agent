---
tags: [ai-model, negotiation, strategy, rule-based, reinforcement-learning, per-category, safety-guardrails]
cssclasses: [procurement-doc, ai-doc]
status: "#processed"
related: ["[[negotiation_engine]]", "[[llm_providers]]", "[[agent_memory_learning]]", "[[model_governance_monitoring]]", "[[phase3_advanced_intelligence_enterprise_features]]", "[[story1_routine_office_supply]]", "[[business_impact_metrics]]"]
---

# AI Model: Negotiation Strategy

> [!architecture] Role in the AI Stack
> The Negotiation Strategy Model determines **what counter-offer terms to propose** via Beckn's `/select` flow. It operates inside the [[negotiation_engine]] component and is designed for progressive sophistication: Phase 1 uses expert-defined rules; later phases add reinforcement learning from actual negotiation outcomes stored in [[agent_memory_learning|vector memory]].

## Architecture

| Phase | Approach |
|---|---|
| Phase 1 (initial) | Expert-defined rule-based engine, configurable per procurement category |
| Phase 2+ | Reinforcement learning (RL) from negotiation outcomes refines strategies over time |
| Ambiguous cases | [[llm_providers\|GPT-4o]] for strategy selection when rules don't clearly apply |

## Rule-Based Strategy Types

| Strategy | Trigger | Action |
|---|---|---|
| Counter-offer | Commodity category, price above budget | Send `/select` with `X%` discount (max 20%) |
| Accept within margin | Price within `N%` of budget threshold | Accept without counter-offer |
| Escalate to human | Gap exceeds configured limit | Route to [[approval_workflow\|procurement manager]] |
| Advisory only | Specialized/high-value category | Recommendation without transaction |

> [!tech-stack] Per-Category Configuration
> Enterprise admin configures strategies per procurement category via the admin dashboard. Examples:
> - **Office supplies** → aggressive automated negotiation (commodity, price-sensitive).
> - **Enterprise IT equipment** → advisory mode (specialized, relationship-sensitive).
> - **Medical devices** → advisory mode + compliance-first scoring.
> This per-category model ensures the agent's behavior is appropriate for the commercial context, not a one-size-fits-all approach.

## Learning (Phase 2+)

- Negotiation outcomes (accepted price, rejected counter-offers, final terms) stored in [[vector_db_qdrant_pinecone|Qdrant]] via [[agent_memory_learning]].
- RL model updates strategy weights based on what works with specific seller segments.
- Target: **8–15% avg. cost reduction** vs. list price (90-day rolling window, per [[business_impact_metrics]]).

> [!milestone] Phase 3 Acceptance
> From [[phase3_advanced_intelligence_enterprise_features|Phase 3 Negotiation Engine milestone]]:
> - Configurable strategies work correctly per category.
> - Negotiation outcomes logged to [[audit_trail_system|audit events]].
> - [[observability_stack|LangSmith]] traces each negotiation step.

> [!guardrail] Hard Safety Limits
> These limits are **non-negotiable** and enforced in code before any `/select` call is made:
> - Maximum discount request: **20%** — agent cannot request more.
> - Agent cannot agree to terms outside pre-defined policy boundaries.
> - All negotiation actions require policy compliance check before execution.
> - Violations are rejected and logged to [[audit_trail_system]].
> These guardrails prevent the agent from committing the enterprise to terms that violate procurement policy, even in edge cases.
