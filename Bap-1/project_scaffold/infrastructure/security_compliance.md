---
tags: [infrastructure, security, compliance, sox, gdpr, owasp, pii, tls, aes256, kms, rbac]
cssclasses: [procurement-doc, infra-doc]
status: "#processed"
related: ["[[security_encryption]]", "[[identity_access_keycloak]]", "[[audit_trail_system]]", "[[cloud_providers]]", "[[databases_postgresql_redis]]", "[[vector_db_qdrant_pinecone]]", "[[phase4_hardening_testing_production]]"]
---

# Infrastructure: Security & Compliance

> [!architecture] Defense-in-Depth Security Model
> Security is implemented as five independent, layered controls. A breach of any single layer does not compromise data confidentiality or integrity — the next layer provides independent protection. This model satisfies [[security_encryption|SOX, GDPR, and IT Act 2000]] simultaneously and is validated in [[phase4_hardening_testing_production|Phase 4]] via penetration testing.

## Network Security

- TLS 1.3 for all API calls ([[beckn_bap_client|Beckn network]], [[erp_sap_oracle|ERP]], [[llm_providers|LLM providers]], internal services).
- [[api_gateway|Kong API Gateway]] enforces authentication, rate limiting, and TLS termination at the edge.
- No service-to-service call bypasses the gateway in production.

## Data Encryption

| Layer | Protocol | Details |
|---|---|---|
| In transit | TLS 1.3 | All API calls |
| At rest | AES-256 | [[databases_postgresql_redis\|PostgreSQL]] and [[vector_db_qdrant_pinecone\|Qdrant]] |
| Key management | KMS | AWS KMS / Azure Key Vault — keys rotated per enterprise policy |

## Identity & Access Control

- RBAC: roles `Requester`, `Approver`, `Admin` — enforced at [[api_gateway|API Gateway]] and agent level.
- IdP: [[identity_access_keycloak|Keycloak]], Okta, Azure AD.
- Least-privilege: API-level authorization; audit logging of all access events → [[audit_trail_system|Kafka → Splunk]].

## PII Protection

- PII scrubbing pipeline before all [[llm_providers|LLM calls]].
- Procurement data is entity-level (company, not individual) by default.
- No personal data in LLM prompts unless strictly necessary and policy-approved.

## Compliance Frameworks

| Framework | Scope | Compliance Mechanism |
|---|---|---|
| SOX Section 404 | Financial controls | [[audit_trail_system\|Automated audit trail]] with real-time reasoning capture |
| GDPR | EU-supplier interactions | DPAs with LLM providers; configurable data retention |
| IT Act 2000 | India operations | Data stays in [[cloud_providers\|India-region clouds]] |
| OWASP Top 10 | Application security | Pen test in [[phase4_hardening_testing_production\|Phase 4]]; all findings remediated before go-live |

> [!milestone] Phase 4 Security Hardening Deliverables
> - Penetration test completed, all critical/high findings remediated.
> - OWASP Top 10 fully addressed.
> - Encryption verified at rest and in transit.
> - Access control audit trail confirmed end-to-end.
> **Hard gate:** No production deployment without signed-off pen test report.

> [!guardrail] Non-Negotiable Security Controls
> The following controls are **hard requirements** — they cannot be disabled or bypassed for any reason:
> 1. TLS 1.3 on all API endpoints — no HTTP in production.
> 2. AES-256 at rest for all datastores containing procurement data.
> 3. RBAC enforced at [[api_gateway|API Gateway]] — no direct backend access.
> 4. All secrets via KMS — no plaintext secrets in code, environment variables, or config files.
> 5. PII scrubbing before LLM calls.
> Violations are flagged immediately in the [[audit_trail_system]] and escalated to the security team.
