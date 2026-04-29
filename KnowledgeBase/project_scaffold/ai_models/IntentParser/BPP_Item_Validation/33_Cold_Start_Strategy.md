---
tags: [bpp-validation, cold-start, architecture, postgresql, feedback-loop]
cssclasses: [procurement-doc, ai-doc]
status: "#approved"
related: ["[[25_CatalogCacheWriter]]", "[[22_Feedback_Loop_Overview]]", "[[35_Stage3_Observability_Metrics]]"]
---

# Cold-Start Strategy

## Context

The cache is **empty on first deployment**. Every query triggers the MCP fallback until the cache warms. This is expected and handled gracefully — the [[07_Hybrid_Architecture_Overview]] fallback path is designed to work correctly with an empty cache.

## Accelerated Seeding Options (Priority Order)

### 1. Replay Historical `on_discover` Callbacks

If past BPP callback payloads are stored in PostgreSQL via the Kafka consumer, re-process them through `CatalogNormalizer` → `CatalogCacheWriter` → cache **before the first user query**. This is the fastest path to a warm cache and leverages existing data with no new infrastructure.

### 2. Startup BPP Scrape

On `beckn-bap-client` start, proactively fire a discover call to known BPPs and route responses through Path A (`CatalogCacheWriter`). This seeds the cache with the current BPP catalog before any user queries arrive.

### 3. Static Seed File

A curated CSV of commonly procured items with BPP identifiers, embedded and loaded at deploy time. This provides a warm start for high-frequency item categories (e.g., office supplies, standard industrial components) without requiring live BPP network calls at startup.

### 4. Accept Organic Warm-Up (Simplest PoC)

The cache fills naturally. The first query per item category triggers the MCP fallback; all subsequent queries hit the cache. This is the simplest implementation for a proof-of-concept deployment where cold-start latency for the first few queries is acceptable.

## Monitoring Cold-Start Progress

The `item_validation_cache_hit_rate` and `item_validation_mcp_fallback_rate` metrics in [[35_Stage3_Observability_Metrics]] directly track warm-up progress. The hit rate should rise steadily from 0% toward the steady-state level over the first 1–2 weeks of usage.

---

## Related Notes

- [[25_CatalogCacheWriter]] — Path A writer used in options 1 and 2
- [[22_Feedback_Loop_Overview]] — The feedback loop that drives organic warm-up (option 4)
- [[35_Stage3_Observability_Metrics]] — Metrics for monitoring warm-up progress
