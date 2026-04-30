---
tags: [bpp-validation, feedback-loop, postgresql, semantic-cache, architecture]
cssclasses: [procurement-doc, ai-doc]
status: "#approved"
related: ["[[24_Two_Writers_One_Table_Pattern]]", "[[09_bpp_catalog_semantic_cache_Schema]]", "[[30_Cache_Convergence_and_Invalidation]]"]
---

# Why One Table Is Correct

## Resolving the "Polluted Table" Concern

The concern about "polluting one table with incompatible data" is resolved by recognizing that **the semantic question both paths answer is identical**: "Has the BPP network confirmed that item X exists?" The answer is either present or absent regardless of how confirmation was obtained.

## Origin and Fidelity Made Explicit

The `source` and `embedding_strategy` columns in [[09_bpp_catalog_semantic_cache_Schema]] make origin and fidelity **explicit and queryable**:

- `source = "bpp_publish"` + `embedding_strategy = "item_name_only"` → Path A row (weaker embedding, proactive)
- `source = "mcp_feedback"` + `embedding_strategy = "item_name_and_specs"` → Path B row (richer embedding, reactive)

Both row types are valid answers to the semantic question. The column values distinguish fidelity without requiring a separate table.

## Tie-Breaking Rule

At the AMBIGUOUS boundary (similarity 0.75–0.91), **prefer Path B rows** (`embedding_strategy = 'item_name_and_specs'`) over Path A rows at similar similarity scores. Path B rows have better embedding alignment with buyer-vocabulary queries.

## Path A → Path B Upgrade Path

A Path A row can be **upgraded** to Path B quality when a subsequent MCP probe confirms the same `(item_name, bpp_id)` pair. The `ON CONFLICT DO UPDATE` clause in [[26_MCPResultAdapter]] refreshes:

- `descriptions` → populated with buyer spec vocabulary
- `embedding_strategy` → upgraded from `"item_name_only"` to `"item_name_and_specs"`
- `last_seen_at` → refreshed
- `hit_count` → incremented

This upgrade mechanism means the cache continuously improves in embedding quality as usage accumulates, without requiring a separate migration step.

---

## Related Notes

- [[24_Two_Writers_One_Table_Pattern]] — Side-by-side comparison of both paths
- [[09_bpp_catalog_semantic_cache_Schema]] — Schema with `source` and `embedding_strategy` columns
- [[30_Cache_Convergence_and_Invalidation]] — How the upgrade path fits into convergence
