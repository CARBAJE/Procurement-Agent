---
tags: [infrastructure, kubernetes, helm, argocd, gitops, devops, deployment, eks, aks, gke]
cssclasses: [procurement-doc, infra-doc]
status: "#processed"
related: ["[[orchestration_kubernetes]]", "[[cicd_pipeline]]", "[[cloud_providers]]", "[[phase4_hardening_testing_production]]", "[[observability_stack]]", "[[security_compliance]]"]
---

# Infrastructure: Kubernetes Deployment

> [!architecture] Deployment Model
> All system components run as containerized workloads in **Kubernetes**. Deployments are managed by **Helm** (parametric chart for dev/staging/prod environments) and continuously reconciled by **ArgoCD** (GitOps — cluster state always matches the Git repository). The cloud target is configurable: the same Helm chart deploys to [[cloud_providers|EKS (AWS), AKS (Azure), or GKE (Google)]] by swapping a values file.

## Deployment Targets

| Platform | Cloud Provider |
|---|---|
| EKS | Amazon Web Services |
| AKS | Microsoft Azure |
| GKE | Google Cloud Platform |

Full cloud details: [[cloud_providers]].

## Tools

| Tool | Role |
|---|---|
| Helm | Kubernetes package manager; parameterized chart for all environments |
| ArgoCD | GitOps continuous deployment; reconciles cluster state with Git |

## Service Topology

| Service | Workload Type | Notes |
|---|---|---|
| [[agent_framework_langchain_langgraph\|Agent service]] | Deployment | Horizontal pod autoscaler on request queue depth |
| [[beckn_bap_client\|BAP Client]] | Deployment | Scales on Beckn request volume |
| [[frontend_react_nextjs\|Frontend (Next.js)]] | Deployment | SSR; CDN in front |
| [[api_gateway\|API Gateway (Kong)]] | Deployment | Ingress controller |
| [[databases_postgresql_redis\|PostgreSQL]] | StatefulSet | Persistent volume; enterprise cloud managed |
| [[databases_postgresql_redis\|Redis]] | StatefulSet | In-memory; persistent volume optional |
| [[vector_db_qdrant_pinecone\|Qdrant]] | StatefulSet | Persistent volume required (data sovereignty) |
| [[event_streaming_kafka\|Kafka]] | StatefulSet | KRaft mode |
| [[observability_stack\|Prometheus + Grafana]] | Deployment | Monitoring namespace |

## Local Development

- `docker-compose` — full stack runs locally, mirroring the Kubernetes topology.
- No Kubernetes cluster required for developer iteration.

> [!milestone] Phase 4 Acceptance (Weeks 13–16)
> From [[phase4_hardening_testing_production|Phase 4 Containerization milestone]]:
> - Full stack runs via `docker-compose up` (all services healthy).
> - Helm chart deploys cleanly to target Kubernetes cluster.
> - [[cicd_pipeline|GitHub Actions]] pipeline: lint → test → build → Helm deploy runs automatically on merge.

> [!guardrail] Production Hardening Rules
> - All container images built from distroless/minimal base images.
> - Image vulnerability scanning (Trivy) runs in [[cicd_pipeline|CI pipeline]] — critical CVEs block deployment.
> - No `latest` tags in production — all images pinned to digest hashes.
> - Kubernetes service account RBAC follows least-privilege ([[security_compliance]]).
> - All secrets injected via Kubernetes Secrets (sourced from KMS) — never in `docker-compose.yml` or Helm values files in plaintext.
