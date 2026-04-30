---
tags: [bpp-validation, pgvector, postgresql, hnsw, semantic-cache]
cssclasses: [procurement-doc, ai-doc]
status: "#approved"
related: ["[[09_bpp_catalog_semantic_cache_Schema]]", "[[39_Sprint_Open_Questions]]"]
---

# HNSW Index Strategy

## Full Index Specification

```
INDEX TYPE:       HNSW (Hierarchical Navigable Small World)
OPERATOR CLASS:   vector_cosine_ops
BUILD PARAMETERS: m=16, ef_construction=64
QUERY PARAMETER:  ef_search=100  (set per-session; prioritises recall over speed)
```

## Why HNSW Over IVFFlat

HNSW is chosen over IVFFlat for two reasons:

- **IVFFlat requires a fitting step** (cluster count selection) that must be re-run as the corpus grows; HNSW inserts are incremental. As the feedback loop continuously adds new rows via [[25_CatalogCacheWriter]] and [[26_MCPResultAdapter]], IVFFlat's cluster structure would degrade without periodic re-fitting. HNSW handles this incrementally with no maintenance window.

- **For catalog sizes of hundreds to tens of thousands of items**, HNSW recall at `ef_search=100` adds < 2ms — acceptable overhead. The `bpp_catalog_semantic_cache` is a bounded corpus, and HNSW's performance characteristics are well-suited to this scale.

## Parameter Rationale

- `m=16`: Number of bi-directional links created for each node. Balances graph connectivity vs. memory footprint for catalog-scale corpora.
- `ef_construction=64`: Size of the dynamic candidate list during index construction. Higher values improve recall quality at insert time.
- `ef_search=100`: Size of the dynamic candidate list during query. Set per-session; prioritizes recall over raw speed, acceptable given the ~10–20ms budget for the primary path.

## Open Questions

The optimal `ef_search` value relative to the actual pgvector version installed and initial catalog sizes (100–10,000 entries) is captured in [[39_Sprint_Open_Questions]] question 1.

---

## Related Notes

- [[09_bpp_catalog_semantic_cache_Schema]] — The table this index applies to
- [[39_Sprint_Open_Questions]] — Question 1: pgvector version and ef_search tuning
