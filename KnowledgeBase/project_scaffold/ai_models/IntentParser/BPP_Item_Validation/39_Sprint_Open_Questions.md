---
tags: [bpp-validation, sprint-ready, pgvector, hnsw, mcp, postgresql, embedding, intent-parser]
cssclasses: [procurement-doc, ai-doc]
status: "#approved"
related: ["[[10_HNSW_Index_Strategy]]", "[[17_Threshold_Sensitivity_Analysis]]", "[[25_CatalogCacheWriter]]", "[[21_MCP_Bounding_Constraints]]"]
---

# Implementation Sprint — Open Questions

## Question 1 — pgvector Version and `ef_search` Tuning

What pgvector version is installed? What `ef_search` value balances recall vs. latency for initial catalog sizes of 100–10,000 entries?

Context: the [[10_HNSW_Index_Strategy]] specifies `ef_search=100` as the starting point, but the optimal value is corpus-size-dependent and pgvector-version-dependent. The installed version may affect available index types and parameter ranges.

## Question 2 — Embedding Model Sovereignty

If data residency prohibits the OpenAI API (`text-embedding-3-small`), which self-hosted model produces the tightest clusters for short technical procurement item names?

Priority candidates:
- `nomic-embed-text` (768 dims, Ollama-compatible)
- `all-MiniLM-L6-v2` (384 dims, fast but lower quality for technical text)

Context: the [[16_Threshold_Calibration_Methodology]] empirical guidance is calibrated for `text-embedding-3-small`. A different model will require re-running the threshold calibration procedure — the threshold value 0.92 should not be transferred across embedding models without validation.

## Question 3 — MCP Server Transport

Use `stdio` transport (embedded in `intention-parser` process, simpler for PoC) or `SSE/HTTP` transport (separate port, required for horizontal scaling)?

Context: `stdio` transport is simpler for a PoC but limits the `intention-parser` to single-instance deployment of the MCP server. If horizontal scaling of `intention-parser` is required, each instance needs its own MCP sidecar process (`stdio`) or they can share a networked MCP server (`SSE/HTTP`).

## Question 4 — Async Write Failure Isolation

Define the exact error handling contract: write failures from `CatalogCacheWriter` or `MCPResultAdapter` must log to [[audit_trail_system]] but must never raise exceptions visible to the Stage 3 caller.

Context: [[25_CatalogCacheWriter]] and [[26_MCPResultAdapter]] both specify "async, non-blocking" behavior and that write failures are logged but not propagated. The exact exception handling pattern (try/except scope, log format, retry policy) needs to be defined before implementation.

## Question 5 — Category Pre-Filter

Should `category_tag` be used as a `WHERE` pre-filter before the ANN search? Improves precision but requires Stage 2 `BecknIntentParser` to also extract a category classification — minor prompt extension.

Context: the `category_tag` column in [[09_bpp_catalog_semantic_cache_Schema]] is nullable and supports pre-filtering. Using it as a WHERE clause before the ANN search reduces the search space and improves precision for cases where the category is unambiguous. The trade-off is a Stage 2 prompt extension to extract category alongside item and descriptions.

## Question 6 — Threshold as a Runtime Configuration

Should the similarity threshold live as a service environment variable (requires redeployment to change) or as a database-stored configuration record (live adjustment via governance UI, no restart)?

Context: [[17_Threshold_Sensitivity_Analysis]] notes that the threshold should be recalibrated quarterly and is category-dependent. A database-stored configuration record enables live adjustment without a deployment cycle, which aligns better with the quarterly recalibration cadence and category-level tuning requirement.

## Question 7 — Path A Descriptions Enrichment (Future Phase 2)

A Phase 2 enhancement for `CatalogCacheWriter` could extract spec tokens from raw BPP catalog `tags[]` or `descriptor.short_desc` fields *before* normalization, upgrading Path A rows to `item_name_and_specs` quality without requiring an MCP confirmation.

Context: currently `CatalogCacheWriter` receives `DiscoverOffering[]` which does not carry `descriptions`. This enhancement would require `CatalogCacheWriter` to receive the raw BPP payload alongside the normalized output, or for `CatalogNormalizer` to optionally pass-through the raw `tags[]` field. This is a Phase 2 item — not required for the PoC but represents a meaningful quality improvement for the proactive cache path.

---

## Related Notes

- [[10_HNSW_Index_Strategy]] — ef_search specification and HNSW rationale (Q1)
- [[17_Threshold_Sensitivity_Analysis]] — Threshold values and category-dependent tuning (Q6)
- [[25_CatalogCacheWriter]] — Path A writer affected by Q4 and Q7
- [[21_MCP_Bounding_Constraints]] — MCP transport and timeout context (Q3)
