---
tags: [integration, identity, keycloak, saml, oidc, rbac, sso, okta, azure-ad, access-control]
cssclasses: [procurement-doc, integration-doc]
status: "#processed"
related: ["[[api_gateway]]", "[[approval_workflow]]", "[[frontend_react_nextjs]]", "[[security_compliance]]", "[[phase1_foundation_protocol_integration]]", "[[security_encryption]]"]
---

# Integration: Identity & Access Management

> [!architecture] Role in the System
> Identity & Access Management (IAM) is the **trust foundation** of the entire procurement system. Every request to the backend carries an identity claim — issued by the IdP (Keycloak, Okta, or Azure AD) and validated by the [[api_gateway|API Gateway]]. The RBAC roles carried in the JWT/SAML assertion determine what the [[agent_framework_langchain_langgraph|agent]] is allowed to do on behalf of the user — specifically, whether the agent can auto-confirm or must route to [[approval_workflow|approval]].

## Primary IdP: Keycloak

| Attribute | Detail |
|---|---|
| Protocol | SAML 2.0 or OIDC |
| Role | SSO broker for enterprise identity |
| RBAC | Procurement roles mapped to system permissions |

## Additional IdP Options

| Provider | Protocol | Use Case |
|---|---|---|
| Okta | OIDC | Enterprise SaaS-first IdP |
| Azure AD | OIDC / SAML | Microsoft-stack enterprises |

## Procurement Roles

| Role | Permissions |
|---|---|
| Requester | Submit requests; cannot exceed auto-approval threshold; cannot call `/confirm` directly |
| Approver | Review and approve/reject orders above requester threshold via [[communication_slack_teams\|one-click interface]] |
| Admin | Configure thresholds, strategies, category policies; manage users and role mappings |

> [!tech-stack] SAML vs. OIDC Selection
> **SAML 2.0** is used for enterprises with existing SAML-based corporate SSO (common in SAP/Oracle environments). **OIDC** is preferred for cloud-native or API-first enterprises (Okta, Azure AD). Both protocols are supported simultaneously — the [[api_gateway|Kong Gateway]] handles token validation regardless of which protocol issued the token.

## Enforcement Points

1. **[[api_gateway|API Gateway (Kong)]]** — validates JWT/SAML token on every inbound request; rejects unauthenticated calls.
2. **[[agent_framework_langchain_langgraph|Agent Framework]]** — checks role claim before executing approval-required actions.
3. **[[approval_workflow]]** — routes to the correct approver tier based on role hierarchy and spend threshold.

> [!milestone] Phase 1 Delivery (Weeks 1–4)
> From [[phase1_foundation_protocol_integration|Phase 1 Frontend Scaffold milestone]]:
> - [[frontend_react_nextjs|Frontend]] runs locally with **Keycloak SSO stub** (mocked for dev).
> - Full Keycloak integration wired before [[phase2_core_intelligence_transaction_flow|Phase 2]] [[approval_workflow|approval workflow]] goes live.

> [!guardrail] RBAC is Non-Bypassable
> A `Requester` role **cannot** call `/confirm` directly — this route is blocked at the [[api_gateway|API Gateway]] level regardless of how the request is constructed. No application-layer workaround exists. This is validated in the [[phase4_hardening_testing_production|Phase 4 integration test suite]] and confirmed in the penetration test.
