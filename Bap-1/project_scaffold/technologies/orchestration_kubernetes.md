---
tags: [technology, infrastructure, kubernetes, helm, argocd, gitops, devops, eks, aks, gke]
cssclasses: [procurement-doc, tech-doc]
status: "#processed"
related: ["[[cicd_pipeline]]", "[[cloud_providers]]", "[[phase4_hardening_testing_production]]", "[[observability_stack]]", "[[security_compliance]]"]
---

# Container Orchestration — Kubernetes

> [!architecture] Deployment Architecture
> All system components are containerized and orchestrated via Kubernetes. **Helm** provides templated, environment-aware deployments. **ArgoCD** implements GitOps — the cluster state is always reconciled with the Git repository, making deployments reproducible and auditable. The stack is cloud-agnostic: the same Helm chart deploys to [[cloud_providers|EKS, AKS, or GKE]] by swapping values files.

## Tools

| Technology | Role |
|---|---|
| Kubernetes | Container orchestration platform |
| Helm | Kubernetes package manager; parameterized chart for all environments |
| ArgoCD | GitOps continuous deployment; reconciles cluster state with Git |
| EKS (AWS) | Managed Kubernetes on Amazon Web Services |
| AKS (Azure) | Managed Kubernetes on Microsoft Azure |
| GKE (Google) | Managed Kubernetes on Google Cloud Platform |

> [!tech-stack] Why Kubernetes + ArgoCD
> Kubernetes provides the horizontal scaling, health checks, and self-healing that enterprise SLAs (≥ 99.9% uptime, per [[technical_performance_metrics]]) require. ArgoCD's GitOps model makes every deployment change a Git commit — reviewable, auditable, and reversible. This aligns with [[security_compliance|SOX Section 404]] requirements for traceable change management in financial systems.

## Service Topology

| Service | Workload Type | Notes |
|---|---|---|
| Agent service ([[agent_framework_langchain_langgraph\|LangChain/LangGraph]]) | Deployment | Horizontal pod autoscaler on request queue depth |
| [[beckn_bap_client\|BAP Client]] (Python aiohttp) | Deployment | Scales based on Beckn request volume |
| [[frontend_react_nextjs\|Frontend]] (Next.js) | Deployment | SSR; CDN in front |
| [[api_gateway\|API Gateway]] (Kong) | Deployment | Ingress controller |
| [[databases_postgresql_redis\|PostgreSQL]] | StatefulSet | Persistent volume; enterprise cloud managed preferred |
| [[databases_postgresql_redis\|Redis]] | StatefulSet | In-memory; persistent volume optional |
| [[vector_db_qdrant_pinecone\|Qdrant]] | StatefulSet | Self-hosted; persistent volume required for data sovereignty |
| [[event_streaming_kafka\|Kafka]] | StatefulSet | KRaft mode (no Zookeeper dependency) |
| [[observability_stack\|Prometheus + Grafana]] | Deployment | Monitoring namespace |

## Local Development

- **`docker-compose`** — full stack runs locally for development, mirroring Kubernetes topology.
- Developers do not need a Kubernetes cluster to iterate; `docker-compose up` brings everything online.

> [!milestone] Phase 4 Acceptance Criteria (Weeks 13–16)
> Delivered as part of [[phase4_hardening_testing_production|Phase 4 Containerization milestone]]:
> - Full stack runs via `docker-compose up` locally (all services healthy).
> - Helm chart deploys cleanly to target Kubernetes cluster (EKS or AKS).
> - [[cicd_pipeline|GitHub Actions]] CI pipeline runs lint → test → build → Helm deploy automatically on merge.

> [!guardrail] Production Hardening
> All container images must be built from distroless or minimal base images. Image vulnerability scanning runs in the [[cicd_pipeline|CI/CD pipeline]] via Trivy. No `latest` tags in production — all images pinned to digest hashes. RBAC for Kubernetes service accounts follows least-privilege (see [[security_compliance]]).
