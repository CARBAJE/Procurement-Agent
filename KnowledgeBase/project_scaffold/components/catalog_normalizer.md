---
tags: [component, normalizer, catalog, beckn, microservice, lambda-2]
cssclasses: [procurement-doc, component-doc]
status: "#implemented"
related: ["[[beckn_bap_client]]", "[[microservices_architecture]]", "[[comparison_scoring_engine]]", "[[phase2_core_intelligence_transaction_flow]]"]
---

# Component: Catalog Normalizer

> [!architecture] Role in the System
> The Catalog Normalizer is the **Normalizer Agent** described in `architecture/Architecture.md`. It lives embedded inside `services/beckn-bap-client/` (Lambda 2) — not as a separate service. It normalizes raw Beckn catalog responses into uniform `DiscoverOffering` objects consumed by the scoring engine.

## Location

```
services/beckn-bap-client/src/normalizer/
├── __init__.py          exports CatalogNormalizer
├── normalizer.py        CatalogNormalizer — public facade
├── detector.py          FormatDetector — identifies catalog schema variant
├── formats.py           FormatVariant enum (FLAT_RESOURCES, NESTED_PROVIDERS, UNKNOWN)
├── schema_mapper.py     SchemaMapper — deterministic field mapping for known formats
└── llm_fallback.py      LLMFallbackNormalizer — heuristic/LLM for unknown formats
```

## Normalization Pipeline

```
Raw catalog dict (from ONIX on_discover callback)
      │
      ▼
FormatDetector.detect()
      │  FormatVariant
      ▼
  FLAT_RESOURCES / NESTED_PROVIDERS ──→ SchemaMapper.map_to_offerings()
  UNKNOWN ─────────────────────────────→ LLMFallbackNormalizer.normalize()
      │
      ▼
list[DiscoverOffering]
```

## Supported Formats

| FormatVariant | Description | Source |
|---------------|-------------|--------|
| `FLAT_RESOURCES` | `message.catalogs[].resources[]` | Real Beckn v2 Catalog Service |
| `NESTED_PROVIDERS` | `message.catalog.providers[].items[]` | Mock / legacy network |
| `UNKNOWN` | Any other schema | LLM fallback |

## Integration

`handler.py` does NOT call `CatalogNormalizer` directly — the `BecknClient._parse_on_discover()` method handles format parsing at the wire level. `CatalogNormalizer` is available for the Phase 2 extension where multi-format normalization via LLM is needed.

## Testing

```bash
cd services/beckn-bap-client
pytest tests/
```

## Phase 2 Extension

Replace `LLMFallbackNormalizer.normalize()` body with an LLM ReAct call (using `NORMALIZER_MODEL` env var) to handle exotic BPP catalog formats. No interface changes needed — same `CatalogNormalizer.normalize(catalog, bpp_id, bpp_uri) → list[DiscoverOffering]` signature.
