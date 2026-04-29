---
tags: [bpp-validation, feedback-loop, mcp, postgresql, embedding, intent-parser]
cssclasses: [procurement-doc, ai-doc]
status: "#approved"
related: ["[[23_CatalogNormalizer_SRP_Boundary]]", "[[09_bpp_catalog_semantic_cache_Schema]]", "[[11_Embedding_Input_Strategy]]", "[[27_One_Table_Rationale]]", "[[25_CatalogCacheWriter]]"]
---

# `MCPResultAdapter` — Path B Writer

## Location

```
services/intention-parser/src/validation/mcp_result_adapter.py
```

## Trigger

After the MCP tool returns `found: true`.

## Inputs Available

- `mcp_result.items` — `list[DiscoverOffering]` (already normalized inside BAP Client)
- `original_intent` — the `BecknIntent` from Stage 2 (holds `item` and `descriptions`)

`MCPResultAdapter` is the **only component that holds both halves of the richer embedding** simultaneously: BPP-canonical `item_name` from `DiscoverOffering` and buyer-vocabulary `descriptions` from `BecknIntent`.

## Full Data Flow

```
MCP returns:    {found:true, items:[DiscoverOffering...], query_used: str}
Stage 2 gave:   BecknIntent {item: str, descriptions: list[str], ...}

MCPResultAdapter.adapt(mcp_result, original_intent):
  For each DiscoverOffering in mcp_result.items:
    │
    ├─ item_name   = offering.item_name       ← BPP canonical name
    ├─ bpp_id      = offering.bpp_id
    ├─ bpp_uri     = offering.bpp_uri
    ├─ provider_id = offering.provider_id
    ├─ descriptions = original_intent.descriptions  ← buyer spec vocabulary
    │
    ├─ embed_input = item_name + " | " + " ".join(descriptions)
    │   Example:   "SS316 flange valve 2in | flanged 2 inch stainless"
    │              ← bridges BPP canonical naming with buyer's terminology
    │
    ├─ item_embedding = embed(embed_input)
    │
    └─ INSERT INTO bpp_catalog_semantic_cache (
         item_name, item_embedding, descriptions,
         bpp_id, bpp_uri, provider_id,
         source='mcp_feedback',
         embedding_strategy='item_name_and_specs',
         created_at=NOW(), last_seen_at=NOW(), hit_count=0
       ) ON CONFLICT (item_name, bpp_id) DO UPDATE
           SET last_seen_at = NOW(),
               hit_count = hit_count + 1,
               descriptions = EXCLUDED.descriptions   ← refresh buyer vocab
```

## Why This Embedding Is Richer Than Path A

A future buyer querying `"stainless flanged valve 2 inch"` produces a query vector very close to `embed("SS316 flange valve 2in | flanged 2 inch stainless")` — despite zero lexical overlap with `"SS316"`. The buyer-vocabulary `descriptions` act as a **semantic bridge**, substantially improving recall for terminology-divergent queries.

## Critical Constraint

The INSERT is **asynchronous and non-blocking**. `ParseResponse` is returned to the user immediately after the MCP tool confirms existence. Write failures are logged to the audit trail but **never propagate as errors** — the validation succeeded; only the cache optimization failed.

---

## Related Notes

- [[23_CatalogNormalizer_SRP_Boundary]] — Why CatalogNormalizer cannot be used here
- [[09_bpp_catalog_semantic_cache_Schema]] — The table this writer populates
- [[11_Embedding_Input_Strategy]] — Path B embedding strategy (item_name_and_specs)
- [[27_One_Table_Rationale]] — How Path B rows are preferred at the AMBIGUOUS boundary
- [[25_CatalogCacheWriter]] — Path A writer for comparison
