---
tags: [component, integration, sap, oracle, erp, odata, rest, bidirectional, po-sync, budget-check]
cssclasses: [procurement-doc, component-doc]
status: "#processed"
related: ["[[erp_sap_oracle]]", "[[event_streaming_kafka]]", "[[databases_postgresql_redis]]", "[[approval_workflow]]", "[[audit_trail_system]]", "[[phase3_advanced_intelligence_enterprise_features]]", "[[story2_high_value_it_equipment]]"]
---

# Component: ERP Integration

> [!architecture] Role in the System
> The ERP Integration middleware provides **bidirectional synchronization** between the procurement agent and enterprise ERP systems (SAP S/4HANA and Oracle ERP Cloud). It serves two critical functions: (1) **pre-confirm budget check** — the agent queries the ERP for real-time budget availability before executing `/confirm`, preventing overspend; and (2) **post-confirm PO push** — after `/confirm`, the agent creates the purchase order in the ERP automatically, eliminating manual re-entry. All sync operations are event-driven via [[event_streaming_kafka|Apache Kafka]].

## Supported ERPs

| System | API Protocol | Integration Type |
|---|---|---|
| SAP S/4HANA | OData APIs | Bidirectional |
| Oracle ERP Cloud | REST APIs | Bidirectional |

Full integration specification: [[erp_sap_oracle]].

## Integration Flows

### Outbound (Agent → ERP)

- POs created by the agent after `/confirm` are pushed to the ERP system.
- Budget availability checked in ERP **in real-time** before `/confirm` is executed.

### Inbound (ERP → Agent)

- Goods receipt updates flow back from ERP → update procurement status in [[databases_postgresql_redis|PostgreSQL]].
- Invoice matching results returned → update order records.
- Budget consumption updated after each order confirmation.

## Data Flow

```
Agent executes /confirm
       ↓
Kafka event published
       ↓
ERP sync consumer triggered
       ↓
  ┌────────────────────┐
  SAP OData / Oracle REST
  (PO created in ERP)
```

> [!milestone] Phase 3 Acceptance (Weeks 9–12)
> From [[phase3_advanced_intelligence_enterprise_features|Phase 3 ERP Integration milestone]]:
> - POs created by agent appear correctly in ERP within minutes of `/confirm`.
> - Budget checks return real-time values from ERP.
> - Budget validation confirmed before `/confirm` execution.

> [!guardrail] Budget Check Is Mandatory
> The agent **cannot** execute `/confirm` without a successful real-time budget check from the ERP. If the budget check fails (insufficient budget, cost center not found, ERP unavailable), the order is held and the [[approval_workflow|requester is notified]] with context. This prevents financial overcommitment even when the [[approval_workflow|approval workflow]] has already approved the order.
