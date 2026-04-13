---
tags: [technology, infrastructure, cicd, github-actions, docker, terraform, iac, devops]
cssclasses: [procurement-doc, tech-doc]
status: "#processed"
related: ["[[orchestration_kubernetes]]", "[[phase4_hardening_testing_production]]", "[[observability_stack]]", "[[security_compliance]]", "[[cloud_providers]]"]
---

# CI/CD Pipeline

> [!architecture] Pipeline Overview
> The CI/CD pipeline automates the full path from code commit to production deployment. **GitHub Actions** orchestrates the pipeline stages. **Docker** builds and tags container images. **Terraform** provisions cloud infrastructure declaratively. **ArgoCD** (in [[orchestration_kubernetes]]) handles GitOps-based cluster reconciliation after image push. Together, these ensure every deployment is repeatable, auditable, and aligned with [[security_compliance|SOX change management requirements]].

## Tools

| Tool | Role |
|---|---|
| GitHub Actions | Automated CI/CD pipeline runner |
| Docker | Container image build and registry |
| Terraform | Infrastructure as Code (IaC) for [[cloud_providers|cloud resource provisioning]] |

> [!tech-stack] Why Terraform for IaC
> All cloud resources (EKS clusters, RDS instances, VPCs, KMS keys) are defined as Terraform code — versioned in Git, reviewed via pull request, and applied idempotently. This satisfies [[security_compliance|SOX audit requirements]] for infrastructure change traceability, and enables instant environment recreation (critical for disaster recovery).

## Pipeline Stages

1. **Lint & Type Check** — ESLint/TypeScript ([[frontend_react_nextjs|frontend]]), Ruff/mypy (Python agent/BAP backend).
2. **Unit Tests** — Component-level tests for [[agent_framework_langchain_langgraph|agent tools]], [[comparison_scoring_engine|scoring functions]], [[beckn_bap_client|Beckn client]].
3. **Integration Tests** — End-to-end Beckn flow tests against sandbox. [[phase4_hardening_testing_production|Phase 4 target]]: ≥ 80% code coverage.
4. **LLM Evaluation Suite** — 20+ procurement scenarios with ground-truth scoring; agent must achieve ≥ 85% accuracy (via [[observability_stack|LangSmith]]).
5. **Docker Build** — Build and tag images for each service.
6. **Image Vulnerability Scan** — Trivy scans images for CVEs before push.
7. **Push to Registry** — Tagged images pushed to ECR/ACR/GCR.
8. **Helm Deploy** — ArgoCD-triggered deployment to staging/production [[orchestration_kubernetes|Kubernetes cluster]].

> [!milestone] Phase 4 Acceptance Criteria (Weeks 13–16)
> From [[phase4_hardening_testing_production|Phase 4 Integration Testing milestone]]:
> - End-to-end test suite covering all Beckn flows (search → on_search → select → init → confirm → status).
> - Code coverage: **≥ 80%** on critical paths.
> - Evaluation suite: agent achieves **≥ 85%** accuracy.
> - CI pipeline runs in < 15 minutes end-to-end.

> [!guardrail] Security Controls in Pipeline
> - No `--no-verify` flag usage; all git hooks must pass.
> - Secrets (API keys, database passwords) are injected via GitHub Actions secrets — never stored in code or Dockerfiles.
> - All Terraform state is stored in encrypted remote backend (S3/Azure Blob with KMS encryption per [[security_compliance]]).
> - Production deployments require a manual approval gate in GitHub Actions.
