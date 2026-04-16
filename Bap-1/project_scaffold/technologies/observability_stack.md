---
tags: [technology, infrastructure, observability, monitoring, prometheus, grafana, opentelemetry, langsmith, tracing]
cssclasses: [procurement-doc, tech-doc]
status: "#processed"
related: ["[[agent_framework_langchain_langgraph]]", "[[llm_providers]]", "[[model_governance_monitoring]]", "[[technical_performance_metrics]]", "[[phase4_hardening_testing_production]]", "[[orchestration_kubernetes]]"]
---

# Observability Stack

> [!architecture] Full-Stack Monitoring Architecture
> The observability stack provides visibility at every layer: **Prometheus** for infrastructure metrics, **Grafana** for dashboards and alerting, **OpenTelemetry** for distributed tracing across all services, and **LangSmith** specifically for the LLM layer. This multi-layer approach means a slow procurement request can be traced from the [[frontend_react_nextjs|frontend]] click through every [[agent_framework_langchain_langgraph|agent step]], every Beckn API call, and every [[llm_providers|LLM invocation]].

## Tools

| Tool | Role |
|---|---|
| Prometheus | Metrics scraping and storage (Beckn API success rate, system health) |
| Grafana | Metrics visualization and alerting dashboards; [[technical_performance_metrics\|SLA monitoring]] |
| OpenTelemetry | Distributed tracing across all services (spans, traces) |
| LangSmith | LLM-specific tracing — prompts, outputs, latency, tokens, cost |

> [!tech-stack] Why LangSmith Alongside Standard Observability
> Standard distributed tracing (OpenTelemetry) covers HTTP spans and service latencies but cannot inspect the **content** of LLM calls. LangSmith fills this gap: it traces every [[llm_providers|GPT-4o/Claude]] invocation with its input prompt (version-stamped from [[model_governance_monitoring|Model Registry]]), output, latency, token count, and cost. This enables: debugging incorrect agent reasoning, optimizing prompt versions, and tracking cost per procurement request type.

## System Uptime Target

≥ 99.9% — enforced via Kubernetes health checks + Grafana alerts (see [[technical_performance_metrics]]).

## Key Monitored Metrics

| Metric | Tool | Target |
|---|---|---|
| Agent P95 response latency | OpenTelemetry | `< 5 seconds` |
| Beckn API success rate | Prometheus | `≥ 99.5%` |
| System uptime | K8s health + Grafana | `≥ 99.9%` |
| Intent parsing accuracy | LangSmith + eval pipeline | `≥ 95%` |
| Comparison quality vs. expert | Eval pipeline (weekly) | `≥ 85%` agreement |
| Catalog normalization success | Prometheus | `≥ 95%` |
| LLM token cost per request | LangSmith | Cost tracking / budget alerts |
| User override rate | [[databases_postgresql_redis\|PostgreSQL]] + dashboard | `< 25%` (12-month target) |

> [!milestone] Eval Pipeline Cadence
> Per [[model_governance_monitoring|Model Governance]]:
> - **Frequency:** Weekly automated run via [[cicd_pipeline|GitHub Actions]].
> - **Scope:** 100-scenario curated test suite.
> - **Metrics tracked:** Intent parsing accuracy, comparison quality, negotiation savings achieved, response latency.

> [!guardrail] Drift Detection Alerts
> Two automatic alert conditions managed by this stack and governed by [[model_governance_monitoring]]:
> - LLM accuracy `< 85%` on weekly evaluation suite → **prompt review triggered immediately**.
> - User override rate `> 30%` → **scoring calibration review triggered**.
> These thresholds are enforced as Grafana alert rules firing to [[communication_slack_teams|Slack]] and email.
