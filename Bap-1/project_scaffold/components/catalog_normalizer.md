---
tags: [component, normalizer, catalog, beckn, schema-mapping, llm-fallback, format-detection]
cssclasses: [procurement-doc, component-doc]
status: "#implemented"
related: ["[[beckn_bap_client]]", "[[comparison_scoring_engine]]", "[[agent_framework_langchain_langgraph]]", "[[phase2_core_intelligence_transaction_flow]]"]
---

# Component: Catalog Normalizer

> [!architecture] Role in the System
> The Catalog Normalizer transforms **heterogeneous BPP catalog payloads** from `on_discover` callbacks into a unified `DiscoverOffering` schema consumable by the [[comparison_scoring_engine|Comparison Engine]]. It replaces the `_parse_on_discover()` method previously embedded in `BecknClient`, which only handled 2 of 5+ possible BPP response formats.

## Architecture: 3-Step Pipeline

```
Payload raw on_discover (dict)
        │
        ▼
Step 1 — FormatDetector.detect(catalog) → FormatVariant (1–5)
        │
        ├── Variant 1–4 → SchemaMapper.map(catalog, variant, bpp_id, bpp_uri)
        │      (deterministic, covers 80%+ of cases, no LLM needed)
        │
        └── Variant 5 (UNKNOWN) → LLMFallbackNormalizer.normalize(catalog, bpp_id, bpp_uri)
               instructor + Ollama qwen3:1.7b — same pattern as IntentParser/core.py
        │
        ▼
Step 2 — Pydantic v2 validation (applied automatically by DiscoverOffering)
        │
        ▼
list[DiscoverOffering] → returned to client.py → DiscoverResponse
```

## Supported Format Variants

| Variant | Enum Value | Description | Detection Predicate | Mapping Method |
|---|---|---|---|---|
| `BECKN_V2_FLAT_RESOURCES` | 1 | `resources[]` in catalog root (real Beckn v2 Catalog Service) | `isinstance(c.get("resources"), list) and len > 0` | `_map_v2_flat_resources` |
| `ONDC_CATALOG` | 4 | Has `fulfillments[]` + `tags[]` (ONDC-specific fields) | `"fulfillments" in c and "tags" in c` | `_map_ondc` |
| `LEGACY_PROVIDERS_ITEMS` | 2 | `providers[].items[]` (mock_onix / legacy format) | `isinstance(c.get("providers"), list) and any("items" in p ...)` | `_map_legacy_providers` |
| `BPP_CATALOG_V1` | 3 | `items[]` with `provider` as string ID | `isinstance(c.get("items"), list) and isinstance(items[0]["provider"], str)` | `_map_bpp_v1` |
| `UNKNOWN` | 5 | No fingerprint matched | — (fallback) | LLM Fallback |

> [!note] Detection Order
> ONDC_CATALOG (variant 4) is checked **before** LEGACY_PROVIDERS_ITEMS (variant 2) because ONDC catalogs also contain `providers[].items[]`. The more specific fingerprint must match first.

## Format Detection Strategy

`FormatDetector.detect()` iterates `FINGERPRINT_RULES` — an ordered list of `(FormatVariant, predicate)` pairs — and returns the **first match**. This makes detection O(n) where n is the number of known formats (currently 4), with zero IO and zero LLM calls.

```python
FINGERPRINT_RULES = [
    (FormatVariant.BECKN_V2_FLAT_RESOURCES, _has_resources),
    (FormatVariant.ONDC_CATALOG, _has_fulfillments_and_tags),   # ← before legacy
    (FormatVariant.LEGACY_PROVIDERS_ITEMS, _has_providers_items),
    (FormatVariant.BPP_CATALOG_V1, _has_items_with_string_provider),
]
```

**Why "first match wins":** It is O(1) amortized for the common cases (Formats A and B represent 80%+ of real traffic), requires no scoring or confidence weighting, and makes the detection deterministic and trivially testable.

## LLM Fallback

Activated only when `FormatVariant.UNKNOWN` is returned (no fingerprint matched).

- **Model:** `NORMALIZER_MODEL` env var, default `qwen3:1.7b`
- **Client:** `instructor.from_openai(OpenAI(base_url=OLLAMA_URL, api_key="ollama"), mode=instructor.Mode.JSON)`
- **Pattern:** Identical to `IntentParser/core.py` — same `instructor` + Ollama setup for consistency across the project.
- **Schema:** `NormalizedCatalog(offerings: list[RawOffering])` where `RawOffering` has all `DiscoverOffering` fields as optional with safe defaults.
- **Retry:** `max_retries=3`
- **Error handling:** Any exception → logs warning, returns `[]`. **Never propagates exceptions.** The LangGraph graph handles `offerings=[]` gracefully (routes directly to `present_results`).

## Integration with the System

### How it replaces `_parse_on_discover()`

`client.py` previously embedded the parsing logic inside `BecknClient`. After Phase 2:

1. `_parse_on_discover()` is **removed** from `BecknClient`.
2. A module-level singleton `_normalizer = CatalogNormalizer()` is created in `client.py`.
3. `_build_discover_response()` calls `_normalizer.normalize({"message": {"catalog": catalog}}, bpp_id, bpp_uri)` for each catalog in the callback.

### LangGraph graph — unchanged

`CatalogNormalizer` is transparent to the LangGraph nodes. The `discover_node` still receives a `DiscoverResponse` with `offerings: list[DiscoverOffering]`. No changes to `graph.py`, `nodes.py`, or `state.py`.

### Module structure

```
src/normalizer/
├── __init__.py         # exports CatalogNormalizer only
├── formats.py          # FormatVariant enum + FINGERPRINT_RULES
├── detector.py         # FormatDetector — pure function, no IO
├── schema_mapper.py    # SchemaMapper — deterministic mappers for variants 1–4
├── llm_fallback.py     # LLMFallbackNormalizer — instructor + Ollama
└── normalizer.py       # CatalogNormalizer — public facade
```

## Acceptance Criteria — Phase 2

- [x] Handles 5+ BPP catalog formats (4 deterministic + 1 LLM fallback for unknowns)
- [x] Format A (`resources[]`) and Format B (`providers[].items[]`) behavior is **identical** to the previous `_parse_on_discover()` — moved verbatim, no regressions
- [x] 17 unit tests in `tests/test_normalizer.py` — all pass without Ollama running
- [x] Existing tests (`test_discover.py`, `test_agent.py`) continue passing without changes
- [x] LLM fallback returns `[]` on error — never raises
- [x] `BecknClient` is a thin HTTP layer — no format-detection logic remains inside it

## References

- [[beckn_bap_client]] — the HTTP client that delegates to this normalizer
- [[comparison_scoring_engine]] — consumes `list[DiscoverOffering]` produced here
- [[agent_framework_langchain_langgraph]] — LangGraph graph unchanged by this component
- [[phase2_core_intelligence_transaction_flow]] — milestone that delivered this component
