---
tags: [bpp-validation, feedback-loop, catalog-normalizer, postgresql, embedding]
cssclasses: [procurement-doc, ai-doc]
status: "#approved"
related: ["[[23_CatalogNormalizer_SRP_Boundary]]", "[[09_bpp_catalog_semantic_cache_Schema]]", "[[11_Embedding_Input_Strategy]]", "[[27_One_Table_Rationale]]"]
---

# `CatalogCacheWriter` — Path A Writer

## Location

```
services/beckn-bap-client/src/cache/catalog_cache_writer.py
```

## Trigger

After `CatalogNormalizer.normalize()` produces `DiscoverOffering[]`.

## Full Data Flow

```
BPP fires on_discover callback (or BPP catalog registration event)
      │
      ▼
CatalogNormalizer.normalize({"message":{"catalog":{...}}}, bpp_id, bpp_uri)
      │
      ▼  list[DiscoverOffering]  ← CatalogNormalizer contract UNCHANGED
      │
      ▼  (new, separate step — CatalogNormalizer does NOT call this)
CatalogCacheWriter.write_batch(offerings: list[DiscoverOffering])
      │
      ├─ For each offering:
      │    embed_input     = offering.item_name         ← item_name only
      │    item_embedding  = embed(embed_input)
      │    INSERT INTO bpp_catalog_semantic_cache (
      │      item_name, item_embedding, descriptions=NULL,
      │      bpp_id, bpp_uri, provider_id,
      │      source='bpp_publish',
      │      embedding_strategy='item_name_only',
      │      created_at=NOW(), last_seen_at=NOW()
      │    ) ON CONFLICT (item_name, bpp_id) DO UPDATE
      │        SET last_seen_at = NOW()
      │
      ▼  (async, non-blocking — does not delay the discover response)
```

## Why `descriptions = NULL` for Path A

`CatalogNormalizer.SchemaMapper` produces `item_name` as a canonical string but does not extract spec tokens — this is not within its responsibility. Attempting to reverse-engineer spec tokens from `item_name` inside `CatalogCacheWriter` would be speculative. Path A rows carry `NULL` descriptions; their embedding is honest but weaker.

A Phase 2 enhancement (captured in [[39_Sprint_Open_Questions]] question 7) could extract spec tokens from raw BPP catalog `tags[]` or `descriptor.short_desc` fields *before* normalization, upgrading Path A rows to `item_name_and_specs` quality without requiring an MCP confirmation.

## SRP Boundary Preserved

`CatalogNormalizer` normalizes format variants → `CatalogCacheWriter` persists normalized offerings. Two distinct responsibilities, two separate classes, **zero modification to `CatalogNormalizer`**.

---

## Related Notes

- [[23_CatalogNormalizer_SRP_Boundary]] — Why CatalogNormalizer cannot be extended for this role
- [[09_bpp_catalog_semantic_cache_Schema]] — The table this writer populates
- [[11_Embedding_Input_Strategy]] — Path A embedding strategy (item_name_only)
- [[27_One_Table_Rationale]] — Path A rows and their upgrade path to Path B quality
