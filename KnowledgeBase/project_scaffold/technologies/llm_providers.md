---
tags: [technology, ai, llm, ollama, qwen3, claude, local-inference, model-routing]
cssclasses: [procurement-doc, tech-doc]
status: "#implemented"
related: ["[[nl_intent_parser]]", "[[comparison_scoring_engine]]", "[[negotiation_engine]]", "[[embedding_models]]", "[[model_governance_monitoring]]", "[[agent_framework_langchain_langgraph]]"]
---

# LLM Providers

> [!implementation] Implementation Note (updated Phase 3)
> The original spec described a cloud-first multi-provider strategy (GPT-4o primary, Claude fallback). The implemented system uses **local Ollama inference** for all main pipeline steps, with Claude as a last-resort fallback only. No GPT-4o calls exist anywhere in the current codebase. This decision was driven by data sovereignty, zero API cost during development, and the ability to run fully offline.

## Implemented Provider Matrix

| Model | Runtime | Role | Opt-in? |
|---|---|---|---|
| `qwen3:8b` | Local Ollama | Stage 1 intent classification + Stage 2 BecknIntent extraction (complex queries) | No — default |
| `qwen3:1.7b` | Local Ollama | Stage 2 BecknIntent extraction (simple/short queries, routed by complexity) | No — default |
| `claude-sonnet-4-6` | Anthropic API | Last-resort broadening fallback in Stage 3 recovery (query broadening + RFQ trigger) | Yes — requires `ANTHROPIC_API_KEY` |
| Claude (via proxy :8012) | OpenAI-compat proxy | `SupplierAgent` in `frontend_demo_gateway` — simulates supplier responses in negotiation demo | Yes — demo only |

## Per-Component Assignment

| Component | Model | Notes |
|---|---|---|
| [[nl_intent_parser\|NL Intent Parser — Stage 1]] | `qwen3:8b` | Instructor JSON mode via Ollama |
| [[nl_intent_parser\|NL Intent Parser — Stage 2]] | `qwen3:8b` (complex) / `qwen3:1.7b` (simple) | Routed by query complexity; both via Ollama |
| [[nl_intent_parser\|Stage 3 broadening fallback]] | `claude-sonnet-4-6` | Only when pgvector + MCP sidecar return `not_found`; ANTHROPIC_API_KEY must be set |
| [[negotiation_engine\|Negotiation Engine — advisory mode]] | `qwen3:8b` | Advisory analysis of ambiguous terms |
| `SupplierAgent` (demo) | Claude via :8012 | Simulates supplier counter-offers in the frontend demo gateway |
| [[embedding_models\|Memory & Retrieval]] | `BAAI/bge-small-en-v1.5` | Embedding model — see [[embedding_models]] |

## Complexity Routing (Stage 2)

Stage 2 routes between `qwen3:8b` and `qwen3:1.7b` based on query complexity score:

- **High complexity** (multi-item, many constraints, ambiguous specs): `qwen3:8b`
- **Low complexity** (single well-structured item): `qwen3:1.7b` — faster and cheaper

The routing threshold is set in `IntentParser/config.py`.

## Configuration

```bash
# Required for any LLM calls
OLLAMA_BASE_URL=http://localhost:11434  # default

# Optional — enables Claude broadening fallback in Stage 3
ANTHROPIC_API_KEY=sk-ant-...

# Required for SupplierAgent in demo flows
# Points to a Claude-compatible OpenAI proxy
OLLAMA_BASE_URL=http://localhost:8012/v1   # frontend_demo_gateway config
OLLAMA_API_KEY=...
SUPPLIER_MODEL=claude-3-5-sonnet
```

> [!tech-stack] Why Local Ollama
> Running qwen3 locally means zero per-request API cost, zero data egress, and fully offline operation during development. The model quality for structured procurement intent extraction is sufficient — the Instructor + Pydantic v2 pipeline enforces schema correctness regardless of model tier. The Claude fallback provides a quality escape hatch for edge-case broadening without committing to a cloud-primary strategy.

## Original Design vs. Implementation

| Original spec | Implemented |
|---|---|
| `gpt-4o` as primary for all reasoning | `qwen3:8b` via local Ollama |
| `gpt-4o-mini` for lightweight tasks | `qwen3:1.7b` for simple Stage 2 queries |
| `claude-sonnet-4-6` as intent-parse fallback | `claude-sonnet-4-6` as Stage 3 broadening fallback only (opt-in) |
| LangSmith traces for all LLM calls | `reasoning_payload` in audit trail captures data; LangSmith deferred to Phase 4 |
| Weekly evaluation suite (100 scenarios) | Manual evaluation; automated eval deferred to Phase 4 |

> [!milestone] Phase 4 Path
> When the system moves to production: evaluate whether qwen3:8b accuracy on the real procurement catalog justifies staying local, or whether switching Stage 1/2 to Claude/GPT-4o provides meaningful gains. LangSmith integration (see [[model_governance_monitoring]]) should be wired first so the decision is data-driven.
