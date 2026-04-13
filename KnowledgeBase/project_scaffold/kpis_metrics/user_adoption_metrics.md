---
tags: [kpi, metrics, adoption, nps, user-engagement, override-rate, active-users, requests-volume]
cssclasses: [procurement-doc, metrics-doc]
status: "#processed"
related: ["[[business_impact_metrics]]", "[[technical_performance_metrics]]", "[[model_governance_monitoring]]", "[[communication_slack_teams]]", "[[frontend_react_nextjs]]", "[[analytics_dashboard]]"]
---

# KPIs: User Adoption Metrics

> [!insight] Adoption Is the Proof of Value
> Technical performance metrics ([[technical_performance_metrics]]) confirm the system works. Adoption metrics confirm it's **being used and trusted**. The agent recommendation acceptance rate — the fraction of agent recommendations that users act on without override — is the single most important signal: it measures whether users trust the system enough to delegate procurement decisions to it.

## Targets

| Metric | Target (6 months) | Target (12 months) |
|---|---|---|
| Active users (monthly) | **50+** across 3 enterprise pilots | **500+** across 15 enterprises |
| Requests processed via agent | **1,000 / month** | **10,000 / month** |
| Agent recommendation acceptance rate | **≥ 60%** | **≥ 75%** |
| User override rate | **< 40%** | **< 25%** |
| User satisfaction (NPS) | **≥ 30** | **≥ 50** |

## What Override Rate Signals

- High override rate (> 30%) → agent recommendations are not calibrated to enterprise preferences.
- **Triggers** [[model_governance_monitoring|model review]]: scoring calibration + prompt improvement.
- Every override is captured with a reason — aggregate data feeds back into [[comparison_scoring_model|scoring model calibration]] and [[intent_parsing_model|prompt refinement]].

> [!guardrail] Override Rate as a Governance Signal
> An override rate > 30% is not just an adoption problem — it is a **model governance trigger**. Per [[model_governance_monitoring]], it must result in a documented calibration review within 48 hours. Ignoring a high override rate allows the agent to continue making systematically wrong recommendations, eroding user trust and adoption. See also [[observability_monitoring]].

## Adoption Path

| Stage | Timeline | Milestone |
|---|---|---|
| Production-ready prototype | Weeks 13–16 | [[phase4_hardening_testing_production|Phase 4]] complete |
| Enterprise pilots | Months 1–6 | 3 enterprises, 50+ users, 1,000 requests/month |
| Scale | Months 7–12 | 15 enterprises, 500+ users, 10,000 requests/month |

## NPS Definition

- Score ≥ **30** at 6 months → product is meeting user needs; adoption likely to scale.
- Score ≥ **50** at 12 months → strong enterprise advocacy; referral-driven growth.

## Measurement

- Monthly active user counts: [[databases_postgresql_redis|PostgreSQL]] `user_sessions` table.
- Recommendation acceptance and override rates: [[audit_trail_system|audit trail events]] in Kafka/PostgreSQL.
- NPS: in-app survey (quarterly cadence) + [[analytics_dashboard|dashboard tracking]].

> [!milestone] 12-Month Revenue Gate
> Reaching 15 enterprises × 500 users × 10,000 requests/month at 12 months is the threshold required to support Infosys' conservative **$30–100M pipeline** projection from [[business_impact_metrics]]. Each metric in this file is a leading indicator toward that commercial target.
