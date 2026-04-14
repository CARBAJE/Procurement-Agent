---
tags: [technology, infrastructure, kafka, event-streaming, event-driven, pub-sub, audit]
cssclasses: [procurement-doc, tech-doc]
status: "#processed"
related: ["[[databases_postgresql_redis]]", "[[vector_db_qdrant_pinecone]]", "[[audit_trail_system]]", "[[audit_splunk_servicenow]]", "[[real_time_tracking]]", "[[erp_integration]]", "[[data_pipeline_architecture]]"]
---

# Event Streaming — Apache Kafka

> [!architecture] Central Event Bus
> Apache Kafka is the **nervous system** of the procurement agent architecture. Every significant system event — Beckn seller responses, agent decisions, user interactions, order confirmations — is published to Kafka before being consumed by downstream processors. This decoupled, event-driven design means components never call each other directly; they publish and subscribe. The [[audit_trail_system]] is therefore a natural byproduct of the system's operation, not an afterthought.

## Rationale

- **Decoupled architecture** — no direct service-to-service calls for audit, ERP sync, or notifications.
- **Full audit trail** — every event is durable and replayable. [[audit_splunk_servicenow|Splunk/ServiceNow]] consumers can re-process events if needed.
- **Real-time streaming** — [[real_time_tracking|order tracking]], [[databases_postgresql_redis|PostgreSQL]] ingestion, and [[vector_db_qdrant_pinecone|vector DB learning]] all happen in parallel, not sequentially.
- **ERP decoupling** — [[erp_integration|SAP/Oracle sync]] happens asynchronously after `/confirm`, without blocking the confirmation response to the user.

## Event Types Published

| Event | Source | Consumers |
|---|---|---|
| Beckn `discover` responses | [[beckn_bap_client\|BAP Client]] | Catalog Normalizer, [[databases_postgresql_redis\|Redis]] cache |
| Agent decisions (with reasoning) | [[agent_framework_langchain_langgraph\|Agent Framework]] | [[databases_postgresql_redis\|PostgreSQL]] (audit), [[observability_stack\|LangSmith]] |
| User interactions (requests, selections, feedback) | [[frontend_react_nextjs\|Frontend]] | [[databases_postgresql_redis\|PostgreSQL]], [[vector_db_qdrant_pinecone\|Vector DB]] |
| Order confirmations (`/confirm`) | [[beckn_bap_client\|BAP Client]] | [[erp_integration\|ERP sync]], Notification service |
| Approval actions | [[approval_workflow\|Workflow engine]] | Agent, [[erp_integration\|ERP sync]], [[audit_trail_system\|Audit log]] |
| Delivery status (`/status`) | [[beckn_bap_client\|BAP Client]] | [[real_time_tracking\|Real-time tracking dashboard]] |

## Consumers

| Consumer | Purpose |
|---|---|
| [[databases_postgresql_redis\|PostgreSQL]] | Transactional storage + full audit trail |
| [[vector_db_qdrant_pinecone\|Qdrant]] | Agent memory and learning |
| Analytics engine | Dashboard metrics for [[analytics_dashboard]] |
| [[audit_splunk_servicenow\|Splunk / ServiceNow]] | Enterprise audit and compliance (SIEM sink) |
| Notification service | [[communication_slack_teams\|Slack/Teams/Email]] webhooks |

> [!milestone] Phase 3 Delivery (Weeks 9–12)
> The [[audit_trail_system]] is validated during [[phase3_advanced_intelligence_enterprise_features|Phase 3]]:
> - Every agent action published as a Kafka event with full reasoning payload.
> - Audit trail consumer sinks to PostgreSQL and [[audit_splunk_servicenow|Splunk]].
> - Full decision chain reconstructable from events alone (no application state required).

> [!guardrail] Event Durability
> Kafka topics for audit events must be configured with **replication factor ≥ 3** and **retention ≥ 7 years** to satisfy [[security_compliance|SOX Section 404]] audit retention requirements. Producer acknowledgment must be set to `acks=all` to prevent data loss on broker failure.
