---
tags: [infrastructure, data-pipeline, kafka, etl, streaming, batch, postgresql, qdrant, redis]
cssclasses: [procurement-doc, infra-doc]
status: "#processed"
related: ["[[event_streaming_kafka]]", "[[databases_postgresql_redis]]", "[[vector_db_qdrant_pinecone]]", "[[embedding_models]]", "[[erp_integration]]", "[[audit_trail_system]]", "[[agent_memory_learning]]"]
---

# Infrastructure: Data Pipeline Architecture

> [!architecture] Central Event Bus — Apache Kafka
> All data flows are **event-driven through [[event_streaming_kafka|Apache Kafka]]**. No direct point-to-point service coupling. Every significant event is published to Kafka, and independent consumers process these events for different purposes — [[databases_postgresql_redis|PostgreSQL]] for transactional storage, [[vector_db_qdrant_pinecone|Qdrant]] for agent memory, the [[analytics_dashboard|analytics engine]] for dashboards, and [[audit_splunk_servicenow|Splunk/ServiceNow]] for compliance audit.

## Data Sources & Pipeline

| Data Source | Type | Volume | Freshness | Processing |
|---|---|---|---|---|
| Beckn/ONDC Catalog Responses | Semi-structured JSON (sync discover response) | Matching offerings per discover query | Real-time | Normalize → Score → Cache ([[databases_postgresql_redis\|Redis]], 15-min TTL) |
| Enterprise Procurement History | Structured (ERP exports, DB records) | 50K–500K records | Daily batch sync | ETL → [[databases_postgresql_redis\|PostgreSQL]] → Embed → [[vector_db_qdrant_pinecone\|Qdrant]] |
| User Interaction Logs | Semi-structured (request text, selections, feedback) | 1K–10K events/day | Real-time streaming | [[event_streaming_kafka\|Kafka]] → PostgreSQL (audit) + Qdrant (learning) |
| Supplier Performance Data | Structured (ratings, delivery metrics, certifications) | Aggregated ONDC + internal | Weekly aggregation | Batch → Supplier scoring model update |

## Full Pipeline Flow

```
Beckn discover responses ──→ Kafka ──→ Catalog Normalizer ──→ Redis cache (15-min TTL)
                                      ↓
                               Comparison Engine ──→ PostgreSQL (offers table)

User interactions ────────────→ Kafka ──→ PostgreSQL (audit log)
                                      ↓
                               Qdrant (agent learning + memory)

Agent decisions ──────────────→ Kafka ──→ PostgreSQL (audit trail with reasoning)
                                      ↓
                               Splunk / ServiceNow (SIEM sink)

/confirm events ──────────────→ Kafka ──→ ERP sync consumer (SAP OData / Oracle REST)
                                      ↓
                               Notification service (Slack/Teams/Email)
```

## Caching Strategy

- [[databases_postgresql_redis|Redis 7]] with **15-minute TTL** for Beckn catalog responses.
- [[phase4_hardening_testing_production|Phase 4 target]]: caching reduces redundant Beckn network calls by ≥ **50%**.

> [!tech-stack] Why Event-Driven Architecture
> Each data consumer (audit log, ERP sync, agent learning, analytics) has completely different latency and processing requirements. [[event_streaming_kafka|Kafka's]] pub/sub model lets each consumer operate at its own pace without blocking others. The `/confirm` action — which triggers ERP sync, audit logging, and notification simultaneously — would require sequential orchestration without Kafka, adding latency for the user.

> [!guardrail] Pipeline Reliability
> Kafka topics for audit events require **replication factor ≥ 3** and **retention ≥ 7 years** ([[security_compliance|SOX audit retention]]). The ETL pipeline from ERP exports to [[vector_db_qdrant_pinecone|Qdrant]] must be idempotent — re-running it must not create duplicate vector records. All pipeline failures are logged to [[observability_stack|Prometheus/Grafana]] with alerting.
