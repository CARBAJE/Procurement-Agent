---
tags: [moc, intent-parser, pipeline, architecture, beckn, nlp, two-stage, instructor, pydantic, sprint-ready]
cssclasses: [procurement-doc, ai-doc, moc]
status: "#approved"
related: ["[[nl_intent_parser]]", "[[beckn_bap_client]]", "[[microservices_architecture]]", "[[model_governance_monitoring]]", "[[llm_providers]]", "[[BPP_Item_Validation/00_BPP_Validation_MOC]]"]
---

# Intent Parsing Core — Map of Content

> [!abstract] Architecture Summary
> The intent parsing pipeline is a **two-stage, schema-validated NLP system** for enterprise procurement intent extraction on the Beckn Protocol. Stage 1 classifies free-form user queries and gates non-procurement intents. Stage 2 — activated only for procurement queries — extracts a fully structured `BecknIntent` object ready for the Beckn `discover` query. The pipeline runs inside [[nl_intent_parser|Lambda 1 (NL Intent Parser, port 8001)]] and uses `instructor` + Pydantic v2 for guaranteed structured output, a heuristic complexity router for compute efficiency, and an automatic validation feedback loop for reliability. In production, this feeds directly into [[beckn_bap_client|Lambda 2 (BAP Client)]] and is further validated by the [[BPP_Item_Validation/00_BPP_Validation_MOC|BPP Item Validation]] layer.

---

## 1. Pipeline Architecture

The entry points for understanding the full system:

- [[01_Two_Stage_Pipeline_Overview]] — Full pipeline ASCII diagram; Stage 1 → domain gate → Stage 2 → output; the architectural anchor for all other notes
- [[02_Stage1_IntentClassifier]] — Domain gatekeeper; open vocabulary design; system prompt strategy; fixed `qwen3:8b`
- [[03_Stage2_BecknIntentParser]] — Deep structured extraction; Beckn field challenges table; model selection; anti-corruption layer
- [[04_Domain_Gating_Procurement_Intents]] — `_PROCUREMENT_INTENTS` set; short-circuit logic; why non-procurement queries must never reach Stage 2

---

## 2. Data Schemas

The Pydantic models that define the pipeline's input/output contracts:

- [[05_ParsedIntent_Schema]] — Stage 1 output: `intent`, `product_name`, `quantity`, `confidence`, `reasoning`; open `str` vs. `Literal` design decision; `@field_validator("confidence")`
- [[06_BecknIntent_Schema]] — Stage 2 output: `item`, `descriptions`, `quantity`, `location_coordinates`, `delivery_timeline`, `budget_constraints`; runtime validators; role as shared model across all Lambdas
- [[07_BudgetConstraints_Schema]] — Nested model inside `BecknIntent`: `{min: float, max: float}`; `min=0.0` default for upper-bound-only queries; why a range, not a scalar

---

## 3. Core Technologies

The three interlocking libraries that make structured LLM output reliable:

- [[08_Instructor_Library_Integration]] — How `instructor` wraps the OpenAI client; schema injection; response parsing; automatic retry loop; backend portability
- [[09_Pydantic_v2_Schema_Enforcement]] — `Field(description=...)` as runtime LLM instructions; `@field_validator` as constraint enforcement and retry triggers; why custom validators over `Annotated` constraints
- [[17_Schema_Constrained_Decoding]] — Why JSON mode / schema-constrained decoding eliminates an entire class of runtime failures; what it guarantees and what it does not

---

## 4. Model Routing and Configuration

How models are selected and configured for each query:

- [[10_Heuristic_Complexity_Router]] — `is_complex_request()` function; four signals ordered by cost; fallback escalation on retry exhaustion; production mapping to GPT-4o-mini / GPT-4o
- [[11_Routing_Keyword_Signal_Sets]] — `_DELIVERY_KEYWORDS` and `_BUDGET_KEYWORDS` frozensets; `O(1)` membership testing; how to extend
- [[16_Model_Configuration]] — Role in the AI stack; GPT-4o primary / Claude Sonnet 4.6 fallback / GPT-4o-mini lightweight; why no fine-tuning initially

---

## 5. Reliability Mechanisms

How the pipeline handles LLM failures, edge cases, and non-determinism:

- [[12_Retry_Mechanism_Validation_Feedback_Loop]] — Full 5-step retry cycle; `@field_validator` as intentional retry triggers; `InstructorRetryException`; retry budget (max 3); interaction with fallback escalation
- [[13_Location_Resolution]] — `_CITY_COORDINATES` lookup table; `resolve_location()` function; hybrid resolution strategy (LLM + deterministic); hallucination handling; passthrough for unknown cities
- [[22_Accuracy_Target_Fallback_Policy]] — ≥95% accuracy target; GPT-4o → Claude Sonnet 4.6 fallback chain; failure logging to Kafka + LangSmith; failure rate monitoring

---

## 6. Prompting and Training

How the LLM is instructed to produce correct extractions:

- [[18_Few_Shot_Prompting_Strategy]] — 50+ curated procurement examples; Stage 1 domain context prompting; Stage 2 Beckn-specific rule prompting; why few-shot over fine-tuning; maintenance on accuracy drift
- [[23_Beckn_Protocol_Structured_Fields_Context]] — Why `location_coordinates`, `delivery_timeline`, and `budget_constraints` must be typed exactly as specified; `BecknIntent` as anti-corruption layer; Beckn endpoint overview

---

## 7. Fields and Edge Cases

What is extracted and how unusual inputs are handled:

- [[19_Fields_Extracted]] — Complete field list: item, descriptions, quantity, location, timeline, budget, urgency flag, government compliance flags; what is NOT extracted and why
- [[20_Edge_Cases_Handled]] — Multi-location delivery (Story 3); complex technical specifications (Story 2); Government L1 constraints (Story 5); emergency urgency detection (Story 3)

---

## 8. Evaluation and Governance

How the pipeline's quality is measured and maintained:

- [[21_Evaluation_Methodology]] — Test set: 100 requests × 15 categories; success criteria; weekly GitHub Actions run; Phase 1 acceptance criterion (15+ diverse requests); failure investigation process
- [[22_Accuracy_Target_Fallback_Policy]] — The ≥95% target, its justification (error amplification downstream), and the full fallback chain

---

## 9. Batch Processing

High-throughput classification:

- [[14_Batch_Processing_ThreadPoolExecutor]] — `classify_batch()` function; `ThreadPoolExecutor(max_workers=4)`; I/O-bound concurrency model; per-query error isolation; `pd.DataFrame` output schema; production scaling (asyncio replacement)

---

## 10. Multi-Backend Support

How the same schemas work across different LLM providers:

- [[15_Multi_Backend_Support]] — Initialization table for Ollama, OpenAI, Anthropic; Anthropic adapter difference; what stays the same vs. what changes; relevance to production failover

---

## 11. Architectural Analysis

Comparative and evolutionary documents:

- [[24_Design_Patterns_Table]] — Eight design patterns: open vocabulary, two-stage pipeline, heuristic routing, schema-as-prompt, validator-as-guardrail, deterministic post-processing, batch isolation, backend portability
- [[25_Base_vs_Notebook_Comparison]] — Nine-aspect comparison: manual JSON → `instructor`; basic types → `@field_validator`; no retry → automated loop; fixed enum → open vocab; 3 fields → full `BecknIntent`
- [[26_Production_vs_Prototype_Divergences]] — Five divergence points: model provider, schema usage path, observability, batch processing, governance; what remains identical between notebook and production

---

## Document Lineage

> [!note] Sources
> This atomic note network consolidates and supersedes two monolithic documents:
> - `intent_parsing_model.md` — Model configuration, fields extracted, edge cases, evaluation methodology, accuracy target
> - `intent_parsing_classification_notebook.md` — Pipeline architecture, `instructor` integration, Pydantic schemas, heuristic routing, retry mechanism, batch processing, multi-backend support, design patterns, production divergences
>
> All technical content has been preserved with full depth. No content was summarized or omitted. The two source documents have been deleted.
>
> **Related vault sections:**
> - [[nl_intent_parser]] — Lambda 1 service implementation (handler.py, Dockerfile)
> - [[beckn_bap_client]] — Lambda 2 service; consumer of `BecknIntent`
> - [[BPP_Item_Validation/00_BPP_Validation_MOC|BPP Item Validation MOC]] — Stage 3 hybrid validation layer added after Stage 2 in Lambda 1
> - [[model_governance_monitoring]] — Production model registry, drift detection, override events
> - [[microservices_architecture]] — Full Step Functions state machine; Lambda 1–5 map
