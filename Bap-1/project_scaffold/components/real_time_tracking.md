---
tags: [component, frontend, tracking, websocket, status-polling, webhooks, real-time, notifications]
cssclasses: [procurement-doc, component-doc]
status: "#processed"
related: ["[[beckn_bap_client]]", "[[event_streaming_kafka]]", "[[databases_postgresql_redis]]", "[[communication_slack_teams]]", "[[frontend_react_nextjs]]", "[[phase2_core_intelligence_transaction_flow]]", "[[story2_high_value_it_equipment]]"]
---

# Component: Real-Time Order Tracking

> [!architecture] Role in the System
> Real-Time Tracking delivers **live order delivery status** to users via the [[frontend_react_nextjs|dashboard]] and [[communication_slack_teams|notification channels]]. It combines two input streams — Beckn `/status` polling (agent-initiated) and seller webhooks (seller-pushed) — with a WebSocket push mechanism to the frontend. The result: the dashboard always reflects the latest order status within 30 seconds of any change, without the user needing to refresh.

## Implementation

- **Beckn `/status` polling** — [[beckn_bap_client|BAP Client]] periodically polls Beckn for order status updates from the seller.
- **Webhooks** — sellers push status change events directly to the system endpoint.
- **WebSockets** — [[frontend_react_nextjs|frontend dashboard]] maintains a WebSocket connection; status updates are pushed server-to-client in real-time.

## Data Flow

```
Beckn /status response  OR  Seller webhook push
              ↓
       BAP Client (aiohttp)
              ↓
      Kafka event published
              ↓
  ┌──────────────┬──────────────────┐
  ↓              ↓                  ↓
PostgreSQL   WebSocket push    Notification
(audit log)  (dashboard)       (Slack/Teams)
```

> [!milestone] Phase 2 Acceptance (Weeks 5–8)
> From [[phase2_core_intelligence_transaction_flow|Phase 2 Real-time Tracking milestone]]:
> - Dashboard reflects order status within **30 seconds** of any status change.
> - Both `/status` polling and webhook push paths validated against Beckn sandbox.

## Notification Channels

| Channel | Events Pushed |
|---|---|
| [[communication_slack_teams\|Slack / Teams]] | Approval requests, order confirmations, delivery updates, exception alerts |
| Email | Order confirmation, delivery updates |
| Dashboard | All events in real-time via WebSocket |

## User Experience ([[story2_high_value_it_equipment|Story 2 — IT Equipment]])

Rajesh sees delivery progress for 200 enterprise laptops on the dashboard in real-time after `/confirm`. Status flows: Beckn `/status` → [[event_streaming_kafka|Kafka]] → [[databases_postgresql_redis|PostgreSQL]] (audit) → WebSocket → Dashboard.

> [!insight] Impact on Procurement Experience
> Real-time tracking eliminates the need for follow-up emails and phone calls to suppliers — historically a significant time sink for procurement teams. The [[story1_routine_office_supply|45-second end-to-end Story 1 procurement cycle]] is only valuable if the team can also trust and monitor delivery in real-time without manual effort.
