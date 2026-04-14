---
tags: [component, compliance, audit, kafka, splunk, sox, gdpr, rti, decision-logging, explainability]
cssclasses: [procurement-doc, component-doc]
status: "#processed"
related: ["[[event_streaming_kafka]]", "[[databases_postgresql_redis]]", "[[audit_splunk_servicenow]]", "[[observability_stack]]", "[[phase3_advanced_intelligence_enterprise_features]]", "[[security_compliance]]", "[[story3_emergency_procurement]]", "[[story5_government_emarketplace]]"]
---

# Component: Audit Trail System

> [!architecture] Role in the System
> The Audit Trail System captures **every agent decision with its reasoning** as a durable, structured event — not just the outcome. This is architecturally fundamental: the system does not reconstruct reasoning after the fact (as manual procurement does), it captures it in real-time during the decision process. The trail flows through [[event_streaming_kafka|Apache Kafka]] to [[databases_postgresql_redis|PostgreSQL]] and [[audit_splunk_servicenow|Splunk/ServiceNow]], making it queryable both for operational dashboards and regulatory audits.

## Architecture

```
Agent Decision / Action
       ↓
Kafka (structured event with full reasoning payload)
       ↓
  ┌────────────────┬───────────────────┐
  ↓                ↓                   ↓
PostgreSQL    Splunk / ServiceNow   LangSmith
(transactional  (SIEM sink for         (LLM-level
 audit log)      compliance)            trace)
```

## Events Logged

| Event | Detail Captured |
|---|---|
| `discover` query | Intent parameters, timestamp, Discovery Service target |
| `discover` response | All returned offerings, normalization result |
| Comparison scoring | Per-seller scores across all dimensions + explanation text |
| [[negotiation_engine\|Negotiation steps]] | Counter-offer sent, seller response, strategy applied |
| [[approval_workflow\|Approval routing]] | Who notified, when, action taken |
| `/confirm` execution | Final order details, seller, total value |
| User overrides | Agent recommendation vs. user choice + override reason |

## Compliance Coverage

| Framework | How Audit Trail Satisfies It |
|---|---|
| SOX Section 404 | Real-time decision trail with reasoning — no post-hoc reconstruction |
| GDPR | Data processing records; configurable retention per [[security_compliance\|policy]] |
| Government RTI ([[story5_government_emarketplace\|Story 5]]) | Full transparency: all sellers considered, qualification reasoning, L1 justification |

> [!milestone] Phase 3 Acceptance (Weeks 9–12)
> From [[phase3_advanced_intelligence_enterprise_features|Phase 3 Audit Trail milestone]]:
> - Every agent action logged as a Kafka event with full reasoning payload.
> - Audit trail consumer sinks events to [[databases_postgresql_redis|PostgreSQL]] and [[audit_splunk_servicenow|Splunk]].
> - Full decision chain reconstructable from events alone (no application state required).

> [!insight] Business Impact
> The Audit Trail System eliminates approximately **2 weeks of compliance documentation effort** per audit cycle — reasoning is captured in real-time, not reconstructed under time pressure. In [[story3_emergency_procurement|Story 3]] (emergency PPE procurement), the system maintained full audit compliance automatically even when Anita was under extreme time pressure — a historically recurring audit failure mode. See [[business_impact_metrics]] for the 90% reduction target.
