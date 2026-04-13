---
tags: [integration, audit, splunk, servicenow, siem, compliance, sox, rti, kafka-sink, decision-logging]
cssclasses: [procurement-doc, integration-doc]
status: "#processed"
related: ["[[audit_trail_system]]", "[[event_streaming_kafka]]", "[[databases_postgresql_redis]]", "[[security_compliance]]", "[[story3_emergency_procurement]]", "[[story5_government_emarketplace]]", "[[phase3_advanced_intelligence_enterprise_features]]"]
---

# Integration: Audit & SIEM — Splunk / ServiceNow

> [!architecture] Role in the System
> Every agent decision is logged as a **structured Kafka event** (via [[audit_trail_system]]), then sinked to the enterprise's SIEM platform — Splunk or ServiceNow — where it becomes part of the corporate audit record. Critically, the event payload includes the agent's **reasoning**, not just the outcome. This transforms compliance documentation from a manual post-hoc exercise into an automatic real-time byproduct of system operation.

## Supported Platforms

| Platform | Role |
|---|---|
| Splunk | Enterprise SIEM — security event ingestion, full-text audit search, alert rules |
| ServiceNow | IT service management — compliance workflows, incident management, RTI reports |

## Data Flow

```
Agent Decision / Action
       ↓
[[event_streaming_kafka|Kafka]] (structured event with full reasoning payload)
       ↓
Splunk / ServiceNow Kafka consumer sink
       ↓
Indexed, searchable audit records
```

## Events Sunk to SIEM

- `/search` parameters and intent (from [[nl_intent_parser]])
- All seller responses received and normalization output (from [[beckn_bap_client]])
- [[comparison_scoring_engine|Comparison scores and reasoning]] for each seller
- [[negotiation_engine|Negotiation steps]]: counter-offers sent, responses received, strategy applied
- [[approval_workflow|Approval requests]], approver actions, timestamps
- `/confirm` execution details (seller, price, terms)
- **User overrides** — what the agent recommended vs. what the user chose, with override reason

## Compliance Use Cases

| Framework | Coverage |
|---|---|
| SOX Section 404 | Full financial control documentation; reasoning captured in real-time |
| GDPR | Data access logs, processing records; configurable retention via [[security_compliance\|policy]] |
| Government RTI ([[story5_government_emarketplace\|Story 5]]) | Full transparency report: all sellers, qualification reasoning, L1 selection justification |

> [!milestone] Phase 3 Acceptance (Weeks 9–12)
> From [[phase3_advanced_intelligence_enterprise_features|Phase 3 Audit Trail milestone]]:
> - Every agent action published as Kafka event with full reasoning payload.
> - Consumer sinks events to [[databases_postgresql_redis|PostgreSQL]] and Splunk/ServiceNow.
> - Full decision chain reconstructable from events alone.

> [!insight] Compliance Cost Reduction
> The Audit & SIEM integration eliminates approximately **2 weeks of manual documentation work** per audit cycle. In [[story3_emergency_procurement|Story 3]] (emergency PPE procurement), full audit compliance was maintained automatically under extreme time pressure — a scenario that historically resulted in audit flags and penalty risk. See [[business_impact_metrics]] for the 90% audit prep time reduction target.
