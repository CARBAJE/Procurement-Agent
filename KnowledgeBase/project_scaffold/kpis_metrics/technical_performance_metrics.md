---
tags: [kpi, metrics, performance, latency, accuracy, uptime, beckn-api, normalization, evaluation]
cssclasses: [procurement-doc, metrics-doc]
status: "#processed"
related: ["[[observability_stack]]", "[[observability_monitoring]]", "[[model_governance_monitoring]]", "[[phase4_hardening_testing_production]]", "[[nl_intent_parser]]", "[[comparison_scoring_engine]]", "[[beckn_bap_client]]"]
---

# KPIs: Technical Performance Metrics

> [!insight] System SLA Summary
> The procurement agent must deliver **sub-5-second P95 response latency** while maintaining **≥ 99.5% Beckn API success rate** and **≥ 99.9% system uptime**. These targets are not aspirational — they are the baseline required for enterprise production deployment. Every target is measured by the [[observability_stack|observability stack]] and reviewed weekly.

## Targets & Measurement

| Metric | Target | Measurement Method |
|---|---|---|
| Agent response time (intent to recommendation) | `< 5 seconds` (P95) | [[observability_stack\|OpenTelemetry]] distributed tracing |
| Intent parsing accuracy | `≥ 95%` | Weekly evaluation — 100-scenario test suite ([[model_governance_monitoring]]) |
| Comparison quality vs. human expert ranking | `≥ 85%` agreement | Blind comparison test: agent vs. expert rankings |
| Beckn API success rate | `≥ 99.5%` | [[observability_stack\|Prometheus]] monitoring of API call outcomes |
| System uptime | `≥ 99.9%` | [[orchestration_kubernetes\|Kubernetes]] health checks + [[observability_stack\|Grafana]] alerts |
| Catalog normalization success rate | `≥ 95%` | Automated schema validation on `discover` responses |

## Performance Optimization ([[phase4_hardening_testing_production|Phase 4]])

- [[databases_postgresql_redis|Redis]] caching reduces redundant Beckn network calls by **≥ 50%**.
- P95 latency target `< 5 seconds` for standard procurement requests (e.g., [[story1_routine_office_supply|Story 1]]).
- Phase 4 acceptance: caching efficiency and P95 latency both confirmed under load testing.

## Evaluation Suite ([[phase4_hardening_testing_production|Phase 4]])

- 20+ procurement scenarios with ground-truth scoring.
- Agent must achieve **≥ 85%** accuracy across the suite.
- Run as part of [[cicd_pipeline|GitHub Actions CI/CD pipeline]].

> [!guardrail] Drift Detection Thresholds
> Governed by [[model_governance_monitoring]]:
> | Condition | Alert | Required Action |
> |---|---|---|
> | Accuracy `< 85%` on eval suite | Automatic alert | Prompt review within 48 hours |
> | User override rate `> 30%` | Automatic alert | Scoring calibration review |
> | Beckn API success rate `< 99.5%` | Prometheus alert | Investigate [[beckn_bap_client\|BAP client]] / network |
> | System uptime `< 99.9%` | Grafana alert | Kubernetes pod restart + escalation |
> All alerts fire to [[communication_slack_teams|Slack]] and create a [[audit_splunk_servicenow|ServiceNow]] ticket.

> [!milestone] Phase 4 Measurement Confirmation
> All six technical performance metrics must be confirmed under representative load before [[phase4_hardening_testing_production|Phase 4]] is declared complete. Load testing uses a simulated workload matching the 6-month pilot volume: 1,000 requests/month across 3 enterprise pilots (per [[user_adoption_metrics]]).
