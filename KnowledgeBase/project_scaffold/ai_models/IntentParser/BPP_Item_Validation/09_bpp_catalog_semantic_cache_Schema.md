---
tags: [bpp-validation, pgvector, postgresql, semantic-cache, architecture]
cssclasses: [procurement-doc, ai-doc]
status: "#approved"
related: ["[[10_HNSW_Index_Strategy]]", "[[11_Embedding_Input_Strategy]]", "[[25_CatalogCacheWriter]]", "[[26_MCPResultAdapter]]", "[[30_Cache_Convergence_and_Invalidation]]"]
---

# PostgreSQL pgvector — `bpp_catalog_semantic_cache` Schema

## Extension and Table Declaration

```
EXTENSION: vector  (pgvector)
TABLE:     bpp_catalog_semantic_cache
```

## Full Column Definitions

| Column | Type | Constraint | Notes |
|---|---|---|---|
| `id` | `UUID` | PK, default `gen_random_uuid()` | Stable row identifier |
| `item_name` | `TEXT` | NOT NULL | Canonical BPP item name (seller's label) |
| `item_embedding` | `vector(1536)` | NOT NULL | Cosine-comparable dense vector |
| `descriptions` | `TEXT[]` | nullable | Atomic spec tokens; NULL for Path A rows |
| `bpp_id` | `TEXT` | NOT NULL | Source BPP identifier |
| `bpp_uri` | `TEXT` | NOT NULL | BPP endpoint URI for discover routing |
| `provider_id` | `TEXT` | nullable | Provider sub-ID within the BPP |
| `category_tag` | `TEXT` | nullable | Product category; enables pre-filter before ANN search |
| `source` | `TEXT` | NOT NULL | `"bpp_publish"` or `"mcp_feedback"` |
| `embedding_strategy` | `TEXT` | NOT NULL | `"item_name_only"` or `"item_name_and_specs"` |
| `created_at` | `TIMESTAMPTZ` | NOT NULL, default `NOW()` | Initial population timestamp |
| `last_seen_at` | `TIMESTAMPTZ` | NOT NULL, default `NOW()` | Updated on every hit or write |
| `hit_count` | `INTEGER` | NOT NULL, default `0` | Cumulative hit counter for LFU eviction analysis |

## Unique Constraint

```
UNIQUE (item_name, bpp_id)
```

One row per item per BPP. This constraint is the basis for the `ON CONFLICT DO UPDATE` upsert logic in both [[25_CatalogCacheWriter]] and [[26_MCPResultAdapter]].

## Key Column Semantics

### `embedding_strategy` Values

- `"item_name_only"` — Path A rows written by [[25_CatalogCacheWriter]]; weaker embedding; `descriptions` is NULL
- `"item_name_and_specs"` — Path B rows written by [[26_MCPResultAdapter]]; richer embedding; bridges BPP canonical name with buyer vocabulary

### `source` Values

- `"bpp_publish"` — Row originated from a BPP `on_discover` callback or BPP registration event (Path A)
- `"mcp_feedback"` — Row originated from a successful MCP probe that confirmed item existence (Path B)

These two columns make origin and fidelity explicit and queryable. At the AMBIGUOUS boundary, Path B rows (`item_name_and_specs`) are preferred over Path A rows at similar similarity scores. See [[27_One_Table_Rationale]].

---

## Related Notes

- [[10_HNSW_Index_Strategy]] — Index configuration for the `item_embedding` column
- [[11_Embedding_Input_Strategy]] — How `item_embedding` is computed for each path
- [[25_CatalogCacheWriter]] — Path A writer: populates rows with `source='bpp_publish'`
- [[26_MCPResultAdapter]] — Path B writer: populates rows with `source='mcp_feedback'`
- [[30_Cache_Convergence_and_Invalidation]] — Invalidation rules using `last_seen_at` and `hit_count`
