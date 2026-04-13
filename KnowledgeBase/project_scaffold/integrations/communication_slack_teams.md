---
tags: [integration, communication, slack, teams, email, notifications, webhooks, conversational-interface]
cssclasses: [procurement-doc, integration-doc]
status: "#processed"
related: ["[[approval_workflow]]", "[[real_time_tracking]]", "[[frontend_react_nextjs]]", "[[nl_intent_parser]]", "[[story1_routine_office_supply]]", "[[story2_high_value_it_equipment]]", "[[story3_emergency_procurement]]"]
---

# Integration: Communication — Slack / Teams / Email

> [!architecture] Role in the System
> The communication integration serves two distinct functions: (1) **Notification delivery** — pushing procurement events (approvals, confirmations, delivery updates, alerts) to users where they already work (Slack/Teams/Email); and (2) **Conversational interface** — allowing users to submit procurement requests and receive responses directly in Slack or Teams, without opening the [[frontend_react_nextjs|procurement dashboard]]. The [[nl_intent_parser]] handles natural language requests regardless of whether they arrive from the dashboard or a chat message.

## Channels

| Channel | Protocol | Use |
|---|---|---|
| Slack | Webhook / Slack API | Notification delivery; conversational interface |
| Microsoft Teams | Webhook / Graph API | Notification delivery; conversational interface |
| Email | SMTP | Order confirmations, escalations, periodic summaries |

## Notification Types

| Event | Recipients | Channel |
|---|---|---|
| [[approval_workflow\|Approval request]] | Designated approver (manager / CFO) | Slack + Teams + Email |
| Order confirmation | Requester | Slack with full comparison, reasoning, and order details |
| [[real_time_tracking\|Delivery status update]] | Requester | Slack / dashboard |
| Exception alert | Procurement admin | Slack / Teams |
| Emergency auto-approve countdown ([[story3_emergency_procurement\|Story 3]]) | CFO / designated authority | Slack + Email (with 60-min timer) |

> [!tech-stack] Conversational Interface Option
> Users can submit procurement requests as Slack/Teams messages. The [[nl_intent_parser]] processes them identically to dashboard submissions. Responses are threaded in the same conversation. No separate app needed.
> Example ([[story1_routine_office_supply|Story 1]]): Priya submits via Slack → gets order confirmation in the same thread in **45 seconds**.

## Approval via Slack/Teams Workflow

1. Agent routes order above threshold via [[approval_workflow]].
2. Approver receives message with: full comparison, agent reasoning, order value.
3. **One-click approve / reject** button in the message.
4. Agent acts on response immediately, no dashboard visit required.

Example ([[story2_high_value_it_equipment|Story 2]]): CFO approves ₹1.52 crore laptop order in **10 minutes** via a single Slack message.

> [!milestone] Delivery
> Notification webhooks are available from [[phase2_core_intelligence_transaction_flow|Phase 2]] onwards. The full conversational interface (request submission via Slack/Teams) is a Phase 2–3 feature requiring [[nl_intent_parser]] integration with the messaging platform API.

> [!insight] Adoption Impact
> Embedding the procurement interface in Slack/Teams — where enterprise users spend the majority of their working day — dramatically lowers the activation barrier for adoption. Users don't need to change their workflow; the agent meets them where they already are. This is a key lever for reaching the [[user_adoption_metrics|500+ active users at 12 months]] target.
