---
tags: [technology, security, encryption, tls, aes256, kms, rbac, compliance, sox, gdpr]
cssclasses: [procurement-doc, tech-doc]
status: "#processed"
related: ["[[security_compliance]]", "[[identity_access_keycloak]]", "[[databases_postgresql_redis]]", "[[vector_db_qdrant_pinecone]]", "[[cloud_providers]]", "[[phase4_hardening_testing_production]]"]
---

# Security & Encryption

> [!architecture] Defense-in-Depth Model
> Security is implemented across **five dimensions** in a defense-in-depth model: data residency, PII protection, encryption (at rest and in transit), access control, and compliance framework coverage. No single control is relied upon exclusively — multiple independent layers protect procurement data. This model satisfies [[security_compliance|SOX, GDPR, and IT Act 2000]] requirements simultaneously.

---

### 1. Data Residency

- Procurement data must stay within the enterprise's jurisdiction.
- **Implementation:** Self-hosted [[vector_db_qdrant_pinecone|Qdrant vector DB]]; [[databases_postgresql_redis|PostgreSQL]] on enterprise [[cloud_providers|cloud (AWS Mumbai / Azure India)]]; LLM calls via enterprise API agreements with data processing addendums.

---

### 2. PII Protection

- No personal data in [[llm_providers|LLM prompts]] unless strictly necessary.
- **Implementation:** PII scrubbing pipeline runs before all LLM calls; procurement data is entity-level (company, not individual) by default.

---

### 3. Encryption

| Layer | Protocol | Details |
|---|---|---|
| In transit | TLS 1.3 | All API calls (Beckn network, ERP, LLM providers, internal services) |
| At rest | AES-256 | [[databases_postgresql_redis\|PostgreSQL]] and [[vector_db_qdrant_pinecone\|Qdrant]] |
| Key management | KMS | AWS KMS / Azure Key Vault — keys rotated per enterprise policy |

---

### 4. Access Control

- Role-based, least-privilege principle.
- **Implementation:** RBAC via [[identity_access_keycloak|Okta / Azure AD]] integration; API-level authorization via [[api_gateway|Kong Gateway]]; audit logging of all access events to [[audit_trail_system|Kafka → Splunk]].

---

### 5. Compliance Frameworks

| Framework | Scope | Implementation |
|---|---|---|
| SOX Section 404 | Financial controls | Automated [[audit_trail_system\|audit trail]] satisfies documentation requirements |
| GDPR | EU-supplier interactions | DPAs with [[llm_providers\|LLM providers]]; configurable data retention |
| IT Act 2000 | India operations | Data stays in [[cloud_providers\|India-region clouds]] |
| OWASP Top 10 | Application security | Pen test in [[phase4_hardening_testing_production\|Phase 4]]; all findings remediated |

> [!milestone] Phase 4 Security Hardening (Weeks 13–16)
> From [[phase4_hardening_testing_production|Phase 4 Security Hardening milestone]]:
> - Penetration test completed and all findings remediated.
> - OWASP Top 10 **fully addressed**.
> - Encryption verified at rest and in transit (confirmed by security audit).
> - Access control audit trail confirmed end-to-end.
> **Acceptance criterion:** Pen test report signed off; data encrypted at rest and in transit confirmed.

> [!guardrail] Hard Security Constraints
> - Maximum discount negotiation capped at **20%** in [[negotiation_engine|Negotiation Engine]] — agent cannot agree to terms outside policy boundaries.
> - A `requester` role **cannot** bypass [[approval_workflow|approval thresholds]] via direct API calls — [[api_gateway|Kong Gateway]] enforces RBAC at the edge.
> - No PII in LLM prompts without explicit policy exception logged in [[audit_trail_system]].
> - All secrets managed via KMS — **never** stored in environment variables or application code.
