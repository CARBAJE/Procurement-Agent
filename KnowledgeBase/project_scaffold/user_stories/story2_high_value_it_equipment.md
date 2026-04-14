---
tags: [user-story, high-value, approval-workflow, it-equipment, human-in-the-loop, iso27001, tco]
cssclasses: [procurement-doc, story-doc]
status: "#processed"
related: ["[[nl_intent_parser]]", "[[beckn_bap_client]]", "[[comparison_scoring_engine]]", "[[approval_workflow]]", "[[real_time_tracking]]", "[[audit_trail_system]]", "[[communication_slack_teams]]", "[[erp_integration]]"]
---

# User Story 2: High-Value IT Equipment with Approval Workflow

## Persona
**Rajesh Menon** — IT Director, financial services firm.
Procuring 200 enterprise laptops for a new office.

## Current State (As-Is)

- Team creates RFQ → sends to 5 pre-approved vendors → waits 7–10 days for responses.
- Builds comparison spreadsheet manually (often incomplete).
- Presents to CFO for approval → negotiates over 3–4 calls → places order.
- End-to-end: **3–4 weeks**. Reasoning behind selection not fully documented.

## Step-by-Step Agent Journey

**Input:** "200 business laptops, 16GB RAM, 512GB SSD, i7 or equivalent, Windows 11 Pro, 3-year warranty, deliver to Mumbai HQ within 15 business days, budget ₹1.6 crore."

1. [[nl_intent_parser]] parses request with detailed technical specifications.
2. [[beckn_bap_client]] sends `discover` queries to multiple Discovery Services across ONDC and Beckn-compatible networks → 8 sellers with matching inventory returned.
3. [[comparison_scoring_engine]] scores: price, warranty terms, delivery timeline, seller rating, **ISO 27001 certification** (required for IT equipment per enterprise policy).
4. Agent presents top 3 options to Rajesh with detailed comparison and reasoning.
   > *"Seller C recommended despite 4% higher unit price — superior warranty (5-year vs. 3-year) and bulk discount at 200+ units produce 8% lower TCO."*
5. Rajesh reviews and selects Seller C via the [[frontend_react_nextjs|comparison UI]].
6. Total (₹1.52 crore) > Rajesh's approval authority → [[approval_workflow]] routes to CFO.
7. CFO receives [[communication_slack_teams|Slack notification]]: full comparison, agent reasoning, one-click approve/reject.
8. CFO approves in **10 minutes**.
9. Agent executes `/init` → `/confirm`. [[erp_integration|ERP sync]] creates PO in SAP. Full [[audit_trail_system|audit trail]] captured.
10. [[real_time_tracking|Real-time delivery tracking]] via `/status` on dashboard.

> [!architecture] Technical Workflow
> `NL Parser` → `Multi-network discover (sync queries to multiple Discovery Services)` → `Catalog Normalizer` → `[[comparison_scoring_engine|Comparison Engine]]` (ISO 27001 compliance check + TCO scoring) → `Human-in-the-Loop` (Rajesh selects) → `[[approval_workflow|Approval Routing]]` (CFO notification) → `/init` → `/confirm` → `[[event_streaming_kafka|Kafka]]` (audit + [[erp_integration|ERP sync]]) → `[[real_time_tracking|/status polling]]` (real-time tracking).

> [!insight] Human-in-the-Loop Value
> This story demonstrates that the agent's value in human-in-the-loop mode is **not just speed** (3–4 weeks → 2 days) but **comparison quality**. The agent evaluated 8 sellers more rigorously than a manual process evaluating 5. The ISO 27001 compliance check — which Rajesh's team might have missed under time pressure — was automatic. The audit trail eliminates 2 weeks of documentation work.

## Expected Outcomes

| Metric | Before | After |
|---|---|---|
| Procurement cycle time | 3–4 weeks | 2 days |
| Sellers evaluated | 5 (manual) | 8+ (rigorous automated) |
| Audit trail preparation | 2 weeks | Automated, zero effort |
