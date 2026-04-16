---
tags: [integration, erp, sap, oracle, odata, rest-api, po-sync, budget-check, bidirectional]
cssclasses: [procurement-doc, integration-doc]
status: "#processed"
related: ["[[erp_integration]]", "[[event_streaming_kafka]]", "[[databases_postgresql_redis]]", "[[approval_workflow]]", "[[audit_trail_system]]", "[[phase3_advanced_intelligence_enterprise_features]]", "[[story2_high_value_it_equipment]]"]
---

# Integration: ERP Systems — SAP S/4HANA & Oracle ERP Cloud

> [!architecture] Integration Architecture
> The ERP integration is implemented as a **Kafka-consumer middleware** — after `/confirm`, the procurement agent publishes an order event to [[event_streaming_kafka|Kafka]], and the ERP sync consumer translates it into an OData (SAP) or REST (Oracle) API call to create the purchase order. Budget checks flow in the opposite direction: the agent calls the ERP synchronously before `/confirm` to verify budget availability in real-time.

## SAP S/4HANA

| Attribute | Detail |
|---|---|
| Protocol | OData APIs |
| Integration type | Bidirectional |
| Data out | POs created by [[erp_integration\|agent]] pushed to SAP |
| Data in | Budget availability (real-time); goods receipt; invoice matching |

## Oracle ERP Cloud

| Attribute | Detail |
|---|---|
| Protocol | REST APIs |
| Integration type | Bidirectional |
| Data out | POs pushed to Oracle after `/confirm` |
| Data in | Budget availability (real-time); goods receipt; invoice matching |

## Integration Flows

### Budget Check (Pre-Confirm)

1. Agent intends to execute `/confirm`.
2. [[erp_integration|ERP middleware]] queries SAP/Oracle for real-time budget availability in the relevant cost center.
3. Budget available → agent proceeds to `/confirm`.
4. Budget insufficient → [[approval_workflow|requester notified]]; order held.

### PO Push (Post-Confirm)

1. Agent executes `/confirm`.
2. [[event_streaming_kafka|Kafka]] event published → ERP sync consumer triggered.
3. PO created in ERP with all order details (seller, items, quantities, agreed price, delivery terms).

### Inbound Updates

1. ERP publishes goods receipt event → [[databases_postgresql_redis|PostgreSQL]] order status updated.
2. Invoice matching result → order record updated.

> [!milestone] Phase 3 Acceptance (Weeks 9–12)
> From [[phase3_advanced_intelligence_enterprise_features|Phase 3 ERP Integration milestone]]:
> - POs created by agent appear in SAP/Oracle within minutes of `/confirm`.
> - Real-time budget checks return correct values from ERP.
> - Budget validation confirmed as a hard prerequisite to `/confirm`.

> [!guardrail] ERP Sync Failure Handling
> If the ERP sync consumer fails to create the PO (network error, ERP unavailable), the order is **not silently dropped** — the failure is published back to a dead-letter Kafka topic, an alert fires via [[observability_stack|Prometheus/Grafana]], and the procurement admin is notified via [[communication_slack_teams|Slack/Teams]]. The Beckn order is already confirmed (supplier committed), so the PO must be created to prevent financial reconciliation gaps. Retry logic with exponential backoff is implemented.
