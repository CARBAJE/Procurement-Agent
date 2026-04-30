---
tags: [bpp-validation, mcp, intent-parser, beckn, api-contract]
cssclasses: [procurement-doc, ai-doc]
status: "#approved"
related: ["[[18_MCP_Fallback_Tool_Overview]]", "[[20_MCP_LLM_Reasoning_Loop]]", "[[21_MCP_Bounding_Constraints]]"]
---

# `search_bpp_catalog` — Tool Specification

## Tool Name

```
search_bpp_catalog
```

## Description

```
Searches the live Beckn BPP network for items matching the
given procurement query. Activate ONLY when the semantic
cache returns no high-confidence match. Performs a bounded
discovery probe with a reduced timeout.
```

## Input Parameters

| Parameter | Type | Required | Description |
|---|---|---|---|
| `item_name` | `str` | required | The extracted item label. |
| `descriptions` | `list[str]` | optional | Atomic technical specification tokens. |
| `location` | `str` | optional | `"lat,lon"` coordinates. |

## Output Fields

| Field | Type | Description |
|---|---|---|
| `found` | `bool` | Whether any matching items were found. |
| `items` | `list[dict]` | Matching catalog entries (see sub-fields below). |
| `query_used` | `str` | Exact query sent to BPP network. May differ if LLM reformulated. |
| `probe_latency_ms` | `int` | Actual round-trip time in ms. |

### `items` Sub-Fields

Each dict in `items` contains:

| Sub-field | Description |
|---|---|
| `item_name` | BPP canonical item name |
| `bpp_id` | Source BPP identifier |
| `bpp_uri` | BPP endpoint URI |
| `provider_id` | Provider sub-ID within the BPP |
| `category` | Product category |

## Notes

- `query_used` may differ from the input `item_name` if the LLM reformulated the query on a second tool call (see [[20_MCP_LLM_Reasoning_Loop]])
- The `items` list contains already-normalized `DiscoverOffering`-equivalent dicts — `CatalogNormalizer` has already run inside the BAP Client before the response reaches the MCP tool
- This is an existence probe only; the full offering list for the authoritative discover is retrieved by Lambda 2 independently

---

## Related Notes

- [[18_MCP_Fallback_Tool_Overview]] — Sidecar architecture and what this tool does NOT do
- [[20_MCP_LLM_Reasoning_Loop]] — How the LLM uses this tool in the reasoning loop
- [[21_MCP_Bounding_Constraints]] — Constraints governing this tool's execution
