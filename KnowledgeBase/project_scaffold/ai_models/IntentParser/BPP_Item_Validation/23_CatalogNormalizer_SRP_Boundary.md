---
tags: [bpp-validation, catalog-normalizer, architecture, feedback-loop]
cssclasses: [procurement-doc, ai-doc]
status: "#approved"
related: ["[[22_Feedback_Loop_Overview]]", "[[25_CatalogCacheWriter]]", "[[26_MCPResultAdapter]]", "[[29_Component_Responsibilities_Table]]"]
---

# CatalogNormalizer — SRP Boundary Analysis

## What `CatalogNormalizer` Is Designed to Ingest

`CatalogNormalizer` (`services/beckn-bap-client/src/normalizer/`) has one contract: transform raw BPP `on_discover` callback payloads into `DiscoverOffering[]` for the Comparison Engine.

```
Input:  {"message": {"catalog": {<raw BPP catalog in one of 4 wire formats>}}}
Output: list[DiscoverOffering]
```

## `FormatDetector` — Four Wire Formats

| Variant | Root Key | Detection Predicate |
|---|---|---|
| `BECKN_V2_FLAT_RESOURCES` | `resources[]` | `isinstance(c.get("resources"), list) and len > 0` |
| `LEGACY_PROVIDERS_ITEMS` | `providers[].items[]` | `isinstance(c.get("providers"), list) and any("items" in p ...)` |
| `BPP_CATALOG_V1` | `items[]` + string `provider` | `isinstance(items[0]["provider"], str)` |
| `ONDC_CATALOG` | `fulfillments[]` + `tags[]` | `"fulfillments" in c and "tags" in c` |

## `DiscoverOffering` Output Contract

**The `DiscoverOffering` output carries:** `item_id`, `item_name`, `provider_id`, `provider_name`, `price_value`, `price_currency`, `rating`, `fulfillment_hours`. **It does NOT carry `descriptions`** — atomic spec tokens are a `BecknIntent` concept, not a `DiscoverOffering` concept.

## What the MCP Tool Actually Receives

When the MCP tool calls `POST http://beckn-bap-client:8002/discover`, the BAP Client processes the BPP callback internally through `CatalogNormalizer` and returns a fully normalized `DiscoverResponse`:

```
MCP calls:  POST /discover { BecknIntent }
BAP Client: ① ONIX → BPP → on_discover callback
            ② CatalogNormalizer.normalize(raw_callback) → DiscoverOffering[]
            ③ Returns DiscoverResponse { transaction_id, offerings: [DiscoverOffering...] }

MCP receives: already-normalized DiscoverOffering objects — not raw BPP payloads
```

The MCP tool **never sees the raw BPP catalog envelope**. By the time the probe result arrives, `CatalogNormalizer` has already run inside the BAP Client.

## Three Independent Grounds for Rejection

### Ground 1 — Input Type Mismatch (Hard Failure)

`CatalogNormalizer` expects `{"message": {"catalog": {...}}}`. A `DiscoverOffering` dict matches none of the four `FINGERPRINT_RULES` predicates. `FormatDetector` would return `UNKNOWN` for every MCP result, routing each one to `LLMFallbackNormalizer` — which would attempt to re-interpret an already-normalized object as a raw catalog. The outcome is undefined behavior and potential silent data corruption.

### Ground 2 — Data Availability Mismatch

The cache embedding requires both `item_name` (BPP-canonical) and `descriptions` (buyer spec tokens). These exist in two separate objects at MCP result time:

| Field needed | In `DiscoverOffering` | In `BecknIntent` |
|---|---|---|
| `item_name` (BPP canonical) | ✅ Yes | ❌ No — buyer's label |
| `descriptions` (spec tokens) | ❌ No — not extracted | ✅ Yes |
| `bpp_id`, `bpp_uri` | ✅ Yes | ❌ No |

No existing component holds both simultaneously. An adapter that bridges them is structurally necessary.

### Ground 3 — Single Responsibility Violation

`CatalogNormalizer`'s documented responsibility is format detection and schema mapping of raw BPP payloads for the Comparison Engine. Writing to a PostgreSQL semantic cache, calling an embedding API, and accessing a `BecknIntent` object are entirely outside this boundary. Extending it for the MCP path collapses two unrelated concerns, invalidates the existing 17-unit test suite, and creates a cross-service dependency (Lambda 2 component knowing about Lambda 1 data structures).

## Verdict

**Scenario B — Structurally incompatible at the ingestion level.** The Normalizer and the MCP feedback path occupy different positions in the data pipeline: the Normalizer sits at the raw-to-normalized transformation boundary inside Lambda 2; the MCP feedback write sits at the normalized-to-cached persistence boundary inside Lambda 1.

---

## Related Notes

- [[22_Feedback_Loop_Overview]] — Overview of the two-writer solution
- [[25_CatalogCacheWriter]] — Path A writer (separate class, zero CatalogNormalizer modification)
- [[26_MCPResultAdapter]] — Path B writer (holds both DiscoverOffering + BecknIntent)
- [[29_Component_Responsibilities_Table]] — Component responsibilities table
