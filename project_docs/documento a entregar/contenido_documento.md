# Contenido para "Instep Work Flow Doc.docx"

Copia cada sección en el lugar correspondiente del documento Word.

---

## 1. Background

Infosys's AI-on-DPI (AI on Digital Public Infrastructure) unit applies artificial intelligence
to open digital infrastructure protocols — government-mandated or industry-standard frameworks
that enable interoperable commerce at scale. In India and globally, these protocols (UPI for
payments, ONDC/Beckn for commerce, ABDM for health, Account Aggregator for finance) represent
a structural shift away from winner-take-all platforms toward open APIs where any participant
can transact with any other. Infosys positions itself as the trusted systems integrator that
helps enterprises adopt, build on, and scale within these open ecosystems.

The **Enterprise Procurement Transformation** sub-unit focuses on using AI-on-DPI capabilities
to modernize B2B procurement. The $9.5 billion global enterprise procurement software market
is dominated by closed systems (SAP Ariba, Coupa, Oracle Procurement Cloud) that require
expensive bilateral integration agreements with each supplier. Small or new suppliers cannot
participate without significant IT investment, which restricts buyers to a vendor roster
determined by past IT spending, not current market quality or price. The unit's charter is to
demonstrate — and ultimately productize — an architecture in which an AI-driven procurement
agent discovers and transacts with any Beckn-registered supplier without those bilateral
agreements.

This internship project is the reference implementation Infosys will use as the technical
foundation for enterprise sales. The system — the **Agentic AI Procurement Agent on Beckn
Protocol** — accepts a natural-language purchase request (e.g., "300 meters Cat6 UTP cable
Mumbai 5 days") and drives the full procurement lifecycle (discover → select → init → confirm
→ status) without manual data entry. It integrates with SAP S/4HANA and Oracle ERP Cloud for
budget gating and purchase order push, applies ML-based comparative scoring to rank supplier
offers, and maintains a SOX 404-compliant audit trail suitable for enterprise governance
requirements.

**External drivers.** ONDC (Open Network for Digital Commerce), built on Beckn Protocol,
achieved live commercial transaction volume in India in 2023, proving open-protocol B2B commerce
viable at scale. Beckn Protocol v2.0.0 (2024) extended the specification to B2B procurement
use cases, creating a first-mover opportunity for Infosys enterprise clients who want to
participate in this open network without rebuilding their procurement stack from scratch.

**Internal drivers.** Infosys required a working, documented reference implementation to
demonstrate this capability to potential enterprise clients. Building it as an InStep
internship project served two goals simultaneously: it produced a tangible technical asset
for enterprise sales, and it accelerated development by applying graduate-level AI and ML
engineering talent to a greenfield system unconstrained by legacy architecture decisions.

---

## 2. Infosys Need

Infosys operates as a large, process-driven global IT services and consulting organization,
with a strong emphasis on structure, documentation, and traceability of work. Within this
context, the AI-on-DPI unit's mission is to help enterprises modernize procurement by
combining open digital networks (like Beckn/ONDC) with agentic AI, so that buying becomes
faster, more transparent, more competitive, and more compliant. Existing enterprise
procurement platforms are expensive, restrictive, and slow — and open commerce networks
alone do not natively solve approval workflows, compliance requirements, or enterprise
auditability. This gap is precisely what the unit set out to address through this project.

**The exact need.**
The AI-on-DPI unit required a functionally complete, technically credible reference
implementation of an AI-driven procurement agent on Beckn Protocol that could: (1) be
demonstrated to enterprise clients as concrete evidence of Infosys's open-protocol AI
capabilities; (2) serve as a code base seed for productization into a managed service
targeting the $9.5 B global enterprise procurement software market; and (3) be shared as
a technical reference within the Infosys engineering community.

**How it fits within the unit.**
The unit's value proposition to clients is: "Infosys can integrate your enterprise
procurement systems with open digital commerce networks, replacing closed, bilateral EDI
agreements with a standards-based, AI-augmented workflow." This project provides the
working proof-of-concept for that proposition — an agent that accepts a natural-language
request, discovers suppliers across a Beckn network, scores and negotiates offers, enforces
enterprise approval policies, and writes a confirmed purchase order to an ERP system, all
without manual data entry. Concrete performance targets validate the proposition:
P95 agent latency < 5 seconds, ML ranking accuracy ≥ 85%, and 8–15% average cost
reduction through automated negotiation.

**Value the interns bring to the unit.**
The internship team brought fresh technical perspectives and current expertise in areas
that are central to this project — large language models, vector databases, open-protocol
engineering, and async distributed systems — applied to a greenfield system where no legacy
constraints existed. Rather than maintaining or extending an established codebase, the
interns designed and built the full system from scratch over 16 weeks, making architectural
decisions that will directly shape the productization roadmap.

Each intern owned an independent vertical slice of the system end-to-end:

- **Eduardo García Díaz** led the Beckn protocol integration layer (ONIX Go adapter,
  ED25519 signing, Redis Pub/Sub async discovery decoupling), the three-stage NL
  IntentParser pipeline (LLM intent classification + structured BecknIntent extraction +
  pgvector ANN validation), and the Next.js 13 buyer-facing frontend (procurement wizard,
  real-time order tracking, audit trail viewer).

- **José Emiliano Carrillo Barreiro** built the orchestrator pipeline state machine
  (LangGraph), the autonomous negotiation engine (LangGraph + three-layer policy
  guardrails, 20% maximum discount cap), and the multi-service async Python microservices
  layer (aiohttp, FastAPI).

- **Cristian Montiel García** implemented the agent memory system (pgvector RAG with
  time-decayed supplier loyalty bonuses), the SOX 404-compliant audit trail (9 event
  types, 7-year retention), and the analytics dashboard (spend KPIs, cycle-time
  metrics, CPO benchmarking vs. contracted price).

This division allowed three independent workstreams to progress in parallel, compressing
a development effort that would otherwise have taken a dedicated engineering team
significantly longer, while producing a system that integrates cohesively across all layers.

**Key stakeholders.**

| Stakeholder | Role |
|---|---|
| Monirul Islam | Project Mentor and unit lead; primary technical decision-maker and approver |
| Eduardo García Díaz | Intern — protocol integration, NL pipeline, frontend |
| José Emiliano Carrillo Barreiro | Intern — orchestrator, negotiation engine, microservices |
| Cristian Montiel García | Intern — agent memory, audit trail, analytics |
| Infosys AI-on-DPI unit leadership | Approvers of technical direction and productization roadmap |
| Corporate procurement officers | Future end-users: issue purchase requests via the web dashboard |
| Procurement approvers (managers, CFOs) | Decision-makers in the multi-tier approval workflow built into the system |
| IT / ERP administrators | Deploy and configure the Docker Compose stack and ERP connectors |

---

## 3. Internship Deliverables

This 16-week internship (April 7 – July 25, 2026) delivers a functionally complete
reference implementation across four sequential phases.

### Phase 1 — Foundation & Protocol Integration (Weeks 1–4, Apr 7 – May 2)
- Beckn ONIX Go adapter (onix-bap, onix-bpp) deployed with ED25519 signing verified.
- Full Beckn API lifecycle: discover → select → init → confirm → status, end-to-end with local BPP simulator.
- Three-stage NL IntentParser (qwen3:8b via local Ollama + instructor Mode.JSON retry loop).
- LangGraph ReAct agent framework scaffolded.
- PostgreSQL 16 + pgvector schema (24 numbered SQL migration files).
- Shared Pydantic v2 domain models: BecknIntent, DiscoverOffering.

### Phase 2 — Core Intelligence & Transaction Flow (Weeks 5–8, May 5 – May 30)
- Six-service microservices pipeline: beckn-bap-client, catalog-normalizer, data-normalizer, comparative-scoring, orchestrator, analytics.
- IntentParser Stage 3: hybrid pgvector ANN (384-dim cosine HNSW) + MCP sidecar live Beckn probe.
- ADR-0001: Redis Pub/Sub async discovery decoupling (asyncio event-loop deadlock solved).
- sim-bpp: custom Node.js BPP simulator replacing fidedocker/sandbox-2.0, with hot-reloadable catalog.
- RankNet ML scoring model (PyTorch learning-to-rank, MLflow MLOps stack).
- ERP adapter: synchronous budget gate (≤ 800 ms) + PostgreSQL outbox retry with per-vendor circuit breakers (SAP / Oracle / mock).
- Next.js 13 frontend scaffold (Radix UI + Tailwind) with advisory procurement flow end-to-end.

### Phase 3 — Advanced Intelligence & Enterprise Features (Weeks 9–12, Jun 2 – Jun 27)
- Agent memory: time-decayed supplier loyalty bonuses via pgvector RAG (BAAI/bge-small-en-v1.5 384-dim).
- SOX 404-compliant audit trail: 9 event types, 7-year retention, 20+ instrumentation call sites in the orchestrator.
- RBAC three-tier approval workflow: auto-approve / manager / CFO routing with spend threshold configuration.
- LangGraph autonomous negotiation engine with three independent guardrail layers and 20% maximum discount cap.
- Real-time order tracking: WebSocket + sim-bpp auto-advance lifecycle (ACCEPTED → PACKED → SHIPPED → DELIVERED).
- Kafka → Slack Block Kit / Teams Adaptive Card / SMTP email notification fan-out.
- Analytics dashboard: spend KPIs, cycle-time metrics, CPO benchmarking vs. contracted price.
- Keycloak OIDC authentication integration.

### Phase 4 — Hardening & Production Readiness (Weeks 13–16, Jun 30 – Jul 25)
- Kubernetes + Helm chart + ArgoCD GitOps configuration.
- GitHub Actions CI/CD pipeline: lint → pytest → docker build → helm package.
- OWASP Top 10 security review and critical findings remediated.
- Integration test suite covering all Beckn flows and critical-path services.
- Evaluation suite: 20+ procurement scenarios, accuracy target ≥ 85%.
- Full documentation package: 18 Markdown files (Architecture, API Reference, System Design, Database, Deployment, Security, Testing, Troubleshooting, Configuration, Components, Glossary, and more).

### How the deliverables will be used
The complete reference implementation serves as: (1) a live demo asset for Infosys enterprise
sales engagements; (2) a code base seed for the productization track (Phase 4 Kubernetes
hardening brings it to enterprise-deployable state); and (3) a technical reference for
Infosys engineers onboarding to Beckn Protocol development.

### Support anchors
- **Primary mentor:** Monirul Islam (AI-on-DPI unit)
- **Backup mentor:** to be designated from the AI-on-DPI unit leadership

### Performance measures for successful completion
- All five Beckn protocol actions (discover / select / init / confirm / status) complete end-to-end in the Docker Compose stack.
- NL intent parser correctly classifies and extracts BecknIntent from ≥ 85% of test inputs.
- P95 agent response latency < 5 seconds for standard procurement requests.
- Audit trail captures all 9 event types with complete FK chain persisted to PostgreSQL.
- Full documentation package delivered and reviewed by the unit.
- Final demo walkthrough presented to Monirul Islam and unit stakeholders.

---

## 4. Post Internship

**Who will carry this project forward.**
The AI-on-DPI | Enterprise Procurement Transformation unit will continue the project under
the oversight of Monirul Islam. The reference implementation provides a stable, fully
documented code base suitable for handoff to an Infosys engineering team for productization.

**Implementation plan.**

1. The Infosys engineering team completes Phase 4 hardening: Kubernetes cluster deployment
   (AWS EKS / Azure AKS / GKE), full CI/CD pipeline, and OWASP Top 10 pen test sign-off.

2. Live Beckn network registration replaces the local sim-bpp simulator. This requires only
   YAML configuration changes in the four ONIX routing files
   (`targetType: url` → `targetType: bpp`, add `registryUrl`) — no code changes to any
   service are needed.

3. Kafka is promoted to the primary event bus, replacing the PostgreSQL outbox for ERP
   purchase order push. The `kafka_offset` placeholder column in `erp_sync_records`
   pre-wires this migration path.

4. The evaluation suite (≥ 20 procurement scenarios, ≥ 85% accuracy) is finalized and
   published as the production qualification benchmark.

5. A pilot enterprise deployment is executed on a client Kubernetes cluster using the
   Helm chart produced in Phase 4.

**Documentation completed for handover** (available in `project_docs/documentation/`):

| File | Contents |
|---|---|
| ARCHITECTURE.md | System map, component reference, Beckn integration, port table |
| SYSTEM_DESIGN.md | Architectural decisions (ADR-0001 + 7 additional), communication patterns |
| API_REFERENCE.md | Endpoint contracts and request/response shapes for all 18 services |
| DATABASE.md | PostgreSQL schema, 24-migration FK dependency chain, pgvector index specs |
| DEPLOYMENT.md | Docker Compose startup, environment variables, first-time setup runbook |
| ENVIRONMENT.md | Complete environment variable reference per service |
| SECURITY.md | Authentication (Keycloak OIDC), secrets management, RBAC, audit trail spec |
| TESTING.md | pytest structure, asyncio_mode, test modes (unit / integration / live) |
| TROUBLESHOOTING.md | Common failure modes, diagnostic commands, Redis/ONIX/Ollama checks |
| CONFIGURATION.md | ONIX routing YAML structure and critical rules |
| COMPONENTS.md | Per-service responsibilities, known gotchas, dependency matrix |
| GLOSSARY.md | Beckn v2.0.0 terminology and domain definitions |

---

## 5. Project Plan & Progress Report

### Deliverables expected (biweekly)

| Weeks | Deliverables |
|---|---|
| **Weeks 1 & 2** (Apr 7–18) | Dev environment setup (Docker Compose, conda, PostgreSQL+pgvector, Redis, Ollama). Beckn ONIX adapter deployed; ED25519 signing verified; ONIX pinned to commit d43ec30d. First successful /discover → on_discover webhook call end-to-end. |
| **Weeks 3 & 4** (Apr 21 – May 2) | Full Beckn lifecycle (discover→select→init→confirm→status) with sim-bpp. NL IntentParser Stages 1 & 2 operational (qwen3:8b + instructor). BecknIntent anti-corruption layer defined. LangGraph ReAct agent scaffolded; PostgreSQL schema v1 applied. |
| **Weeks 5 & 6** (May 5–16) | Six-service microservices pipeline wired end-to-end. IntentParser Stage 3: pgvector ANN + MCP sidecar probe. ADR-0001 Redis Pub/Sub async discovery decoupling live (asyncio deadlock solved). sim-bpp AND-token catalog matching verified. |
| **Weeks 7 & 8** (May 19–30) | RankNet ML scoring integrated (comparative-scoring service). ERP adapter: budget gate + PostgreSQL outbox retry. Next.js 13 frontend advisory flow end-to-end. data-normalizer sole-write-path constraint enforced; FK chain tests passing. |
| **Weeks 9 & 10** (Jun 2–13) | Agent memory (pgvector RAG, time-decayed loyalty bonuses) integrated. SOX 404 audit trail: 9 event types, 20+ call sites. RBAC approval workflow: auto-approve / manager / CFO tiers live. |
| **Weeks 11 & 12** (Jun 16–27) | LangGraph autonomous negotiation engine with 3-layer guardrails deployed. Real-time order tracking (WebSocket + sim-bpp auto-advance). Kafka notification fan-out (Slack / Teams / email). Analytics dashboard: 6+ spend metrics and CPO benchmarking. |
| **Weeks 13 & 14** (Jun 30 – Jul 11) | Kubernetes Helm chart drafted; ArgoCD GitOps configuration. GitHub Actions CI/CD pipeline. OWASP Top 10 security review; critical findings remediated. Integration test suite: Beckn flow assertions, critical-path coverage. |
| **Weeks 15 & 16** (Jul 14–25) | Full documentation package complete (18 .md files). Evaluation suite: 20+ procurement scenarios scored. Final demo presented to Monirul Islam. Handoff package: codebase, docs, deployment runbook, Helm chart. |

---

### Progress Report Summaries

| ID | Week Ending | Summary |
|---|---|---|
| 1 | April 18, 2026 (Wks 1–2) | Set up the full development environment across the team: Docker Compose stack, Conda environment, PostgreSQL with pgvector extension, Redis, and local Ollama with the LLM models required for the intent parser. My primary focus was the Beckn Sandbox Setup — deploying the ONIX Go adapter (onix-bap and onix-bpp) and verifying ED25519 message signing end-to-end. During this process I identified a breaking bug introduced in a later upstream ONIX commit that corrupted signature validation, and resolved it by pinning the adapter image to the last stable version. By the end of the period the system was successfully sending a signed /search request to the Beckn sandbox and receiving a valid /on_search callback. |
| 2 | May 2, 2026 (Wks 3–4) | Completed the Core API Flows milestone: implemented the /search, /on_search, and /select flows end-to-end, parsing responses from multiple sellers. In parallel, the team worked on the NL Intent Parser (LLM-based structured intent extraction), the LangGraph ReAct agent framework scaffold, and the initial PostgreSQL schema covering requests, offers, orders, and audit events. By the end of Week 4 the system could take a natural-language procurement request, parse it into a structured intent, and execute a Beckn /search → /on_search → /select sequence against the sandbox, with results stored in the database. |
| 3 | May 16, 2026 (Wks 5–6) | Delivered the Full Transaction Flow milestone: implemented /init, /confirm, and /status to complete the Beckn order lifecycle, and validated the full sequence against the local BPP simulator. This required solving an asynchronous callback challenge — Beckn returns only an ACK on /search, with the catalog arriving later via webhook. I resolved this by introducing a Redis Pub/Sub channel per transaction so the MCP sidecar can subscribe before firing the request and unblock when the callback arrives, without deadlocking the async event loop. The team also completed the Catalog Normalizer service, which standardizes the five distinct seller response formats into a consistent internal model. |
| 4 | May 30, 2026 (Wks 7–8) | My focus this period was the Comparison UI: built the side-by-side offer comparison panel in the Next.js frontend, showing agent recommendations alongside scoring rationale so buyers can review, compare, and act on ranked offers. The team simultaneously delivered the Comparison Engine (multi-criteria ML scoring with explainable rankings), the configurable Approval Workflow (threshold-based RBAC routing to manager or CFO), and Real-time Order Tracking (WebSocket updates reflecting order status within 30 seconds). By end of Week 8 the full advisory procurement flow — NL input → Beckn discovery → scored comparison → buyer decision → confirmed PO — was working end-to-end through the frontend. |
| 5 | June 13, 2026 (Wks 9–10) | Worked on the ERP Integration milestone: built the bidirectional sync layer between the procurement agent and SAP/Oracle ERP systems, implementing a synchronous budget gate that validates available budget before any purchase order is confirmed, and an asynchronous PO push with retry logic and per-vendor circuit breakers. The team also progressed on the Negotiation Engine (automated price negotiation with strategy-based /select modifications and policy guardrails) and began the Agent Memory system (vector database storing past procurement patterns for RAG-based recommendations). |
| 6 | June 27, 2026 (Wks 11–12) | Delivered the Analytics Dashboard milestone: built the spend analysis, savings tracking, and supplier performance metrics dashboard using Recharts, covering 6+ KPIs with drill-down capability and a CPO benchmarking view comparing contracted price vs. live Beckn market price. The team completed the remaining Phase 3 milestones: the Negotiation Engine went live with configurable strategies and three-layer guardrails; Agent Memory became operational with similarity search retrieving past procurement patterns; and the Audit Trail System was fully instrumented, capturing every agent decision and producing a reconstructable decision chain for compliance purposes. |
| 7 | July 11, 2026 (Wks 13–14) | Phase 4 hardening underway across the team. Worked on containerization and deployment automation: created Docker Compose configuration for the full 18-service stack and began drafting the Kubernetes Helm chart for production deployment. The team ran a security review against the OWASP Top 10, remediated the critical findings (secrets management and webhook input validation), and wrote the integration test suite covering all Beckn flows and critical-path service interactions. Performance profiling confirmed P95 agent latency below 5 seconds for standard procurement requests. |
| 8 | July 25, 2026 (Wks 15–16) | Final week of the internship. Led the Documentation & Demo milestone: produced the full documentation package (Architecture, API Reference, System Design, Deployment, Security, Testing, Troubleshooting, and more — 18 Markdown files in total) and prepared a final demo covering the complete procurement lifecycle from natural-language input through Beckn discovery, ML scoring, negotiation, ERP confirmation, and audit trail review. The evaluation suite was finalized with 20+ procurement scenarios spanning standard, complex, and emergency sourcing cases. The demo was presented to Monirul Islam and the unit. The full handoff package — codebase, documentation, deployment runbook, and Helm chart — was delivered to the AI-on-DPI team for the productization track. |
