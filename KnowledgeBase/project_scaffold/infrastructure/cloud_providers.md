---
tags: [infrastructure, cloud, aws, azure, gcp, eks, aks, gke, data-residency, india, multi-cloud]
cssclasses: [procurement-doc, infra-doc]
status: "#processed"
related: ["[[kubernetes_deployment]]", "[[databases_postgresql_redis]]", "[[vector_db_qdrant_pinecone]]", "[[security_compliance]]", "[[security_encryption]]", "[[cicd_pipeline]]"]
---

# Infrastructure: Cloud Providers & Data Residency

> [!architecture] Multi-Cloud Strategy
> The system is cloud-agnostic by design — the same [[orchestration_kubernetes|Helm chart]] deploys to AWS EKS, Azure AKS, or GCP GKE. Cloud provider selection is driven by the enterprise client's existing cloud contracts and **data residency requirements**: procurement data must reside within the enterprise's jurisdiction (India, EU, etc.). The India deployment target (AWS Mumbai / Azure India Central) satisfies [[security_compliance|IT Act 2000]] requirements.

## Supported Cloud Targets

| Provider | Kubernetes Service | Region (India) | Notes |
|---|---|---|---|
| AWS | EKS | Mumbai (ap-south-1) | PostgreSQL on RDS; AWS KMS for key management |
| Azure | AKS | India Central / South India | Azure AD integration for RBAC; Azure Key Vault |
| GCP | GKE | Mumbai (asia-south1) | GKE Autopilot option for reduced ops overhead |

## Data Residency Requirements

> [!guardrail] Data Must Stay In-Jurisdiction
> - **[[databases_postgresql_redis|PostgreSQL]]:** Deployed on enterprise cloud (AWS Mumbai / Azure India).
> - **[[vector_db_qdrant_pinecone|Qdrant (Vector DB)]]:** Self-hosted within enterprise cloud boundary — no third-party SaaS.
> - **LLM calls ([[llm_providers]]):** Enterprise API agreements with data processing addendums. For zero-external-call deployments, [[embedding_models|e5-large-v2]] self-hosted fallback used.
> Violating data residency requirements exposes the enterprise to regulatory penalties under [[security_compliance|IT Act 2000 (India) and GDPR (EU)]].

## Multi-Cloud Flexibility

- [[orchestration_kubernetes|Helm chart]] parameterized for all three cloud targets via values overrides.
- [[cicd_pipeline|ArgoCD]] manages environment-specific configuration.
- On-premises deployment supported via [[api_gateway|Kong Gateway]] + bare-metal Kubernetes.

## Key Management

| Cloud | KMS Service |
|---|---|
| AWS | AWS KMS |
| Azure | Azure Key Vault |
| GCP | Cloud KMS |

AES-256 encryption for all data at rest; KMS-managed keys rotated per enterprise policy. Full encryption spec: [[security_encryption]].

> [!insight] On-Premises Option
> For enterprises with strict air-gap requirements (e.g., defence sector, regulated banking), the full stack can be deployed on-premises via [[orchestration_kubernetes|bare-metal Kubernetes]] + [[api_gateway|Kong Gateway]] + self-hosted [[llm_providers|LLM]] (open-source model). This is a premium configuration that extends the addressable market beyond cloud-native enterprises.
