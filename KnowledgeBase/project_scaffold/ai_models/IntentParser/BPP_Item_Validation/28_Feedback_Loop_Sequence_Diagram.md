---
tags: [bpp-validation, feedback-loop, catalog-normalizer, architecture, postgresql]
cssclasses: [procurement-doc, ai-doc]
status: "#approved"
related: ["[[25_CatalogCacheWriter]]", "[[26_MCPResultAdapter]]", "[[23_CatalogNormalizer_SRP_Boundary]]"]
---

# Feedback Loop — Corrected Sequence Diagram

## Complete Mermaid Sequence Diagram

```mermaid
sequenceDiagram
    participant BPP as BPP Network
    participant BAP as BecknBAP Client<br/>(:8002)
    participant CN as CatalogNormalizer<br/>(inside BAP)
    participant CCW as CatalogCacheWriter<br/>(new — inside BAP)
    participant MCP as MCP Server<br/>(inside IntentParser)
    participant MRA as MCPResultAdapter<br/>(new — inside IntentParser)
    participant PG as PostgreSQL<br/>(bpp_catalog_semantic_cache)

    rect rgb(210, 240, 210)
        Note over BPP,PG: PATH A — Proactive, BPP-driven
        BPP->>BAP: on_discover callback (raw catalog payload)
        BAP->>CN: normalize({"message":{"catalog":{...}}}, bpp_id, bpp_uri)
        CN-->>BAP: list[DiscoverOffering]
        Note over CN: CatalogNormalizer is DONE — no further involvement
        BAP-)CCW: write_batch(offerings) [async, non-blocking]
        CCW->>PG: embed(item_name) → INSERT<br/>source='bpp_publish'<br/>strategy='item_name_only'
    end

    rect rgb(210, 225, 255)
        Note over BPP,PG: PATH B — Reactive, user-driven (MCP fallback)
        MCP->>BAP: POST /discover {BecknIntent probe, timeout=3s}
        BAP->>CN: normalize(raw_on_discover_callback, bpp_id, bpp_uri)
        CN-->>BAP: list[DiscoverOffering]
        Note over CN: CatalogNormalizer is DONE — already ran inside BAP
        BAP-->>MCP: DiscoverResponse {offerings:[DiscoverOffering...]}
        Note over MCP,MRA: MCP holds DiscoverOffering[] + original BecknIntent<br/>MCPResultAdapter bridges both — CatalogNormalizer NOT called
        MCP-)MRA: adapt(mcp_result, original_intent) [async, non-blocking]
        MRA->>PG: embed(item_name + " | " + join(descriptions))<br/>→ INSERT source='mcp_feedback'<br/>strategy='item_name_and_specs'
    end
```

## Participants

- **BPP Network** — Source of raw `on_discover` callback payloads (Path A) and target of MCP probe discover calls (Path B)
- **BecknBAP Client** (:8002) — Hosts `CatalogNormalizer` and `CatalogCacheWriter`; processes all BPP callbacks internally
- **CatalogNormalizer** (inside BAP) — Runs exactly once per BPP payload; outputs `DiscoverOffering[]`
- **CatalogCacheWriter** (new — inside BAP) — Path A writer; async, non-blocking PostgreSQL INSERT
- **MCP Server** (inside IntentParser) — Issues bounded discover probes; holds probe results
- **MCPResultAdapter** (new — inside IntentParser) — Path B writer; bridges `DiscoverOffering[]` + `BecknIntent`; async, non-blocking
- **PostgreSQL** (bpp_catalog_semantic_cache) — Single unified store for both paths

## Key Invariant

**`CatalogNormalizer` is called exactly once per BPP payload — inside the BAP Client. It is never called from Lambda 1, never called on `DiscoverOffering` objects, and never called from `MCPResultAdapter`.**

---

## Related Notes

- [[25_CatalogCacheWriter]] — Path A writer detail
- [[26_MCPResultAdapter]] — Path B writer detail
- [[23_CatalogNormalizer_SRP_Boundary]] — Why CatalogNormalizer's boundary is inviolable
