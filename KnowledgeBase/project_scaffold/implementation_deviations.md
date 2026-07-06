---
tags: [meta, implementation, deviations, design-decisions, as-built]
cssclasses: [procurement-doc]
status: "#living-document"
related: ["[[memory_retrieval_model]]", "[[llm_providers]]", "[[embedding_models]]", "[[vector_db_qdrant_pinecone]]", "[[kubernetes_deployment]]", "[[erp_integration]]"]
---

# Implementation Deviations — Design vs. As-Built

This document records every intentional divergence between the original KnowledgeBase design specs and the actual implementation (Phases 1–3). Its purpose is to prevent a future engineer from reading a design doc, assuming it reflects the code, and making wrong decisions.

**Rule:** when a deviation is resolved in a future phase (e.g., Qdrant is added in Phase 4), update this table and mark the row resolved.

---

## Technology Substitutions

| Area | Design Spec | As Implemented | Reason | Where to look |
|---|---|---|---|---|
| Vector store | Qdrant (self-hosted) + pgvector mirror | **pgvector only** | Zero additional infra; pilot corpus < 100K records where pgvector HNSW is sufficient | [[vector_db_qdrant_pinecone]] |
| Embedding model (primary) | OpenAI `text-embedding-3-large` (3072 dims) | **`BAAI/bge-small-en-v1.5`** (384 dims, fastembed ONNX) for agent memory; **`all-MiniLM-L6-v2`** for BPP semantic cache | No external API calls; offline operation; data sovereignty | [[embedding_models]] |
| Embedding model (fallback) | `e5-large-v2` (self-hosted) | **Not used** | Superseded by the above two models | [[embedding_models]] |
| Vector dimension | 3072 | **384** | Follows from model choice above | `database/sql/22_agent_memory_vector_dim.sql` |
| Primary LLM | GPT-4o (OpenAI) | **`qwen3:8b` via local Ollama** | Zero cost; offline; data sovereignty; quality sufficient for structured extraction | [[llm_providers]] |
| Lightweight LLM | GPT-4o-mini | **`qwen3:1.7b` via local Ollama** (for simple Stage 2 queries) | Same reasons as above | [[llm_providers]] |
| LLM fallback | `claude-sonnet-4-6` for intent parsing | **`claude-sonnet-4-6` for Stage 3 broadening only** (opt-in, `ANTHROPIC_API_KEY`) | Claude is the last resort, not the primary fallback | [[llm_providers]] |
| BPP network partner | `fidedocker/sandbox-2.0` | **`sim-bpp` (local Node.js)** | sandbox-2.0 had fixed catalog; sim-bpp hot-reloads catalog.json and supports auto-advance lifecycle | [[sim_bpp]] |
| ERP event bus | Kafka (primary) | **Outbox in PostgreSQL** (Kafka publish deferred to Phase 4) | Kafka broker not yet deployed; `kafka_offset` column exists as placeholder | [[erp_integration]] |
| Audit event bus | Kafka (7-year retention, replication ≥ 3) | **Direct PostgreSQL insert** (`kafka_offset` placeholder, `splunk_indexed` flag) | Same as above; Kafka integration deferred | [[audit_trail_system]] |
| LLM tracing | LangSmith | **`reasoning_payload` JSONB in audit_trail_events** | LangSmith deferred; data is captured and ready for wiring | [[model_governance_monitoring]] |

---

## Deployment Model

| Area | Design Spec | As Implemented | Reason | Where to look |
|---|---|---|---|---|
| Container orchestration | Kubernetes (EKS / AKS / GKE) + Helm + ArgoCD | **Docker Compose** (single host, 16+ containers) | Phase 4 scope; all containers are K8s-ready | [[kubernetes_deployment]] |
| Cloud provider | AWS Mumbai / Azure India | **Local development machine** | Pilot; no cloud budget in internship scope | [[cloud_providers]] |
| API Gateway | Kong | **Not deployed** (direct HTTP between services via Docker DNS) | Phase 4 scope | [[api_gateway]] |
| CI/CD | GitHub Actions: lint → test → build → Helm deploy | **Manual** (`docker compose up`) | Phase 4 scope | [[cicd_pipeline]] |
| Image scanning | Trivy in CI pipeline | **Not configured** | Phase 4 scope | [[kubernetes_deployment]] |

---

## Architecture Simplifications

| Area | Design Spec | As Implemented | Reason |
|---|---|---|---|
| ERP PO push | Synchronous Kafka event → consumer | Async outbox worker polling `erp_sync_records` | Kafka not deployed; outbox pattern is operationally equivalent and simpler |
| Agent memory: Qdrant nightly ETL | PostgreSQL → Qdrant batch sync (nightly) | No ETL — pgvector is the sole store | Moot given the vector store substitution |
| Model governance pipeline | Weekly evaluation suite (100 scenarios) via GitHub Actions | Not implemented; schema exists | Requires training data corpus; deferred to Phase 4 |
| SIEM integration | Splunk sink + ServiceNow ticket creation | `splunk_indexed` flag column exists; no actual Splunk exporter | Phase 4 scope |
| Retention enforcement | Nightly DELETE/archival job | `retention_until` timestamp exists; no job | Phase 4 scope |
| mTLS to SAP/Oracle | Required for some on-prem tenants | SSL context hook wired but not activated | No on-prem tenant in pilot |

---

## Features Implemented Beyond Original Spec

These were added during implementation and are **not** in the original KnowledgeBase design docs:

| Feature | Service | Notes |
|---|---|---|
| Redis Pub/Sub async decoupling for Beckn discovery | `mcp-sidecar`, `beckn-bap-client` | Solves deadlock from holding HTTP connection open. See `docs/architecture/decisions/ADR-0001`. |
| Dual-secret HMAC rotation for ERP webhooks | `erp-adapter` | Zero-downtime secret rotation via `_NEXT` suffix pattern |
| Per-vendor circuit breakers | `erp-adapter` | `pybreaker` per vendor — SAP outage isolated from Oracle |
| AND-token catalog matching | `sim-bpp` | Filters filler tokens (location, timeline) before matching — prevents every item from matching |
| ONIX schema validator pin at commit `d43ec30d` | `config/generic-bap.yaml`, `config/generic-bpp.yaml` | Later commits introduced `$ref` resolution bug in `SignatureHeader` |
| `on_discover` split routing (dedicated endpoint vs. `/bap/receiver`) | `config/generic-routing-BAPReceiver.yaml` | Required for Redis Pub/Sub path — on_discover must publish to Redis, not just dispatch |
| DeDi registry bypass (`targetType: url`) | All ONIX routing YAMLs | Allows full Beckn flow inside Docker network without ngrok or external registration |
