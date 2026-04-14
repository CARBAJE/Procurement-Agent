---
tags: [user-story, routine-procurement, automation, full-autonomous, office-supply, ondc, 45-seconds]
cssclasses: [procurement-doc, story-doc]
status: "#processed"
related: ["[[nl_intent_parser]]", "[[beckn_bap_client]]", "[[comparison_scoring_engine]]", "[[negotiation_engine]]", "[[approval_workflow]]", "[[audit_trail_system]]", "[[communication_slack_teams]]", "[[business_impact_metrics]]"]
---

# User Story 1: Routine Office Supply Procurement

## Persona
**Priya Sharma** — Procurement Coordinator, 10,000-employee IT services company, Bangalore.
Handles 200+ routine purchase requests monthly.

## Current State (As-Is)

- Receives email request for 500 reams of A4 paper.
- Logs into SAP Ariba, manually searches catalog, compares 3–4 suppliers.
- Creates purchase requisition → routes for approval (2–3 day wait).
- Converts to PO. Total cycle: **5–7 days**.
- Repeats 15–20 times daily. Estimates 70% of work is repetitive data entry.

> [!insight] The Automation Opportunity
> Priya's workflow is 70% repetitive — the exact target for autonomous agent operation. This story demonstrates the **fully autonomous mode**: the order total (₹90,000) is below her auto-approval threshold (₹1,00,000), so the agent completes the entire procurement cycle without human intervention. The comparison between 5–7 days and 45 seconds is the headline value proposition of the entire system.

## Step-by-Step Agent Journey

**Input:** "500 reams A4 paper, 80gsm, white, delivered to Building C, Whitefield campus, within 3 business days."

1. Priya submits request via [[frontend_react_nextjs|dashboard]] or [[communication_slack_teams|Slack]].
2. [[nl_intent_parser]] parses: `item=A4 paper 80gsm`, `qty=500 reams`, `location=12.9716°N 77.5946°E`, `delivery=3 days`.
3. [[beckn_bap_client|Agent]] sends `discover` query to the ONDC Discovery Service → Discovery Service returns matching offerings from 50+ stationery sellers registered in Bangalore.
4. Discovery Service returns catalog from 12 matching sellers in < 1 second. BAP client normalizes the discover response.
5. [[comparison_scoring_engine]] scores: Seller A (₹195/ream, ⭐4.8, 2-day), Seller B (₹189/ream, ⭐4.5, 3-day), etc.
6. [[negotiation_engine]] auto-negotiates with top 3 via `/select` — 5% discount counter-offer. Seller B accepts ₹180/ream.
7. Total (₹90,000) < auto-approval threshold (₹1,00,000) → [[approval_workflow|no approval required]]; agent proceeds to `/init` → `/confirm`.
8. Order placed. Priya receives [[communication_slack_teams|Slack]] notification with comparison, reasoning, confirmation.

**Total time: 45 seconds.**

> [!architecture] Technical Workflow
> `NL Parser` → `discover (sync query to Discovery Service)` → `Catalog Normalizer` → `[[comparison_scoring_engine|Comparison Engine]]` (scoring + explainability) → `[[negotiation_engine|Negotiation Engine]]` (`ONIX: POST /bap/caller/select` with modified terms) → `[[approval_workflow|Policy Check]]` (threshold validation) → `ONIX: POST /bap/caller/init` → `POST /bap/caller/confirm` → `[[event_streaming_kafka|Kafka event]]` (audit + [[erp_integration|ERP sync]]) → [[communication_slack_teams|Notification dispatch]].

## Expected Outcomes

| Metric | Before | After |
|---|---|---|
| Procurement cycle time | 5–7 days | < 1 minute |
| Team throughput | Baseline | 3× volume, same headcount |
| Platform licensing fees | ₹10–25M/year (enterprise) | 80–90% reduction |
| Item cost savings | Baseline | 8–12% via automated negotiation |

See [[business_impact_metrics]] for full quantification.
