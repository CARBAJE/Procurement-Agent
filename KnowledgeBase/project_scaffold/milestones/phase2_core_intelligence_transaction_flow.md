---
tags: [milestone, phase-2, intelligence, transaction-flow, comparison, approval, weeks-5-8]
cssclasses: [procurement-doc, milestone-doc]
status: "#processed"
related: ["[[comparison_scoring_engine]]", "[[beckn_bap_client]]", "[[approval_workflow]]", "[[real_time_tracking]]", "[[frontend_react_nextjs]]", "[[phase1_foundation_protocol_integration]]", "[[phase3_advanced_intelligence_enterprise_features]]"]
---

# Phase 2: Core Intelligence & Transaction Flow (Weeks 5–8)

> [!milestone] Phase Objective
> Build the comparison engine, complete the Beckn transaction lifecycle, and deliver a **functional end-to-end procurement workflow** that a real user can operate. By end of Week 8, a user can submit a request, see ranked seller recommendations with explanations, approve or reject, and track order delivery in real-time — the full loop minus negotiation and memory.

## Milestones & Deliverables

| Milestone                                        | Deliverable                                           | Skills Required                  | Acceptance Criteria                                                    |
| ------------------------------------------------ | ----------------------------------------------------- | -------------------------------- | ---------------------------------------------------------------------- |
| Full Transaction Flow                            | `/init`, `/confirm`, `/status` implemented            | Beckn protocol, state management | Complete order lifecycle working against sandbox                       |
| Catalog Normalizer                               | Standardizes diverse seller response formats          | Data engineering, schema mapping | Handles 5+ distinct seller catalog formats correctly                   |
| [[comparison_scoring_engine\|Comparison Engine]] | Multi-criteria scoring with explainable reasoning     | ML/AI, scoring algorithms        | Ranks sellers correctly for 10+ test scenarios with clear explanations |
| [[approval_workflow\|Approval Workflow]]         | Configurable threshold-based routing                  | Workflow engine, RBAC            | Orders above threshold require and receive approval before `/confirm`  |
| Comparison UI                                    | Side-by-side offer comparison with agent reasoning    | React, data visualization        | Users can view, compare, and act on agent recommendations              |
| [[real_time_tracking\|Real-time Tracking]]       | Order status updates via `/status` polling + webhooks | WebSockets, event handling       | Dashboard reflects status within **30 seconds** of change              |

> [!architecture] Technical Focus Areas
> - State management for multi-step Beckn v2 transaction lifecycle: `discover` → `select` → `init` → `confirm` → `status`.
> - [[comparison_scoring_engine|Hybrid scoring]]: deterministic Python functions + [[llm_providers|GPT-4o]] ReAct reasoning.
> - [[identity_access_keycloak|RBAC enforcement]] for [[approval_workflow|approval routing]].
> - WebSocket integration for real-time status push to [[frontend_react_nextjs|frontend]].
> - [[databases_postgresql_redis|PostgreSQL]] state machine for order lifecycle tracking.

> [!insight] What Phase 2 Unlocks
> Phase 2 delivers the **minimum viable autonomous procurement system** — a user can go from natural language request to confirmed order without touching SAP Ariba. This is the first demonstrable proof point for enterprise pilots. The comparison engine's explainability is particularly important for user trust: without knowing *why* Seller A is recommended, users will override the agent reflexively rather than trusting it.

> [!milestone] Deliverables Summary — End of Week 8
> - Full ONIX-routed flow operational: `discover` (sync query to Discovery Service) → Catalog Normalization → `/bap/caller/select` → `/bap/caller/init` → `/bap/caller/confirm` → `/bap/caller/status`.
> - [[beckn_bap_client|Catalog normalizer]] handles 5+ formats.
> - [[comparison_scoring_engine]] produces ranked, explained results.
> - [[approval_workflow|Approval routing]] enforced for all role combinations.
> - [[real_time_tracking|Real-time dashboard]] live with 30-second SLA.

## Completed Implementation — Catalog Normalizer

> [!done] Delivered
> The **Catalog Normalizer** has been implemented as `src/normalizer/` inside the `Bap-1` project.

### What was built

| Component | File | Responsibility |
|---|---|---|
| `FormatVariant` | `src/normalizer/formats.py` | IntEnum with 5 variants + detection predicates |
| `FormatDetector` | `src/normalizer/detector.py` | Detects the raw catalog format — no IO, no LLM |
| `SchemaMapper` | `src/normalizer/schema_mapper.py` | Deterministic mapping for variants 1–4 |
| `LLMFallbackNormalizer` | `src/normalizer/llm_fallback.py` | LLM fallback via instructor + Ollama for variant 5 |
| `CatalogNormalizer` | `src/normalizer/normalizer.py` | Public facade that orchestrates the 3-step pipeline |

### Design decisions
- The logic of `_parse_on_discover()` was **moved verbatim** into `SchemaMapper` for Formats A and B — no behavioral regressions.
- The LLM fallback follows the same pattern as `IntentParser/core.py` (instructor + Ollama) for consistency across the project.
- `CatalogNormalizer` is a module-level singleton in `client.py` — no changes required in the LangGraph graph or its nodes.
- Detection rule ordering: ONDC (variant 4) is checked **before** LEGACY (variant 2) because ONDC catalogs also contain `providers[].items[]`.
- On LLM error: returns an empty list instead of propagating the exception — the graph handles `offerings=[]` gracefully (routes directly to `present_results`).

### Tests
- 17 unit tests in `tests/test_normalizer.py` — all pass without Ollama running.
- Existing tests in `tests/test_discover.py` and `tests/test_agent.py` continue passing without changes (77 tests total, all green).

*Preceded by → [[phase1_foundation_protocol_integration]] | Continues in → [[phase3_advanced_intelligence_enterprise_features]]*

---

## Architecture Migration — Microservices

> [!milestone] Completed: Bap-1 Monolith → Microservices (AWS Step Functions)

The Bap-1 monolith has been decomposed into 4 services under `services/` following the `architecture/Architecture.md` Step Functions model. See [[microservices_architecture]] for full detail.

### Services Delivered

| Service               | Port | Lambda Equivalent                | Status |
| --------------------- | ---- | -------------------------------- | ------ |
| `intention-parser`    | 8001 | Lambda 1 — Intention Parser      | ✅      |
| `beckn-bap-client`    | 8002 | Lambda 2 — Beckn BAP Client      | ✅      |
| `comparative-scoring` | 8003 | Lambda 3 — Comparative & Scoring | ✅      |
| `orchestrator`        | 8004 | Step Functions simulator         | ✅      |

### Agent Stack Placement

| Agent | Lambda | Location |
|-------|--------|----------|
| Parser Agent | Lambda 1 | `services/intention-parser/` via `IntentParser/` |
| Normalizer Agent | Lambda 2 | `services/beckn-bap-client/src/normalizer/` |
| Negotiator Agent | Lambda 4 (future) | `services/negotiation-engine/` |

### State

JSON payload passed between services via HTTP POST. No shared memory. Each Lambda is stateless. The orchestrator assembles the final result from each step's response.

### Skipped Lambdas (not yet implemented)

- Lambda 4 — Negotiation Engine
- Lambda 5 — Approval Engine

These will become services under `services/negotiation-engine/` and `services/approval-engine/` in a future phase.
