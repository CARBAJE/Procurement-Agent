---
tags: [bpp-validation, mcp, intent-parser, beckn, architecture]
cssclasses: [procurement-doc, ai-doc]
status: "#approved"
related: ["[[19_search_bpp_catalog_Tool_Spec]]", "[[21_MCP_Bounding_Constraints]]", "[[38_Architectural_Principles]]"]
---

# MCP LLM Reasoning Loop

## Design Principle

The MCP tool is embedded in the **LLM reasoning loop** — not a mechanical post-processing HTTP call. When Stage 3 detects a cache miss, control returns to the LLM with the `search_bpp_catalog` tool available.

This is consistent with the ReAct framework referenced in [[38_Architectural_Principles]] P2: "MCP is an LLM affordance, not a mechanical fallback."

## 4-Step LLM Reasoning Sequence

1. Calls `search_bpp_catalog` with the originally extracted `item_name`.
2. Inspects results: if items are returned, selects the best semantic match and updates `BecknIntent.item` to the BPP canonical name.
3. If no results on the first call, may **reformulate** `item_name` (more generic synonym or standard abbreviation) and call the tool once more.
4. If both calls return empty, returns a structured `NOT_FOUND` response with AMBIGUOUS-zone cache candidates as suggestions.

## Maximum Tool Calls

**2 tool calls per validation cycle.** This limit is enforced by [[21_MCP_Bounding_Constraints]] and prevents runaway tool-use loops.

## Semantic Self-Correction

This LLM-in-the-loop behavior enables **semantic self-correction** — the model reasons about whether found items match the user's procurement intent, not just whether any BPP returned a result.

Example: if the user queried "stainless 316L flanged valve" and the first call returns "SS316 flange valve 2in", the LLM can recognize this as the correct item despite zero lexical overlap with "316L" vs "SS316", and update `BecknIntent.item` accordingly. The `query_used` field in the [[19_search_bpp_catalog_Tool_Spec]] output captures whether reformulation occurred.

## Impact on `BecknIntent.item`

After step 2, `beckn_intent.item` in the [[31_ParseResponse_Extended_Schema]] **may be updated** to the BPP canonical name. This is the MCP self-correction mechanism. The `validation.status` will be `MCP_VALIDATED` and `validation.validated_item` will hold the confirmed canonical name.

---

## Related Notes

- [[19_search_bpp_catalog_Tool_Spec]] — The tool being called in this loop
- [[21_MCP_Bounding_Constraints]] — Maximum 2 tool calls, 3s timeout
- [[38_Architectural_Principles]] — P2: MCP is an LLM affordance, not a mechanical fallback
