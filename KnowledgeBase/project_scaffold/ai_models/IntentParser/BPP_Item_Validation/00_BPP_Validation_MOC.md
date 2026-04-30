---
tags: [bpp-validation, architecture, zettelkasten, intent-parser, beckn, semantic-cache]
cssclasses: [procurement-doc, ai-doc]
status: "#approved"
related: ["[[01_Silent_Semantic_Gap]]", "[[07_Hybrid_Architecture_Overview]]", "[[07_Production_Failures_and_LLM_Fallbacks]]", "[[38_Architectural_Principles]]", "[[intent_parsing_model]]", "[[nl_intent_parser]]", "[[beckn_bap_client]]", "[[catalog_normalizer]]", "[[databases_postgresql_redis]]", "[[embedding_models]]", "[[model_governance_monitoring]]", "[[agent_framework_langchain_langgraph]]"]
---

# BPP Item Validation — Map of Content

## Architecture Summary

The approved design for BPP item existence validation in `IntentParser` (Lambda 1) is a **two-tier hybrid architecture** combining (1) a **PostgreSQL pgvector Semantic Cache** as the low-latency primary path (~15ms) and (2) a **bounded MCP Fallback Tool** as the live-network fallback for cache misses (~1–8s). A self-improving feedback loop — the **Two Writers, One Table** pattern — closes the gap between the two tiers over time by populating the cache from both proactive BPP registrations (Path A) and reactive MCP confirmations (Path B).

> [!abstract] Document Status — Single Source of Truth
> This MOC consolidates and supersedes all prior theoretical and refinement documents. It is the authoritative reference for the implementation sprint.
>
> **Approved strategy:** A two-tier hybrid architecture combining (1) a **PostgreSQL pgvector Semantic Cache** as the low-latency primary validation path and (2) a **bounded MCP Fallback Tool** as the live-network fallback for cache misses. A self-improving feedback loop closes the gap between the two tiers over time.

---

## 1. Problem Space

- [[01_Silent_Semantic_Gap]] — The Lambda 1 → Lambda 2 → Lambda 3 pipeline gap: BecknIntent is structurally valid but item may not exist in any BPP; failure is semantic, not syntactic.
- [[02_Item_Field_Failure_Modes]] — The two failure modes of `BecknIntent.item` extraction: over-specification (hallucination of specificity) and under-specification (over-generic extraction).

---

## 2. Rejected Approaches

- [[03_Double_Discover_Anti_Pattern]] — Direct API probe approach and why it violates protocol semantics, adds 10s latency, and couples Lambda 1 to Lambda 2.
- [[04_Iterative_Degradation_Search]] — Word-truncation fallback approach and why it produces false positives, has no semantic model, and compounds latency.
- [[05_Live_Network_Validation_Root_Cause]] — The shared root cause: both rejected approaches attempt live BPP network calls at intent-parse time; the async Beckn round-trip cannot be made cheap.
- [[06_Rejected_Approaches_Decision_Matrix]] — 8-criterion decision matrix comparing Probe, Degradation, and the Approved Hybrid across latency, protocol compliance, semantic accuracy, and tech stack alignment.

---

## 3. Approved Architecture

- [[07_Hybrid_Architecture_Overview]] — Stage 3 Hybrid Item Validator: PRIMARY PATH (~15ms via pgvector) and FALLBACK PATH (~1–8s via MCP) with three zones (VALIDATED / AMBIGUOUS / CACHE MISS).
- [[08_Infrastructure_Component_Alignment]] — Alignment table: PostgreSQL 16+pgvector, text-embedding-3-small, e5-large-v2, MCP Server, BecknBAP Client, and why Qdrant is explicitly excluded.

---

## 4. PostgreSQL pgvector Schema

- [[09_bpp_catalog_semantic_cache_Schema]] — Full 13-column table definition, unique constraint `(item_name, bpp_id)`, and column semantics for `source` and `embedding_strategy`.
- [[10_HNSW_Index_Strategy]] — HNSW over IVFFlat: index spec (m=16, ef_construction=64, ef_search=100) and rationale for incremental insert performance.
- [[11_Embedding_Input_Strategy]] — Path A (item_name_only) vs. Path B (item_name_and_specs) embedding input formulas; query-time strategy always uses the richer form.

---

## 5. System Flow

- [[12_Full_System_Validation_Flow]] — Complete Mermaid sequence diagram covering all participants and all branches: VALIDATED, AMBIGUOUS, CACHE MISS (MCP found / not found).

---

## 6. Similarity Threshold Theory

- [[13_Error_Types_and_Costs]] — Error Type I (false positive: wrong item ordered) and Error Type II (false negative: extra latency). Full examples with cost analysis.
- [[14_Cost_Asymmetry_Procurement_Validation]] — Why the threshold must be high: precision ≥ 0.99 target; asymmetric cost framing with Precision/Recall formulas.
- [[15_Three_Zone_Decision_Space]] — The three-zone table (VALIDATED ≥0.92, AMBIGUOUS 0.75–0.91, CACHE MISS <0.75) and the critical distinction: AMBIGUOUS is a user confirmation gate, not a fallback trigger.
- [[16_Threshold_Calibration_Methodology]] — Empirical derivation: positive pairs, hard negatives, easy negatives, 4-step procedure, and empirical guidance (0.90–0.94 band, PoC start: 0.92).
- [[17_Threshold_Sensitivity_Analysis]] — 6-row sensitivity table (0.80 → 0.98) and the note that the threshold is category-dependent and recalibrated quarterly.

---

## 7. MCP Fallback Tool

- [[18_MCP_Fallback_Tool_Overview]] — MCP server as sidecar in intention-parser; what the tool does NOT do (not a full discover replacement, not a buyer intent signal).
- [[19_search_bpp_catalog_Tool_Spec]] — Full tool specification: name, description, input parameters, and output fields.
- [[20_MCP_LLM_Reasoning_Loop]] — LLM-in-the-loop: 4-step reasoning sequence, self-correction via item_name reformulation, maximum 2 tool calls per validation cycle.
- [[21_MCP_Bounding_Constraints]] — Bounding constraints table: 3s timeout, ≤2 tool calls, ~8s max MCP path latency, and rationale for accepting missed high-latency BPPs.

---

## 8. Feedback Loop — Two Writers, One Table

- [[22_Feedback_Loop_Overview]] — The architectural warning: why routing MCP results through CatalogNormalizer was rejected. The corrected design with the TWO WRITERS — ONE TABLE ASCII diagram.
- [[23_CatalogNormalizer_SRP_Boundary]] — What CatalogNormalizer ingests, its FormatDetector four-variant table, and the three independent grounds for rejection of MCP-through-Normalizer routing.
- [[24_Two_Writers_One_Table_Pattern]] — Side-by-side comparison of Path A and Path B: triggers, source data, components, locations, embed strategies, and source column values.
- [[25_CatalogCacheWriter]] — Path A component: location, trigger, full data flow code block, why descriptions=NULL, and SRP boundary statement.
- [[26_MCPResultAdapter]] — Path B component: location, trigger, inputs, full data flow code block, why the embedding is richer than Path A, and async non-blocking constraint.
- [[27_One_Table_Rationale]] — Why one table is correct: same semantic question, explicit source/embedding_strategy columns, tie-breaking rule, Path A → Path B upgrade path.
- [[28_Feedback_Loop_Sequence_Diagram]] — Complete Mermaid sequence diagram for the corrected feedback loop: PATH A (proactive) and PATH B (reactive) with the CatalogNormalizer key invariant.
- [[29_Component_Responsibilities_Table]] — 3-row responsibility summary: CatalogNormalizer, CatalogCacheWriter, MCPResultAdapter — locations, inputs, outputs, and CatalogNormalizer call status.
- [[30_Cache_Convergence_and_Invalidation]] — Convergence property, 4-rule invalidation table (time-based, Path A re-registration, Path B re-confirmation, threshold recalibration), and 7-day staleness window.

---

## 9. API Contract

- [[31_ParseResponse_Extended_Schema]] — Full ParseResponse schema tree: intent, confidence, beckn_intent, validation (status enum, cache_hit, similarity_score, suggestions, mcp_used), routed_to.
- [[32_Orchestrator_Routing_Logic]] — 4-row routing table: VALIDATED, MCP_VALIDATED, AMBIGUOUS (block Lambda 2), NOT_FOUND (block Lambda 2) with orchestrator actions.

---

## 10. Operations

- [[33_Cold_Start_Strategy]] — 4 seeding options in priority order: replay historical callbacks, startup BPP scrape, static seed file, organic warm-up.
- [[34_Full_Component_Interaction_Map]] — Full ASCII art component interaction map: Lambda 1 box, PostgreSQL, Orchestrator, Lambda 2 BAP Client, CatalogCacheWriter, CatalogNormalizer.

---

## 11. Observability and Governance

- [[35_Stage3_Observability_Metrics]] — 9-metric table with types and alert conditions for all Stage 3 metrics.
- [[36_Drift_Detection_Rules]] — Two drift rules: mcp_fallback_rate >50% and not_found_rate >20% — evidence statements and actions.
- [[37_LangSmith_Tracing_Spec]] — Span name, input, output, tags, and sub-spans for the item_validation LangSmith trace.

---

## 12. Principles and Open Questions

- [[38_Architectural_Principles]] — All 8 architectural principles (P1–P8) with full text.
- [[39_Sprint_Open_Questions]] — All 7 open questions for the implementation sprint.

---

## 13. Production Readiness

- [[07_Production_Failures_and_LLM_Fallbacks]] — Day 2 strategy for the terminal `NOT_FOUND` state: four recovery actions (Buyer Notification, Open RFQ broadcast, Unmet Demand Logging, Query Broadening retry) and the Local-First / Claude-Fallback LLM routing architecture for spec-degradation reasoning.

---

## 14. Document Lineage

> [!note] Document Lineage
> This document consolidates and supersedes:
> - `bpp_item_validation_architecture.md` (original theoretical analysis — proposals and rejection reasoning preserved in Sections 1–2)
> - `hybrid_validation_architecture.md` (refined production architecture — fully merged; file may be deleted)
>
> Key decisions made across the refinement cycle:
> - PostgreSQL pgvector adopted over Qdrant/Redis for the semantic cache (bounded corpus, ACID, existing infrastructure)
> - MCP adopted as the fallback mechanism over a direct HTTP probe (LLM reasoning loop, self-correction)
> - `CatalogNormalizer` confirmed as **not compatible** with MCP result ingestion on three independent grounds
> - "Two Writers, One Table" pattern adopted: `CatalogCacheWriter` (Path A) and `MCPResultAdapter` (Path B)
> - `embedding_strategy` column added to make embedding fidelity differences explicit and queryable
>
> Related documentation:
> - [[nl_intent_parser]] — Lambda 1 service implementation
> - [[beckn_bap_client]] — Lambda 2 and CatalogNormalizer implementation
> - [[catalog_normalizer]] — CatalogNormalizer component detail and 17-test suite
> - [[databases_postgresql_redis]] — PostgreSQL 16 infrastructure configuration
> - [[embedding_models]] — text-embedding-3-small and e5-large-v2 specifications
> - [[model_governance_monitoring]] — Governance pipeline and drift detection thresholds
