---
name: intent-parser-pipeline
description: Three-stage IntentParser pipeline (LLM classify → BecknIntent extract → hybrid pgvector+MCP validation) with recovery flow. Auto-invoke when editing anything in IntentParser/, IntentParser/tests/, services/intention-parser/, or when adding/changing the validation thresholds, MCP fallback, or recovery logic.
tools: Read, Grep, Glob, Edit, Bash
---

# IntentParser pipeline rules

Canonical doc: `IntentParser/README.md`. Async entry point: `IntentParser.orchestrator.parse_procurement_request`. Sync wrapper for legacy/tests: `IntentParser.core.parse_request` (Stage 1+2 only — `enable_stage3=False`).

## Stage 1 — Intent classification

- Single LLM call via `instructor`-patched `AsyncOpenAI` (mode=JSON), `IntentParser/llm_clients.py`.
- Always uses `COMPLEX_MODEL` (`qwen3:8b` by default).
- Procurement gate: `PROCUREMENT_INTENTS = {"SearchProduct", "RequestQuote", "PurchaseOrder"}` in `config.py`. Anything else → early return without `beckn_intent`.

## Stage 2 — BecknIntent extraction

- Routes by **complexity heuristic** in `orchestrator._is_complex`:
  - `len(query) > 120` chars
  - OR `≥ 2` numeric tokens
  - OR contains a procurement keyword (`delivery`, `budget`, `INR`, `per meter`, etc.)
  - → `COMPLEX_MODEL` (qwen3:8b); else `SIMPLE_MODEL` (qwen3:1.7b).
- On simple-model failure, retries with complex model. Both routes return `(BecknIntent, model_used)`.
- Output is **canonical** (anti-corruption layer):
  - `delivery_timeline` is **int hours** (72 = 3 days), never ISO 8601.
  - `location_coordinates` is `"lat,lon"` decimal string. Known cities mapped in `_BECKN_PROMPT` (Bangalore=12.9716,77.5946 etc.).
  - `descriptions` is a list of atomic specs (`["80gsm", "A4", "Cat6"]`).
  - `budget_constraints` is `{max, min}` typed; min defaults to 0.0 when only an upper bound is given.

## Stage 3 — Hybrid validation (`IntentParser/validation.py`)

```
embed (all-MiniLM-L6-v2, 384-dim, ThreadPoolExecutor)
   → query_semantic_cache (HNSW ANN on bpp_catalog_semantic_cache, ef_search=100)
   → apply_three_zone_threshold:
       sim ≥ 0.85  VALIDATED   (P1 cache hit)
       0.45 ≤ sim < 0.85  AMBIGUOUS (P1 low confidence)
       sim < 0.45  CACHE_MISS → MCP probe
                     → MCP_VALIDATED  (P2, async Path B cache write)
                     → not_found      (P3, recovery)
```

**Threshold knobs** in `config.py`: `VALIDATED_THRESHOLD=0.85`, `AMBIGUOUS_THRESHOLD=0.45`. They are calibrated specifically for `all-MiniLM-L6-v2` cosine similarity. If you change the embedding model, recalibrate them.

**Path B writes** (`MCPResultAdapter.write_path_b_row`) run as `asyncio.create_task` — fire-and-forget. Tests must wait for them; see `async-test-patterns` skill.

## Recovery flow (`IntentParser/recovery.py`)

Triggered only when `validation_result.not_found` is True:

1. `broaden_procurement_query(beckn_intent)` — regex strip first, then optional Claude fallback (only if `ANTHROPIC_API_KEY` is set; `CLAUDE_FALLBACK_ENABLED` flag in config).
2. Retry Stage 3 with the broadened intent. On hit, set `validation_result.broadened_item_name`.
3. If still not found: `asyncio.gather(log_unmet_demand, notify_buyer_no_stock, trigger_open_rfq_flow, return_exceptions=True)`. **Always use `return_exceptions=True`** so a failing notifier doesn't take the others down.

## API endpoints (`IntentParser/api.py`)

| Endpoint | What runs | Sync? | Infrastructure |
|---|---|---|---|
| `POST /parse` | Stage 1+2 only | sync (thread-pooled asyncio.run) | Ollama |
| `POST /parse/batch` | Stage 1+2 batch | sync | Ollama |
| `POST /parse/full` | Stage 1+2+3 + recovery | async | Ollama + Postgres + MCP |

`/parse/full` is the production endpoint. The asyncpg pool initialises in the `_lifespan` context. With `httpx.ASGITransport` (used by tests), lifespan does NOT fire — `get_pool()` initialises lazily on first DB access.

## Module map

```
IntentParser/
├── config.py            All env-driven knobs (thresholds, models, DB)
├── models.py            ParsedIntent, ValidationResult, ParseResponse, CacheMatch, ValidationZone
├── db.py                asyncpg pool — init/acquire/close, ef_search=100 set in pool init callback
├── embeddings.py        all-MiniLM-L6-v2 singleton; embed() runs in ThreadPoolExecutor
├── llm_clients.py       instructor-patched AsyncOpenAI (mode=JSON and mode=TOOLS)
├── mcp_client.py        Lightweight MCP SSE client for search_bpp_catalog
├── validation.py        Stage 3 + MCPResultAdapter (Path B writer)
├── recovery.py          broaden + notify + RFQ stubs
├── orchestrator.py      Async pipeline (parse_procurement_request)
├── core.py              Sync wrapper (parse_request, parse_batch)
├── schemas.py           ParseResult re-export — backward-compatible public schema
└── api.py               FastAPI app — three endpoints
```

`BecknIntent`, `BudgetConstraints`, `DiscoverOffering` are defined in `shared/models.py` (single source of truth) and re-exported by `IntentParser.models`. **Do not duplicate them.**

## Common edits — guardrails

- New env knob → declare it in `IntentParser/config.py` with a default; never `os.getenv()` inline elsewhere.
- New endpoint → add to `IntentParser/api.py`, wire to `orchestrator`. Don't put HTTP logic in `orchestrator.py`.
- New stage → add a `run_stageN_*` function in its own module; orchestrator only chains them.
