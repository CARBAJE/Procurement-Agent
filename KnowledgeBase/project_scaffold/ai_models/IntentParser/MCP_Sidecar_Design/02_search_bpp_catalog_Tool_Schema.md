---
tags: [mcp, tool-schema, json-schema, beckn, search]
created: 2026-04-28
updated: 2026-04-29
status: approved
aliases: [search_bpp_catalog Schema]
cssclasses: [procurement-doc, ai-doc]
---

# `search_bpp_catalog` Tool Schema

This note defines the complete interface contract for the single MCP tool the sidecar exposes. For the full design index see [[00_MCP_Sidecar_Design_MOC]].

## Purpose

`search_bpp_catalog` is the single capability the MCP Sidecar advertises to MCP clients. The IntentParser's Stage 3 validation logic calls this tool whenever its pgvector semantic cache produces a miss — specifically, when the cosine similarity between the query embedding and the nearest cached vector falls below the 0.45 threshold. At that point, the cached catalog data is considered too stale or too distant to be reliable, and a live probe of the ONIX network is warranted. The tool accepts a structured description of a procurement item and returns the best-matching BPP catalog entries from the live Beckn peer-to-peer network, including the BPP identifiers needed by the IntentParser to route subsequent procurement actions. The sidecar exposes no other tools; this single-purpose design keeps the surface area minimal and the contract auditable.

## Full JSON Schema

The following object is the complete tool registration entry as it would appear in the MCP `tools/list` response payload.

```json
{
  "name": "search_bpp_catalog",
  "description": "Search the live ONIX Beckn network for a BPP catalog entry matching the given procurement item. Returns the best matching items with their BPP identifiers.",
  "inputSchema": {
    "type": "object",
    "properties": {
      "item_name": {
        "type": "string",
        "description": "Canonical item name extracted by the IntentParser (e.g. 'Stainless Steel Flanged Ball Valve')."
      },
      "descriptions": {
        "type": "array",
        "items": { "type": "string" },
        "description": "List of specification tokens (e.g. ['PN16', '2 inch', 'SS316']). May be empty."
      },
      "location": {
        "type": "string",
        "description": "Buyer location as 'lat,lon' string (e.g. '12.9716,77.5946'). Optional — omit if unknown."
      },
      "domain": {
        "type": "string",
        "description": "Beckn domain identifier for the search context (e.g. 'procurement', 'logistics', 'healthcare'). Caller must supply; the sidecar does not default this value."
      },
      "version": {
        "type": "string",
        "description": "Beckn protocol version string (e.g. '1.1.0'). Must match the version the BAP Client and ONIX network are configured to handle."
      }
    },
    "required": ["item_name", "descriptions", "domain", "version"]
  }
}
```

## Response Contract

The sidecar returns one of two shapes, depending on whether the ONIX probe yielded usable results. The MCP tool result is always a successful JSON-RPC response (never an error object) — see [[04_Timeouts_and_Failure_Handling]] for the rationale.

**Successful match — one or more catalog items found:**

```json
{
  "found": true,
  "items": [
    {
      "item_name": "Stainless Steel Flanged Ball Valve PN16 2 inch",
      "bpp_id": "bpp-industrial-supplies-mumbai",
      "bpp_uri": "https://bpp.industrialsupplies.in/beckn"
    }
  ],
  "probe_latency_ms": 1420
}
```

**No match — ONIX returned no results, or probe failed:**

```json
{
  "found": false,
  "items": [],
  "probe_latency_ms": 3000
}
```

**Field semantics:**

- `found` (boolean) — `true` if at least one catalog item was returned and successfully parsed from the ONIX response. `false` in all other cases: empty result set, BAP Client timeout, BAP Client unreachable, unparseable response, or input validation failure.
- `items` (array of objects) — zero or more catalog entries. Each entry contains:
  - `item_name` (string) — the item descriptor name as returned by the BPP in the ONIX catalog response. This may differ from the input `item_name` (it is the BPP's canonical name, not the buyer's).
  - `bpp_id` (string) — the unique Beckn identifier of the BPP that listed this item. Used by IntentParser to address subsequent `init`, `confirm`, and `status` actions.
  - `bpp_uri` (string) — the base URI of the BPP's Beckn endpoint. The BAP Client uses this to route Beckn actions directly to the correct BPP, bypassing the registry lookup on subsequent calls.
- `probe_latency_ms` (integer) — wall-clock milliseconds from when the sidecar began constructing the BAP Client request to when it received (or timed out waiting for) the response. Useful for monitoring ONIX network health and tuning the 3-second TTL. On a timeout, this value will be approximately 3000.

## Validation Rules

The sidecar must apply these rules before constructing the BAP Client request:

- `item_name` must be a non-empty string. A blank string (`""`) or whitespace-only string is treated as a validation failure; the sidecar returns `{"found": false, "items": [], "probe_latency_ms": 0}` immediately without calling the BAP Client.
- `descriptions` must be present and must be an array. An empty array (`[]`) is valid — it means no additional specification tokens were extracted by the IntentParser. The sidecar must not reject an empty descriptions array.
- `location`, if present, must match the pattern `<float>,<float>` (latitude, longitude). If the string does not match this pattern, the sidecar should omit the `fulfillment.end.location` field from the BAP Client payload rather than failing the entire request.
- `domain` must be a non-empty string. The sidecar maps it directly into the Beckn `context.domain` field. The sidecar imposes no allowlist — new domains are supported purely by updating the caller's configuration. A blank `domain` is a validation failure; return `{"found": false, "items": [], "probe_latency_ms": 0}`.
- `version` must be a non-empty string matching the semver-like pattern `<major>.<minor>.<patch>` (e.g., `"1.1.0"`). A blank or malformed version is a validation failure; return `{"found": false, "items": [], "probe_latency_ms": 0}`.
- The MCP sidecar must never return a JSON-RPC `error` response for any of the above conditions. All validation failures are surfaced as `found: false` in the tool result body. This preserves the IntentParser's ability to parse the response without defensive error-shape detection.

## Related Notes

- [[01_Sidecar_Architecture_and_Transport]] — transport layer and deployment context for this tool.
- [[03_BAP_Client_and_ONIX_Integration]] — how the validated arguments are mapped into a POST /discover payload sent to the BAP Client.
