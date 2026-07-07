# Procurement Agent -- Technical Analysis

> Type: Technical inventory (not final documentation)
> Project: Agentic AI Procurement Agent on Beckn Protocol v2.0.0 -- Infosys InStep internship
> Phases covered: Phase 1, 2, 3 complete. Phase 4 deferred.
> Generated: 2026-07-07
> Sources: KnowledgeBase/, service READMEs, ADRs, CLAUDE.md (primary). Source code consulted only for gaps.

---

## How to Use This Folder

Each file is self-contained and can be read independently. Files are numbered in suggested reading order. Confidence notation: (Source: filename -- Confidence: High/Medium/Low). Inferred conclusions are marked (Inferred).

---

## File Index

| File | Contents | Best read when... |
|------|----------|-------------------|
| 01_overview.md | Project objective, scope, status, key decisions summary | Starting here |
| 02_architecture.md | Architecture patterns, component map, Beckn async flow, LangGraph state machines | Understanding the big picture |
| 03_technologies.md | Full tech stack matrix, LLM routing, embedding models, impl vs spec table | Choosing or auditing technology |
| 04_repository_structure.md | Directory layout, what lives where, naming conventions | Navigating the codebase |
| 05_modules.md | All 16+ services: responsibility, ports, inputs, outputs | Understanding any specific service |
| 06_data_flows.md | All system flows with Mermaid diagrams | Tracing data through the system |
| 07_api_core.md | orchestrator, IntentParser, beckn-bap-client endpoints | Integrating with or debugging core pipeline |
| 08_api_data_services.md | data-normalizer, catalog-normalizer, mcp-sidecar, sim-bpp, analytics, notifications | Working with data and support services |
| 09_api_erp_ml.md | erp-adapter, erp-mock, negotiation, scoring, discovery, demo gateway | ERP or ML scoring work |
| 10_database.md | All 24 tables, 9 ENUMs, 22 indexes, pgvector tables, Redis schema | Database or migration work |
| 11_configuration.md | All env vars by service with defaults | Setting up or configuring the stack |
| 12_features.md | Complete numbered feature list by category | Understanding what is implemented |
| 13_security.md | Auth, HMAC rotation, ED25519, data sovereignty, known gaps | Security review or audit |
| 14_error_handling.md | Error patterns, never-throw, circuit breakers, fail-closed logic | Debugging failures or adding error handling |
| 15_testing.md | Test inventory, patterns, coverage assessment | Running tests or improving coverage |
| 16_deployment.md | Docker Compose stack, local services, MLOps compose, Phase 4 K8s plan | Deploying or operating the system |
| 17_integrations.md | All external integrations: Beckn, SAP, Oracle, Keycloak, Kafka, Slack, Claude API | Working with external systems |
| 18_design_decisions.md | ADRs and key decisions with full rationale | Understanding why the system is built this way |
| 19_project_history.md | Phase timeline, major refactors, project evolution | Understanding history |
| 20_risks_and_limitations.md | Technical risks and current limitations with evidence | Risk assessment or pre-production hardening |
| 21_future_work.md | Phase 4 plans, NotImplementedErrors, deferred features | Planning next steps |
| 22_problems_detected.md | Contradictions, incomplete features, outdated docs, unclear decisions | Code review or debt remediation |

---

## Quick Reference

Five things every engineer should know before touching this codebase:

1. Beckn discovery is async -- never await it. See ADR-0001 and 06_data_flows.md.
2. KnowledgeBase/ describes the ORIGINAL DESIGN. The as-built system differs in 8+ areas. See 22_problems_detected.md and 03_technologies.md.
3. Two services run OUTSIDE Docker: IntentParser (:8001) and mcp-sidecar (:3000). Both require conda activate infosys_project.
4. All LLMs and embeddings are LOCAL by default. Claude API is opt-in only (ANTHROPIC_API_KEY unset = disabled).
5. Phase 4 (Kubernetes, Kafka, CI/CD) is NOT done. The system runs on Docker Compose, single host.
