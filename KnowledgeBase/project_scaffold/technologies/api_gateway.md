---
tags: [technology, infrastructure, api-gateway, kong, authentication, routing]
cssclasses: [procurement-doc, tech-doc]
status: "#processed"
related: ["[[identity_access_keycloak]]", "[[beckn_bap_client]]", "[[erp_integration]]", "[[orchestration_kubernetes]]", "[[security_compliance]]"]
---

# API Gateway

> [!architecture] Role in the System
> The API Gateway is the **single entry point** for all external traffic into the procurement agent backend. It sits between the [[frontend_react_nextjs|React/Next.js frontend]] (and [[communication_slack_teams|Slack/Teams interface]]) and the downstream services: the [[agent_framework_langchain_langgraph|LangChain agent]], the [[beckn_bap_client|BAP client]], and the [[erp_integration|ERP middleware]]. No request reaches a backend service without passing through this layer.

## Options

| Option | Preference | Notes |
|---|---|---|
| Kong Gateway | **Preferred** | On-premises flexibility; open-source; rich plugin ecosystem |
| AWS API Gateway | Alternative | Managed; suitable for fully AWS-hosted deployments |

> [!tech-stack] Why Kong is Preferred
> Kong is preferred for enterprise deployments because it supports **on-premises and hybrid** installation — critical for clients who cannot route all traffic through a cloud provider's managed gateway. Kong's plugin architecture supports custom Beckn-specific rate-limiting policies and integrates natively with [[identity_access_keycloak|Keycloak]] for JWT validation.
> AWS API Gateway is a viable fallback for fully cloud-native (EKS) deployments on [[cloud_providers|AWS Mumbai]].

## Responsibilities

- **Authentication enforcement** — validates JWT tokens issued by [[identity_access_keycloak|Keycloak]] (SAML 2.0 / OIDC) on every inbound request.
- **RBAC at the API boundary** — roles (`requester`, `approver`, `admin`) are extracted from the JWT claim and forwarded to downstream services.
- **Rate limiting** — throttles outbound Beckn `/search` calls to prevent network abuse.
- **Request routing** — directs requests to the correct microservice (agent, BAP client, ERP middleware, notification service).
- **TLS termination** — terminates TLS 1.3; enforced as part of [[security_compliance|defense-in-depth]].

## Integration Points

- **[[identity_access_keycloak]]** — receives and validates JWT/SAML assertions from Keycloak.
- **[[agent_framework_langchain_langgraph|Agent backend]]** — forwards authenticated procurement requests.
- **[[beckn_bap_client|BAP client service]]** — proxies Beckn protocol calls.
- **[[erp_integration|ERP middleware]]** — routes budget-check and PO-sync calls.

> [!guardrail] Security Constraint
> A `requester` role **cannot** call the `/confirm` endpoint directly — the [[approval_workflow|approval workflow]] must complete first. The gateway enforces this via route-level RBAC policies. Attempts to bypass approval by calling backend services directly are blocked at this layer.
> All rate-limiting counters are stored in [[databases_postgresql_redis|Redis 7]] for shared state across horizontally-scaled gateway pods.

> [!milestone] Deployment Target
> Deployed as a Kubernetes `Deployment` with an `Ingress` controller on [[orchestration_kubernetes|EKS/AKS/GKE]]. [[cicd_pipeline|Helm chart]] parameterizes Kong configuration per environment (dev, staging, prod).
