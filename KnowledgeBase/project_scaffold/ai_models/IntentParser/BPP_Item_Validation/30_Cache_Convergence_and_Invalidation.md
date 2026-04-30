---
tags: [bpp-validation, feedback-loop, postgresql, semantic-cache, architecture]
cssclasses: [procurement-doc, ai-doc]
status: "#approved"
related: ["[[09_bpp_catalog_semantic_cache_Schema]]", "[[27_One_Table_Rationale]]", "[[35_Stage3_Observability_Metrics]]"]
---

# Cache Convergence and Invalidation

## Convergence Property

The cache converges toward full BPP item vocabulary coverage through usage:

- Each unique MCP fallback that succeeds adds one Path B row.
- Enterprise procurement catalogs are **bounded and finite** — the item namespace is not unbounded like general web search.
- As user queries accumulate, the cache converges toward covering the full BPP item vocabulary.
- The MCP fallback rate **decreases monotonically** — the system becomes faster purely through usage.
- Path A rows from BPP registrations provide a proactive baseline that accelerates convergence.

At steady state, the primary path (~15ms) handles the vast majority of queries, with MCP fallbacks reserved for genuinely novel item requests.

## Invalidation Rules

| Trigger | Rule |
|---|---|
| **Time-based staleness** | Rows with `last_seen_at < NOW() - interval '7 days'` are excluded from VALIDATED decisions (reclassified as AMBIGUOUS). Staleness window is a configurable database value. |
| **BPP re-registration (Path A)** | `CatalogCacheWriter` upserts on re-publish; items absent from the new batch are not updated and eventually become stale. Nightly hard-delete job removes rows past staleness window. |
| **MCP re-confirmation (Path B)** | `MCPResultAdapter` upserts on `(item_name, bpp_id)` conflict, refreshing `last_seen_at`, `descriptions`, `embedding_strategy`. A Path A row is upgraded to Path B quality. |
| **Threshold recalibration** | Changing the threshold affects query-time decisions only. No row deletions required. |

## Staleness Window

The staleness window of `7 days` is a **configurable database value** (not hardcoded). Rows with `last_seen_at < NOW() - interval '7 days'` are excluded from VALIDATED decisions and reclassified as AMBIGUOUS — they are treated as uncertain until re-confirmed rather than deleted immediately. The nightly hard-delete job permanently removes rows that have been stale for longer than the configured window.

## Monitoring Convergence

The `item_validation_cache_hit_rate` metric in [[35_Stage3_Observability_Metrics]] directly tracks convergence progress. An alert fires if hit rate is < 50% after 2-week warm-up, indicating insufficient seeding or threshold issues.

---

## Related Notes

- [[09_bpp_catalog_semantic_cache_Schema]] — `last_seen_at` and `hit_count` columns used in invalidation
- [[27_One_Table_Rationale]] — Path A → Path B upgrade during MCP re-confirmation
- [[35_Stage3_Observability_Metrics]] — `item_validation_cache_hit_rate` convergence metric
