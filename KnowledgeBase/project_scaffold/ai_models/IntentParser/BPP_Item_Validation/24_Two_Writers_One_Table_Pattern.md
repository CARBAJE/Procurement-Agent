---
tags: [bpp-validation, feedback-loop, architecture, postgresql, catalog-normalizer]
cssclasses: [procurement-doc, ai-doc]
status: "#approved"
related: ["[[22_Feedback_Loop_Overview]]", "[[25_CatalogCacheWriter]]", "[[26_MCPResultAdapter]]", "[[27_One_Table_Rationale]]", "[[09_bpp_catalog_semantic_cache_Schema]]"]
---

# Two Writers, One Table Pattern

## The Two New Thin Components

The solution introduces two new, thin components that write to the same `bpp_catalog_semantic_cache` table while respecting all existing component boundaries:

1. **`CatalogCacheWriter`** — lives inside `beckn-bap-client`; writes Path A rows after `CatalogNormalizer` produces `DiscoverOffering[]`
2. **`MCPResultAdapter`** — lives inside `intention-parser`; writes Path B rows after a successful MCP probe

## Path A vs Path B Side-by-Side

| Attribute | PATH A — BPP Catalog | PATH B — MCP Feedback |
|---|---|---|
| **Nature** | Proactive, BPP-driven | Reactive, query-driven |
| **Trigger** | `on_discover` callback or BPP publish event | MCP probe returns `found: true` |
| **Source data** | `DiscoverOffering[]` from `CatalogNormalizer` | `DiscoverOffering[]` (already normalized) + `BecknIntent` (Stage 2) |
| **Component** | `CatalogCacheWriter` | `MCPResultAdapter` |
| **Location** | `beckn-bap-client/src/cache/` | `intention-parser/src/validation/` |
| **Embed strategy** | `embed(item_name)` — item_name only | `embed(item_name + " | " + join(descriptions))` |
| **`source` column value** | `"bpp_publish"` | `"mcp_feedback"` |
| **`embedding_strategy` column value** | `"item_name_only"` | `"item_name_and_specs"` |
| **`descriptions` column** | NULL (not available from DiscoverOffering) | Populated from `original_intent.descriptions` |

## Architectural Justification

One table because both paths answer the same semantic question: *"Has the BPP network confirmed that item X exists?"*

The answer is either present or absent regardless of how confirmation was obtained. Splitting into two tables would require a UNION in every validation query and add schema complexity with zero semantic benefit.

The `source` and `embedding_strategy` columns in [[09_bpp_catalog_semantic_cache_Schema]] make origin and fidelity explicit and queryable within the single unified store. See [[27_One_Table_Rationale]] for the full rationale including the upgrade path.

---

## Related Notes

- [[22_Feedback_Loop_Overview]] — Full ASCII art diagram and overview
- [[25_CatalogCacheWriter]] — Path A writer detail
- [[26_MCPResultAdapter]] — Path B writer detail
- [[27_One_Table_Rationale]] — Why one table is correct; tie-breaking; upgrade path
- [[09_bpp_catalog_semantic_cache_Schema]] — The shared schema both writers populate
