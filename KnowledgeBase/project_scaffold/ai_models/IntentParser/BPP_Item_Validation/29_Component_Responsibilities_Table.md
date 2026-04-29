---
tags: [bpp-validation, feedback-loop, catalog-normalizer, architecture, postgresql]
cssclasses: [procurement-doc, ai-doc]
status: "#approved"
related: ["[[25_CatalogCacheWriter]]", "[[26_MCPResultAdapter]]", "[[23_CatalogNormalizer_SRP_Boundary]]"]
---

# Component Responsibilities Summary

## Full Component Responsibilities Table

| Component | Service Location | Input | Output | Calls `CatalogNormalizer`? |
|---|---|---|---|---|
| `CatalogNormalizer` | `beckn-bap-client/src/normalizer/` | Raw BPP `on_discover` callback envelope | `list[DiscoverOffering]` | — (is the normalizer) |
| `CatalogCacheWriter` | `beckn-bap-client/src/cache/` | `list[DiscoverOffering]` | PostgreSQL INSERT, Path A | ❌ No |
| `MCPResultAdapter` | `intention-parser/src/validation/` | `DiscoverOffering[]` + `BecknIntent` | PostgreSQL INSERT, Path B | ❌ No |

## Key Points

- **`CatalogNormalizer`** never calls itself and is never called by either writer. Its responsibility ends after producing `DiscoverOffering[]`.
- **`CatalogCacheWriter`** receives `DiscoverOffering[]` from `CatalogNormalizer` via the BAP Client's internal pipeline. It does not call `CatalogNormalizer` — the normalization has already happened.
- **`MCPResultAdapter`** receives already-normalized `DiscoverOffering[]` from the MCP tool response (which already ran through `CatalogNormalizer` inside the BAP Client) plus `BecknIntent` from Stage 2. Neither is a raw BPP payload.

Both writer components produce `PostgreSQL INSERT` operations into `bpp_catalog_semantic_cache` using different embedding strategies and source values. Neither modifies `CatalogNormalizer`, neither is called by `CatalogNormalizer`, and neither introduces any cross-service dependency that violates the Lambda 1 / Lambda 2 boundary.

---

## Related Notes

- [[25_CatalogCacheWriter]] — Path A writer: `beckn-bap-client/src/cache/`
- [[26_MCPResultAdapter]] — Path B writer: `intention-parser/src/validation/`
- [[23_CatalogNormalizer_SRP_Boundary]] — Why CatalogNormalizer cannot serve either writer role
