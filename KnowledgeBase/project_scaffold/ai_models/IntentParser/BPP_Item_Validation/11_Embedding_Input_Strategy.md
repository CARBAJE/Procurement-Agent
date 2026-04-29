---
tags: [bpp-validation, embedding, semantic-cache, pgvector, postgresql]
cssclasses: [procurement-doc, ai-doc]
status: "#approved"
related: ["[[09_bpp_catalog_semantic_cache_Schema]]", "[[25_CatalogCacheWriter]]", "[[26_MCPResultAdapter]]", "[[15_Three_Zone_Decision_Space]]"]
---

# Embedding Input Strategy

## What Gets Vectorized

The `item_embedding` vector stored in [[09_bpp_catalog_semantic_cache_Schema]] is **not** a pure embedding of `item_name` alone. The input string depends on the write path.

## Path B Rows — `item_name_and_specs` (Richer)

Written by [[26_MCPResultAdapter]]. The embed input combines the BPP-canonical item name with the buyer's specification vocabulary:

```
embed_input = item_name + " | " + " ".join(descriptions)

Example:
  item_name    = "SS316 flange valve 2in"
  descriptions = ["stainless steel 316", "flanged", "2 inch"]
  embed_input  = "SS316 flange valve 2in | stainless steel 316 flanged 2 inch"
```

This bridges BPP canonical naming with buyer-vocabulary spec tokens, enabling future queries using buyer terminology to match BPP items despite zero lexical overlap.

## Path A Rows — `item_name_only` (Weaker)

Written by [[25_CatalogCacheWriter]]. The embed input is the item name alone:

```
embed_input = item_name

Example:
  item_name    = "SS316 flange valve 2in"
  embed_input  = "SS316 flange valve 2in"
```

`descriptions` is NULL for Path A rows because `CatalogNormalizer.SchemaMapper` does not extract spec tokens from item names. Attempting to reverse-engineer them would be speculative.

## Query-Time Strategy

At query time, Stage 3 **always uses the richer strategy** regardless of which path populated the cache:

```
query_embed_input = BecknIntent.item + " | " + " ".join(BecknIntent.descriptions)
```

This query vector naturally produces higher similarity scores against Path B rows (matching embedding strategy) and slightly lower but still valid scores against Path A rows.

## Tie-Breaking Rule

At the AMBIGUOUS boundary (similarity 0.75–0.91), **prefer Path B hits** (`embedding_strategy = 'item_name_and_specs'`) over Path A hits at similar similarity scores. The `embedding_strategy` column in [[09_bpp_catalog_semantic_cache_Schema]] makes this preference queryable.

---

## Related Notes

- [[09_bpp_catalog_semantic_cache_Schema]] — Schema including `embedding_strategy` and `descriptions` columns
- [[25_CatalogCacheWriter]] — Path A write path (item_name_only)
- [[26_MCPResultAdapter]] — Path B write path (item_name_and_specs)
- [[15_Three_Zone_Decision_Space]] — Where tie-breaking applies (AMBIGUOUS zone)
