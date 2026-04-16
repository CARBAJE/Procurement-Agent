---
tags: [infrastructure, observability, monitoring, prometheus, grafana, opentelemetry, langsmith, sla, alerting]
cssclasses: [procurement-doc, infra-doc]
status: "#processed"
related: ["[[observability_stack]]", "[[model_governance_monitoring]]", "[[technical_performance_metrics]]", "[[agent_framework_langchain_langgraph]]", "[[llm_providers]]", "[[cicd_pipeline]]", "[[phase4_hardening_testing_production]]"]
---

# Infrastructure: Observability & Monitoring

> [!architecture] Four-Layer Observability Model
> The monitoring stack operates across four distinct layers:
> 1. **Infrastructure metrics** ([[observability_stack|Prometheus]]) — CPU, memory, pod health, Beckn API call rates.
> 2. **Distributed tracing** (OpenTelemetry) — end-to-end request spans from [[frontend_react_nextjs|frontend]] click to [[beckn_bap_client|Beckn confirm]].
> 3. **LLM tracing** ([[observability_stack|LangSmith]]) — every [[llm_providers|GPT-4o/Claude]] call with prompt, output, latency, tokens, cost.
> 4. **Alerting** ([[observability_stack|Grafana]]) — SLA breach alerts → [[communication_slack_teams|Slack/email]]; drift detection alerts → [[model_governance_monitoring|model review]].

## Stack

| Tool | Role |
|---|---|
| Prometheus | Metrics scraping and storage |
| Grafana | Dashboards, alerting, SLA monitoring |
| OpenTelemetry | Distributed tracing across all services |
| LangSmith | LLM-specific tracing — prompts, outputs, latency, tokens, cost |

## SLA Targets (from [[technical_performance_metrics]])

| Metric | Tool | Target |
|---|---|---|
| Agent P95 response latency | OpenTelemetry | `< 5 seconds` |
| Beckn API success rate | Prometheus | `≥ 99.5%` |
| System uptime | K8s health + Grafana | `≥ 99.9%` |
| Intent parsing accuracy | LangSmith + eval pipeline | `≥ 95%` |
| Comparison quality | Eval pipeline (weekly) | `≥ 85%` agreement |
| Catalog normalization success | Prometheus | `≥ 95%` |
| LLM token cost per request | LangSmith | Budget alerts |
| User override rate | [[databases_postgresql_redis\|PostgreSQL]] + dashboard | `< 25%` (12-month) |

## LLM Evaluation Pipeline

Per [[model_governance_monitoring|Model Governance]]:
- **Frequency:** Weekly automated run via [[cicd_pipeline|GitHub Actions]].
- **Scope:** 100-scenario curated test suite.
- **Metrics:** Intent parsing accuracy, comparison quality, negotiation savings, response latency.

> [!guardrail] Drift Detection Alerts
> Two automatic alert conditions firing to [[communication_slack_teams|Slack]] and [[audit_splunk_servicenow|ServiceNow]]:
> - LLM accuracy `< 85%` on evaluation suite → **immediate prompt review**.
> - User override rate `> 30%` → **scoring calibration review**.
> These are not optional — per [[model_governance_monitoring]], all drift events must be investigated within 48 hours.

> [!insight] LangSmith ROI
> LangSmith's per-call cost tracing typically identifies **20–35% LLM cost reduction** opportunities within the first month of production use — by revealing which prompts are unnecessarily verbose and which tasks can be routed to cheaper models ([[llm_providers|GPT-4o-mini]]). At 10,000 requests/month target ([[user_adoption_metrics]]), this becomes a significant operating cost factor.
