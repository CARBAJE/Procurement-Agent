---
tags: [component, workflow, rbac, compliance, approval, threshold, escalation, human-in-the-loop]
cssclasses: [procurement-doc, component-doc]
status: "#processed"
related: ["[[identity_access_keycloak]]", "[[audit_trail_system]]", "[[communication_slack_teams]]", "[[agent_framework_langchain_langgraph]]", "[[phase2_core_intelligence_transaction_flow]]", "[[story2_high_value_it_equipment]]", "[[story3_emergency_procurement]]", "[[story5_government_emarketplace]]"]
---

# Component: Approval Workflow

> [!architecture] Role in the System
> The Approval Workflow enforces **enterprise spending authority rules** before the [[agent_framework_langchain_langgraph|agent]] executes `/confirm`. It is the primary human-in-the-loop control mechanism — ensuring that purchases above configured thresholds require human authorization before funds are committed. The workflow is driven by [[identity_access_keycloak|Keycloak RBAC]] role mappings and threshold configurations set by the enterprise admin.

## Routing Logic

| Condition | Action |
|---|---|
| Order total ≤ requester's auto-approval threshold | Agent proceeds directly to `/init` → `/confirm` |
| Total > requester's threshold, ≤ manager authority | Route to manager for approval |
| Total > manager's authority | Route to CFO / C-level |
| Emergency procurement detected | Flag appropriate authority + 60-minute auto-approve countdown |
| Government L1 mode ([[story5_government_emarketplace\|Story 5]]) | Auto-select L1 among qualified sellers; no override without documented exception |

## RBAC Integration

| Role | Permissions |
|---|---|
| Requester | Submit requests; cannot exceed auto-approval threshold |
| Approver | Review and approve/reject orders above requester threshold |
| Admin | Configure thresholds, strategies, category policies; manage users |

Roles are mapped via [[identity_access_keycloak|Keycloak]] (SAML 2.0 / OIDC) and enforced at the [[api_gateway|API Gateway]] boundary.

## Approval Interface

Approvers receive a [[communication_slack_teams|Slack / Teams / Email]] notification with:
- Full seller comparison (from [[comparison_scoring_engine]]).
- Agent reasoning for the recommendation.
- One-click **approve / reject** action.

Example from [[story2_high_value_it_equipment|Story 2]]: CFO receives laptop order notification (₹1.52 crore) → approves in 10 minutes.

## Emergency Mode ([[story3_emergency_procurement|Story 3]])

- Urgency detected by [[nl_intent_parser]] (`"URGENT:"` prefix).
- CFO flagged with 60-minute auto-approve countdown.
- Full [[audit_trail_system|audit trail]] captured automatically even under emergency conditions — no compliance gap.

> [!milestone] Phase 2 Acceptance (Weeks 5–8)
> From [[phase2_core_intelligence_transaction_flow|Phase 2 Approval Workflow milestone]]:
> - Orders above threshold require and receive approval **before** `/confirm` is executed.
> - Approval routing tested for all role combinations (requester → manager, manager → CFO).
> - Emergency countdown timer functional.

> [!guardrail] Non-Bypassable Control
> The [[api_gateway|API Gateway]] enforces RBAC at the network boundary. A `requester` role **cannot** call `/confirm` directly — the route is blocked unless an approval event with the correct authority level has been recorded in the [[audit_trail_system]]. This control is tested in the [[phase4_hardening_testing_production|Phase 4 integration test suite]].
