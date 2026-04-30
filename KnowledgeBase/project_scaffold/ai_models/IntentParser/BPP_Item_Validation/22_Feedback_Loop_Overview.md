---
tags: [bpp-validation, feedback-loop, catalog-normalizer, architecture, postgresql]
cssclasses: [procurement-doc, ai-doc]
status: "#approved"
related: ["[[23_CatalogNormalizer_SRP_Boundary]]", "[[24_Two_Writers_One_Table_Pattern]]", "[[25_CatalogCacheWriter]]", "[[26_MCPResultAdapter]]", "[[27_One_Table_Rationale]]"]
---

# Feedback Loop — Overview

> [!warning] Critical Architectural Decision — CatalogNormalizer Boundary
> A naive implementation would route MCP probe results back through the `CatalogNormalizer` for cache population. This was evaluated and **rejected** on three independent grounds. The corrected design introduces two dedicated writer components that respect all existing component boundaries.

## The Solution

The solution preserves `CatalogNormalizer` unchanged and introduces two new, thin components. The `bpp_catalog_semantic_cache` table remains a single unified store because both paths answer the same semantic question: *"Has the BPP network confirmed that item X exists?"*

## Why One Table

Both paths answer the same semantic question — "Has the BPP network confirmed that item X exists?" — regardless of whether confirmation came proactively from a BPP registration event (Path A) or reactively from a user query triggering an MCP probe (Path B).

## TWO WRITERS — ONE TABLE (Full Diagram)

```
╔══════════════════════════════════════════════════════════════════════════╗
║                    TWO WRITERS — ONE TABLE                               ║
║                                                                          ║
║  PATH A: BPP Catalog                       PATH B: MCP Feedback          ║
║  (Proactive, BPP-driven)                   (Reactive, query-driven)      ║
║  ─────────────────────────────             ─────────────────────────────║
║  Trigger: on_discover callback             Trigger: MCP probe returns    ║
║           or BPP publish event                       found: true         ║
║                                                                          ║
║  Source data:                              Source data:                  ║
║    DiscoverOffering[]                        DiscoverOffering[]          ║
║    (from CatalogNormalizer)                  (already normalized)        ║
║                                            + BecknIntent (Stage 2)       ║
║                                                                          ║
║  Component: CatalogCacheWriter             Component: MCPResultAdapter   ║
║  Location:                                 Location:                     ║
║    beckn-bap-client/src/cache/               intention-parser/           ║
║                                              src/validation/             ║
║                                                                          ║
║  embed( item_name )                        embed( item_name              ║
║  ← item_name only                               + " | "                  ║
║  ← descriptions NOT available                   + join(descriptions) )   ║
║    from DiscoverOffering                   ← BPP canonical name bridged  ║
║                                              with buyer spec vocabulary   ║
║                                                                          ║
║  source = "bpp_publish"                    source = "mcp_feedback"       ║
║  embedding_strategy = "item_name_only"     embedding_strategy =          ║
║                                              "item_name_and_specs"       ║
║                    │                                      │              ║
║                    ▼                                      ▼              ║
║  ┌─────────────────────────────────────────────────────────────────────┐ ║
║  │   bpp_catalog_semantic_cache  (PostgreSQL 16 + pgvector)            │ ║
║  │   source + embedding_strategy columns distinguish origin and        │ ║
║  │   embedding fidelity — same semantic question, different fidelity   │ ║
║  └─────────────────────────────────────────────────────────────────────┘ ║
╚══════════════════════════════════════════════════════════════════════════╝
```

---

## Related Notes

- [[23_CatalogNormalizer_SRP_Boundary]] — Three independent grounds for rejecting CatalogNormalizer reuse
- [[24_Two_Writers_One_Table_Pattern]] — Path A vs Path B side-by-side comparison
- [[25_CatalogCacheWriter]] — Path A writer implementation
- [[26_MCPResultAdapter]] — Path B writer implementation
- [[27_One_Table_Rationale]] — Why one table is correct and not "polluted"
