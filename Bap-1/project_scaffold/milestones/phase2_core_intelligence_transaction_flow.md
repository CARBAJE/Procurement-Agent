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

| Milestone | Deliverable | Skills Required | Acceptance Criteria |
|---|---|---|---|
| Full Transaction Flow | `/init`, `/confirm`, `/status` implemented | Beckn protocol, state management | Complete order lifecycle working against sandbox |
| Catalog Normalizer | Standardizes diverse seller response formats | Data engineering, schema mapping | Handles 5+ distinct seller catalog formats correctly |
| [[comparison_scoring_engine\|Comparison Engine]] | Multi-criteria scoring with explainable reasoning | ML/AI, scoring algorithms | Ranks sellers correctly for 10+ test scenarios with clear explanations |
| [[approval_workflow\|Approval Workflow]] | Configurable threshold-based routing | Workflow engine, RBAC | Orders above threshold require and receive approval before `/confirm` |
| Comparison UI | Side-by-side offer comparison with agent reasoning | React, data visualization | Users can view, compare, and act on agent recommendations |
| [[real_time_tracking\|Real-time Tracking]] | Order status updates via `/status` polling + webhooks | WebSockets, event handling | Dashboard reflects status within **30 seconds** of change |

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

## Implementación Completada — Catalog Normalizer

> [!done] Entregado
> El **Catalog Normalizer** ha sido implementado como `src/normalizer/` dentro del proyecto `Bap-1`.

### Qué se construyó

| Componente | Archivo | Responsabilidad |
|---|---|---|
| `FormatVariant` | `src/normalizer/formats.py` | Enum con 5 variantes + predicados de detección |
| `FormatDetector` | `src/normalizer/detector.py` | Detecta el formato del catálogo raw sin IO |
| `SchemaMapper` | `src/normalizer/schema_mapper.py` | Mapeo determinista para variantes 1–4 |
| `LLMFallbackNormalizer` | `src/normalizer/llm_fallback.py` | Fallback LLM con instructor + Ollama para variante 5 |
| `CatalogNormalizer` | `src/normalizer/normalizer.py` | Fachada pública que orquesta los 3 pasos |

### Decisiones de diseño tomadas
- La lógica de `_parse_on_discover()` se **movió verbatim** a `SchemaMapper` para los Formatos A y B — sin regresiones.
- El fallback LLM sigue el mismo patrón de `IntentParser/core.py` (instructor + Ollama) para consistencia en el proyecto.
- `CatalogNormalizer` es un singleton a nivel de módulo en `client.py` — no requiere cambios en el grafo LangGraph ni en los nodos.
- La detección usa orden de reglas: ONDC (variante 4) se verifica **antes** que LEGACY (variante 2) porque los catálogos ONDC también contienen `providers[].items[]`.
- Ante error del LLM: retorna lista vacía en lugar de propagar excepción — el grafo maneja `offerings=[]` de forma graciosa (va directo a `present_results`).

### Tests
- 17 tests unitarios en `tests/test_normalizer.py` — todos pasan sin Ollama.
- Los tests existentes en `tests/test_discover.py` y `tests/test_agent.py` siguen pasando sin cambios (48 tests totales en verde).

*Preceded by → [[phase1_foundation_protocol_integration]] | Continues in → [[phase3_advanced_intelligence_enterprise_features]]*
