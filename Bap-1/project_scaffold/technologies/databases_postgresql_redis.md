---
tags: [technology, database, postgresql, redis, caching, transactional, sql]
cssclasses: [procurement-doc, tech-doc]
status: "#processed"
related: ["[[event_streaming_kafka]]", "[[vector_db_qdrant_pinecone]]", "[[audit_trail_system]]", "[[cloud_providers]]", "[[security_compliance]]", "[[data_pipeline_architecture]]"]
---

# Databases — PostgreSQL 16 & Redis 7

> [!architecture] Data Storage Architecture
> The database layer consists of two complementary stores: **PostgreSQL 16** as the transactional source-of-truth (procurement records, audit events, orders) and **Redis 7** as the in-memory cache (Beckn catalog responses, session state). All events flow through [[event_streaming_kafka|Apache Kafka]] before landing in PostgreSQL, ensuring the audit trail is complete and decoupled. The [[vector_db_qdrant_pinecone|vector database (Qdrant)]] handles the agent memory layer separately.

---

## PostgreSQL 16

| Attribute | Detail |
|---|---|
| Role | Primary transactional database |
| Version | 16 |
| Rationale | Proven enterprise RDBMS; ACID compliance for procurement records and audit events |
| Hosted on | Enterprise cloud — [[cloud_providers\|AWS Mumbai / Azure India]] (for data residency compliance) |
| Encryption | AES-256 at rest; KMS-managed keys (see [[security_compliance]]) |

> [!tech-stack] Why PostgreSQL 16
> PostgreSQL provides ACID guarantees critical for financial transactions — an approved order that fails mid-write cannot be silently lost. Version 16 introduces performance improvements for concurrent read/write workloads and better JSON handling for storing Beckn response payloads. Self-hosted within the enterprise cloud boundary satisfies [[security_compliance|data residency requirements]] (procurement data must stay within the enterprise's jurisdiction).

### Schema Covers

- Procurement requests (intent, requester, timestamp, status)
- Seller offers (normalized from Beckn v2 `discover` responses)
- Orders (selected seller, confirmed terms, ERP sync status)
- Audit events (every agent decision with reasoning payload — fed from [[event_streaming_kafka|Kafka]])
- Approval workflow state (routing, approver, action, timestamp)
- User interaction logs (selections, overrides, override reasons)
- ERP sync status (pending, synced, failed, reconciled)

### Data Pipeline Ingestion

- Beckn events → [[event_streaming_kafka|Kafka]] → PostgreSQL (transactional + audit)
- [[erp_integration|ERP daily batch sync]] → ETL → PostgreSQL → Embed → [[vector_db_qdrant_pinecone|Vector DB]]
- User interaction logs → Kafka → PostgreSQL (audit) + Vector DB (learning)

---

## Redis 7

| Attribute | Detail |
|---|---|
| Role | Caching and session state |
| Version | 7 |
| Rationale | Low-latency key-value store for catalog cache and active session data |
| Cache TTL | 15-minute TTL for Beckn catalog responses |

### Use Cases

- **Beckn catalog caching** — `normalize(discover_response)` cached with 15-min TTL. Phase 4 target: reduces redundant Discovery Service calls by ≥ 50%.
- **Session state** — active procurement request context for the [[agent_framework_langchain_langgraph|agent]] across multi-step workflows.
- **Rate-limiting counters** — shared across horizontally-scaled [[api_gateway|Kong Gateway]] pods.

> [!guardrail] Data Residency
> Both PostgreSQL and Redis are deployed **within the enterprise cloud boundary** ([[cloud_providers|AWS Mumbai / Azure India]]). No procurement data transits through external managed database services. Encryption at rest is enforced via AES-256 with KMS-managed key rotation — see [[security_compliance]].
