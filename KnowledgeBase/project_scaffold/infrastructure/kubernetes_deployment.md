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

## Current Deployment: Docker Compose (Phases 1–3)

> [!implementation] Kubernetes is the Phase 4 target. Phases 1–3 run entirely on Docker Compose.

The full stack (16+ containers) is orchestrated via `docker-compose.yml` at the repo root. No Kubernetes cluster is required until Phase 4.

| Container | Port | Notes |
|---|---|---|
| `beckn-bap-client` | 8002 | Beckn protocol client |
| `orchestrator` | 8004 | Pipeline state machine |
| `catalog-normalizer` | 8005 | on_discover normalizer |
| `data-normalizer` | 8006 | Central persistence layer |
| `erp-adapter` | 8007 | SAP/Oracle ERP integration |
| `erp-mock` | 8008 | Local ERP stub |
| `analytics` | 8009 | Dashboard reporting |
| `notification-dispatcher` | 8010 | Kafka → Slack/Teams/Email |
| `comparative-scoring` | 8003 | ML scoring adapter |
| `discovery_engine` | 8006 | Multi-network Beckn fan-out |
| `frontend_demo_gateway` | 8005 | Demo BFF |
| `sim-bpp` | 3002 | Local BPP simulator |
| `onix-bap` | 8081 | ONIX BAP adapter (Go) |
| `onix-bpp` | 8082 | ONIX BPP adapter (Go) |
| `redis` | 6379 | Pub/Sub broker + ONIX cache |
| `procurement-postgres` | 5432 | PostgreSQL 16 + pgvector |

```bash
# Start the full stack
docker compose up -d

# Start only the Beckn core (discovery infra)
docker compose up -d redis onix-bap onix-bpp sim-bpp

# Tail a single service
docker compose logs -f orchestrator
```

All containers share the `beckn_network` bridge. Service discovery uses Docker DNS (`http://orchestrator:8004`, `http://data-normalizer:8006`, etc.).

The MLOps stack (prediction-api, MLflow, training-pipeline, validation-service) is a separate `docker-compose.mlops.yaml` in `services/ComparativeAndScoreing/`.

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
