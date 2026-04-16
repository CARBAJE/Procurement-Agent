---
tags: [index, overview, procurement-agent, beckn-protocol, ondc, infosys, agentic-ai]
cssclasses: [procurement-doc]
status: "#processed"
---

# Project Scaffold — Agentic AI Procurement Agent on Beckn Protocol

> [!architecture] Project Overview
> This vault documents the complete technical architecture for an **enterprise-grade agentic AI procurement system** built on the Beckn/ONDC open commerce protocol. The system acts as an intelligent [[beckn_bap_client|Beckn Application Platform (BAP)]], replacing closed procurement platforms (SAP Ariba, Coupa) with an open-network, autonomously-negotiating AI agent. Source: Infosys Strategic Briefing — AI-on-DPI | Enterprise Procurement Transformation.

Generated from: `Procurement_Agent_Beckn_Protocol.md`

---

> [!insight] Quick Numbers
> - **$9.5B** global enterprise procurement software market (IDC, 2025)
> - **$30–100M** Infosys pipeline from 15–20 enterprise deployments
> - **45 seconds** vs. 5–7 days for routine procurement ([[story1_routine_office_supply|Story 1]])
> - **16 weeks** from kickoff to production-ready prototype
> - **5 AI models**, **10 components**, **14 technologies**, **4 phases**

---

## Vault Structure

```
project_scaffold/
├── .obsidian/snippets/project-theme.css   ← CSS callout theme (5 custom types)
├── technologies/     (14 files) — languages, frameworks, databases, APIs
├── components/       (10 files) — architectural modules and microservices
├── milestones/       (4 files)  — 16-week implementation roadmap
├── infrastructure/   (5 files)  — deployment, CI/CD, cloud, data pipeline
├── integrations/     (4 files)  — ERP, identity, audit, communication
├── ai_models/        (5 files)  — AI/ML model specs and governance
├── user_stories/     (5 files)  — end-to-end procurement scenarios
└── kpis_metrics/     (3 files)  — technical, business, and adoption KPIs
```

---

## technologies/

| File | Contents |
|---|---|
| [[frontend_react_nextjs]] | React 18, Next.js 14, TypeScript, Tailwind CSS, ShadCN UI |
| [[api_gateway]] | Kong Gateway / AWS API Gateway; RBAC enforcement |
| [[agent_framework_langchain_langgraph]] | LangChain, LangGraph, ReAct loop; 3 operating modes |
| [[llm_providers]] | GPT-4o (primary), Claude Sonnet 4.6 (fallback), GPT-4o-mini |
| [[beckn_client]] | beckn-onix Go adapter (BAP/BPP) + Python agent HTTP client; ED25519 signing |
| [[databases_postgresql_redis]] | PostgreSQL 16 (transactional), Redis 7 (caching, 15-min TTL) |
| [[vector_db_qdrant_pinecone]] | Qdrant (self-hosted, preferred) / Pinecone (managed) |
| [[event_streaming_kafka]] | Apache Kafka — central event bus for all data flows |
| [[orchestration_kubernetes]] | Kubernetes (EKS/AKS/GKE), Helm, ArgoCD GitOps |
| [[observability_stack]] | Prometheus, Grafana, OpenTelemetry, LangSmith |
| [[cicd_pipeline]] | GitHub Actions, Docker, Terraform; 8-stage pipeline |
| [[security_encryption]] | TLS 1.3, AES-256, KMS, Okta/Azure AD; 5-dimension security |
| [[embedding_models]] | text-embedding-3-large, e5-large-v2; HNSW + cosine similarity |
| [[data_visualization]] | Recharts, D3.js; 6+ dashboard metrics |

---

## components/

| File | Contents |
|---|---|
| [[nl_intent_parser]] | NL → Beckn JSON; GPT-4o with schema-constrained decoding; ≥ 95% accuracy |
| [[beckn_bap_client]] | All 6 Beckn flows via ONIX adapter; ED25519 signing; catalog normalization layer |
| [[comparison_scoring_engine]] | Hybrid scoring (Python + ReAct); explainability; ≥ 85% quality |
| [[negotiation_engine]] | Strategy-based /select; 20% discount cap; per-category config |
| [[agent_memory_learning]] | Vector DB RAG; < 100ms retrieval; cross-enterprise learning |
| [[approval_workflow]] | Threshold RBAC routing; emergency countdown; L1 government mode |
| [[audit_trail_system]] | Kafka → Splunk; full reasoning capture; SOX/GDPR/RTI |
| [[analytics_dashboard]] | Spend analysis, benchmarking reports; CPO use case |
| [[erp_integration]] | SAP OData + Oracle REST; real-time budget checks; PO sync |
| [[real_time_tracking]] | /status polling + WebSocket push; 30-second SLA |

---

## milestones/

| File | Timeline | Key Deliverables |
|---|---|---|
| [[phase1_foundation_protocol_integration]] | Weeks 1–4 | Beckn sandbox, NL parser, agent framework, data model |
| [[phase2_core_intelligence_transaction_flow]] | Weeks 5–8 | Full Beckn lifecycle, comparison engine, approval workflow |
| [[phase3_advanced_intelligence_enterprise_features]] | Weeks 9–12 | Negotiation, memory, ERP integration, audit trail |
| [[phase4_hardening_testing_production]] | Weeks 13–16 | Security hardening, containerization, 85% eval accuracy |

---

## infrastructure/

| File | Contents |
|---|---|
| [[kubernetes_deployment]] | EKS/AKS/GKE service topology; docker-compose local dev |
| [[cloud_providers]] | AWS Mumbai / Azure India; data residency requirements |
| [[data_pipeline_architecture]] | Kafka-centric event pipeline; all source → sink flows |
| [[observability_monitoring]] | Prometheus + Grafana + OpenTelemetry + LangSmith SLAs |
| [[security_compliance]] | SOX, GDPR, IT Act 2000, OWASP Top 10; 5-dimension model |

---

## integrations/

| File | Contents |
|---|---|
| [[identity_access_keycloak]] | Keycloak, SAML 2.0, OIDC, Okta, Azure AD; 3 RBAC roles |
| [[erp_sap_oracle]] | SAP OData + Oracle REST; budget check + PO sync flows |
| [[audit_splunk_servicenow]] | SIEM sink via Kafka; SOX/RTI compliance coverage |
| [[communication_slack_teams]] | Webhooks, approval one-click, conversational interface |

---

## ai_models/

| File | Contents |
|---|---|
| [[intent_parsing_model]] | GPT-4o + Claude Sonnet 4.6 fallback; few-shot; ≥ 95% accuracy |
| [[comparison_scoring_model]] | Hybrid deterministic + ReAct; ≥ 85% agreement vs. expert |
| [[negotiation_strategy_model]] | Rules + LLM + RL; 20% max discount; configurable per category |
| [[memory_retrieval_model]] | Qdrant + HNSW; < 100ms; RAG retrieval pattern |
| [[model_governance_monitoring]] | Model registry, eval pipeline, drift detection, LangSmith tracing |

---

## user_stories/

| File | Persona | Headline Outcome |
|---|---|---|
| [[story1_routine_office_supply]] | Priya Sharma (Procurement Coordinator) | 5–7 days → **45 seconds** |
| [[story2_high_value_it_equipment]] | Rajesh Menon (IT Director) | 3–4 weeks → **2 days**; CFO approval in 10 min |
| [[story3_emergency_procurement]] | Anita Desai (Facilities Manager) | 4–6 hours → **3 minutes**; full compliance |
| [[story4_strategic_sourcing_analysis]] | Vikram Patel (CPO) | 2-week analysis → **4 hours**; ₹8–12 crore savings |
| [[story5_government_emarketplace]] | Dr. Meera Krishnan (District Collector) | 15–30 days → **2–3 days**; automated RTI |

---

## kpis_metrics/

| File | Key Targets |
|---|---|
| [[technical_performance_metrics]] | P95 < 5s; Beckn API ≥ 99.5%; intent accuracy ≥ 95% |
| [[business_impact_metrics]] | 70–90% cycle time reduction; 8–15% cost savings; $30–100M pipeline |
| [[user_adoption_metrics]] | 500+ users at 12 months; NPS ≥ 50; override rate < 25% |

---

> [!guardrail] CSS Theme Active
> This vault uses `project-theme.css` from `.obsidian/snippets/`. Enable it in Obsidian → Settings → Appearance → CSS Snippets. Five custom callout types are defined: `[!architecture]` 🏗️ · `[!milestone]` 🚩 · `[!tech-stack]` ⚙️ · `[!guardrail]` 🛡️ · `[!insight]` 💡. Each has a distinct animation: glow, shimmer, pulse, breathe, slide.
