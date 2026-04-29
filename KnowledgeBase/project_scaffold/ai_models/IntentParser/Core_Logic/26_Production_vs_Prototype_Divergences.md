---
tags: [intent-parser, production, prototype, divergences, architecture, observability]
cssclasses: [procurement-doc, ai-doc]
status: "#approved"
related: ["[[16_Model_Configuration]]", "[[15_Multi_Backend_Support]]", "[[14_Batch_Processing_ThreadPoolExecutor]]", "[[10_Heuristic_Complexity_Router]]", "[[01_Two_Stage_Pipeline_Overview]]"]
---

# Production vs. Prototype — Divergences

> [!architecture] Context
> The `intent_parsing_classification_notebook.md` is the **experimental prototype** for the [[nl_intent_parser|NL Intent Parser]] component in the production system (Lambda 1, port 8001). The notebook demonstrates the transformation logic that production codifies. This note documents the five specific points where the prototype and production implementations diverge.

---

## Divergence Map

| Dimension | Notebook (Prototype) | Production |
|---|---|---|
| **Model provider** | Ollama local (`qwen3:8b`, `qwen3:1.7b`) | [[llm_providers\|GPT-4o (primary) + Claude Sonnet 4.6 (fallback)]] via enterprise API agreements |
| **Schema usage** | `BecknIntent` transformation demonstrated | `BecknIntent` feeds directly into [[beckn_bap_client\|BAP Client's `discover` query builder]] |
| **Observability** | No tracing instrumentation | Every LLM call wrapped with [[observability_stack\|LangSmith tracing]] |
| **Batch processing** | `ThreadPoolExecutor` (thread-based) | `asyncio` + `aiohttp` queues (async, compatible with [[beckn_bap_client\|async Beckn HTTP client]]) |
| **Governance** | `MODEL = "qwen3:8b"` hardcoded | Model versions and prompt templates tracked in [[model_governance_monitoring\|Model Registry]] |

---

## Divergence 1 — Model Provider

**Notebook:** `instructor.from_openai(OpenAI(base_url="http://localhost:11434/v1"))` → `qwen3:8b` and `qwen3:1.7b`

**Production:** `instructor.from_openai(OpenAI(api_key="sk-..."))` → `gpt-4o` (primary) with `instructor.from_anthropic(...)` → `claude-sonnet-4-6` (fallback after 3 retries)

The routing dimension also changes:

| Notebook | Production | Signal |
|---|---|---|
| Simple → `qwen3:1.7b` | Simple → `gpt-4o-mini` | `is_complex_request() == False` |
| Complex → `qwen3:8b` | Complex → `gpt-4o` | `is_complex_request() == True` |
| *(no model fallback)* | Fallback → `claude-sonnet-4-6` | All retries on `gpt-4o` exhausted |

The [[10_Heuristic_Complexity_Router|`is_complex_request()` heuristic]] is **identical** in both environments — only the model names change. The [[15_Multi_Backend_Support|`instructor` adapter swap]] demonstrated in the notebook is the same mechanism used for production failover.

---

## Divergence 2 — Schema Usage Path

**Notebook:** `BecknIntent` is produced and printed/returned as a demonstration of the transformation logic.

**Production:** `BecknIntent` produced by [[03_Stage2_BecknIntentParser|Stage 2]] is passed directly to the [[beckn_bap_client|BAP Client's `discover` query builder]]:

```python
# Production Lambda 1 → Lambda 2 flow (via Orchestrator):
beckn_intent = BecknIntentParser.parse(query)           # Lambda 1 output
discover_response = await bap_client.discover(beckn_intent)  # Lambda 2 input
```

The `BecknIntent` schema in production is defined in `shared/models.py` — the **single source of truth** imported by all Lambda services. The notebook's `BecknIntent` class is the prototype of this shared definition.

---

## Divergence 3 — Observability

**Notebook:** No tracing. LLM call results are printed to stdout.

**Production:** Every LLM call is a child span in the [[observability_stack|LangSmith]] trace for `POST /parse`:

```
LangSmith trace: POST /parse
├── Span: intent_classification (Stage 1)
│   ├── input: {query: "..."}
│   ├── output: {intent: "SearchProduct", confidence: 0.97}
│   └── latency_ms: 450
└── Span: beckn_intent_extraction (Stage 2)
    ├── input: {query: "...", model: "gpt-4o"}
    ├── output: {item: "SS flanged valve", ...}
    ├── retry_count: 0
    └── latency_ms: 890
```

LangSmith traces feed the [[model_governance_monitoring|Model Governance]] dashboard — retry rate trends, latency distributions, and model drift detection.

---

## Divergence 4 — Batch Processing

**Notebook:** `ThreadPoolExecutor(max_workers=4)` — thread-based concurrent I/O.

**Production:** `asyncio` + `aiohttp` — async event loop, compatible with the [[beckn_bap_client|async Beckn HTTP client]] (`aiohttp.ClientSession` for all BAP calls).

**Why the switch:** The entire production microservice (Lambda 1) runs on `aiohttp` (an async HTTP framework). Mixing `ThreadPoolExecutor` with an `asyncio` event loop requires explicit `loop.run_in_executor()` wrapping — adding boilerplate and a thread pool management concern. Native `asyncio` LLM calls via async-compatible `instructor` adapters are simpler and more consistent with the rest of the service.

---

## Divergence 5 — Model Governance

**Notebook:** `MODEL = "qwen3:8b"` — model name is a hardcoded string constant in the notebook file.

**Production:** Model names, prompt templates, and `max_retries` are tracked in the [[model_governance_monitoring|Model Registry]]:
- Model versions are pinned (e.g., `"gpt-4o-2024-11-20"`) — not the floating `"gpt-4o"` alias
- Prompt template changes require a registry version bump
- Model swaps require approval in the governance workflow
- All changes are auditable and reversible

**Why this matters:** If `gpt-4o` updates its behavior silently (a common occurrence with floating model aliases), the pinned version ensures production behavior is stable until a deliberate upgrade is approved.

---

## What Is the Same

The following are **identical** between notebook and production:
- [[05_ParsedIntent_Schema|`ParsedIntent`]] Pydantic schema
- [[06_BecknIntent_Schema|`BecknIntent`]] Pydantic schema
- [[07_BudgetConstraints_Schema|`BudgetConstraints`]] Pydantic schema
- All `@field_validator` logic
- [[10_Heuristic_Complexity_Router|`is_complex_request()` heuristic function]]
- [[11_Routing_Keyword_Signal_Sets|`_DELIVERY_KEYWORDS` and `_BUDGET_KEYWORDS` sets]]
- [[13_Location_Resolution|`_CITY_COORDINATES` lookup table and `resolve_location()` function]]
- [[12_Retry_Mechanism_Validation_Feedback_Loop|Retry logic (`max_retries=3`)]]
- [[08_Instructor_Library_Integration|`instructor` usage pattern]]

---

## Related Notes
- [[16_Model_Configuration]] — Production model choices and routing
- [[15_Multi_Backend_Support]] — The `instructor` adapter swap mechanism
- [[10_Heuristic_Complexity_Router]] — The routing heuristic preserved across both environments
- [[14_Batch_Processing_ThreadPoolExecutor]] — The notebook batch implementation (replaced in production by asyncio)
