---
tags: [technology, ai, llm, gpt4o, claude, openai, multi-provider, model-routing]
cssclasses: [procurement-doc, tech-doc]
status: "#processed"
related: ["[[nl_intent_parser]]", "[[comparison_scoring_engine]]", "[[negotiation_engine]]", "[[embedding_models]]", "[[model_governance_monitoring]]", "[[observability_stack]]", "[[agent_framework_langchain_langgraph]]"]
---

# LLM Providers

> [!architecture] Multi-Provider Strategy
> The system uses a **multi-provider LLM architecture** for resilience and cost optimization. Model routing is based on task complexity and latency requirements. No single provider is a single point of failure. All calls are traced by [[observability_stack|LangSmith]] and governed by the [[model_governance_monitoring|Model Registry]].

## Provider Matrix

| Model | Provider | Role | Trigger |
|---|---|---|---|
| `gpt-4o` | OpenAI | Primary — [[nl_intent_parser\|intent parsing]], [[comparison_scoring_engine\|comparison reasoning]], [[negotiation_engine\|negotiation strategy]] | All complex multi-step reasoning |
| `claude-sonnet-4-6` | Anthropic | Fallback for intent parsing | When GPT-4o unavailable or latency spike detected |
| `gpt-4o-mini` | OpenAI | Lightweight tasks — simple, well-structured requests | High-volume routine calls; reduces cost by ~70% |

## Per-Component Assignment

| Component | Primary Model | Fallback |
|---|---|---|
| [[nl_intent_parser\|NL Intent Parser]] | `gpt-4o` (JSON mode / structured output) | `claude-sonnet-4-6` |
| [[comparison_scoring_engine\|Comparison & Scoring Engine]] | `gpt-4o` (ReAct reasoning loop) | — |
| [[negotiation_engine\|Negotiation Strategy]] | Rule-based engine + `gpt-4o` for ambiguous cases | — |
| [[embedding_models\|Memory & Retrieval]] | `text-embedding-3-large` (embeddings, not generation) | `e5-large-v2` (open-source) |

> [!tech-stack] Why Multi-Provider
> Relying on a single LLM provider creates a single point of failure for all agent intelligence. The `gpt-4o` → `claude-sonnet-4-6` fallback for [[nl_intent_parser|intent parsing]] ensures the most critical pipeline step (converting natural language to Beckn JSON) stays operational even during OpenAI outages. `gpt-4o-mini` handles high-frequency simple requests, keeping per-request LLM cost sustainable at 10,000+ monthly requests ([[user_adoption_metrics|12-month target]]).

> [!milestone] Evaluation Cadence
> Weekly automated evaluation against 100-scenario test suite, governed by [[model_governance_monitoring]]:
> - Intent parsing accuracy target: **≥ 95%**
> - Comparison quality vs. human expert: **≥ 85% agreement**
> Run via [[cicd_pipeline|GitHub Actions]] as part of the CI/CD pipeline.

## Configuration Management

- All model versions, prompt templates, and temperature settings are tracked in the [[model_governance_monitoring|Model Registry]] (version-controlled).
- Every agent response is traceable to a specific **model version + prompt version**.
- [[observability_stack|LangSmith]] traces every LLM call: input, output, latency, token usage, cost.

> [!guardrail] Drift Detection
> If intent parsing accuracy drops below **85%** on the weekly evaluation suite → automatic alert triggers prompt review.
> If user override rate exceeds **30%** → scoring calibration review is triggered.
> No model or prompt change is deployed without passing the 100-scenario evaluation suite. Governed by [[model_governance_monitoring]].
