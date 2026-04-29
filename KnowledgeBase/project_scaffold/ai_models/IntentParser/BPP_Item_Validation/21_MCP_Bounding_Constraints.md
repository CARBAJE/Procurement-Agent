---
tags: [bpp-validation, mcp, intent-parser, beckn, architecture]
cssclasses: [procurement-doc, ai-doc]
status: "#approved"
related: ["[[18_MCP_Fallback_Tool_Overview]]", "[[20_MCP_LLM_Reasoning_Loop]]", "[[19_search_bpp_catalog_Tool_Spec]]"]
---

# MCP Bounding Constraints

## Full Constraint Table

| Parameter | Value | Rationale |
|---|---|---|
| Discover probe timeout | **3 seconds** | Reduced from Lambda 2's 10s default; existence check, not full search |
| Maximum tool calls per cycle | **2** | Prevents runaway tool-use loops |
| Maximum MCP path latency | **~8 seconds** | 2 calls × 3s + ~2s LLM reasoning overhead |

## Constraint Rationale Detail

### 3-Second Timeout

The MCP probe is an existence check, not an authoritative full search. Lambda 2's 10-second `CALLBACK_TIMEOUT` is designed to wait for all BPPs in the network to respond. The MCP probe only needs to confirm existence in **at least one BPP** — a shorter timeout is acceptable.

The 3-second timeout means high-latency BPPs may be missed. This is **acceptable** because:
- The MCP probe confirms existence in at least one BPP
- Lambda 2's authoritative search (full 10s timeout) retrieves all offerings downstream after VALIDATED/MCP_VALIDATED status

### Maximum 2 Tool Calls

Prevents runaway tool-use loops in the LLM reasoning cycle described in [[20_MCP_LLM_Reasoning_Loop]]. The two-call budget allows:
- Call 1: original `item_name`
- Call 2: reformulated/more-generic synonym (if call 1 returned empty)

If both return empty, the status is `NOT_FOUND` with AMBIGUOUS-zone near-misses as suggestions.

### ~8-Second Maximum Path Latency

This bounds the worst-case user experience on the fallback path:
- 2 tool calls × 3s timeout = 6s
- ~2s LLM reasoning overhead for inspection and possible reformulation
- Total: ~8s maximum

This is contrasted with the primary path at ~15ms — the MCP fallback is only triggered on cache misses, which decrease monotonically as the cache warms per [[30_Cache_Convergence_and_Invalidation]].

---

## Related Notes

- [[18_MCP_Fallback_Tool_Overview]] — MCP sidecar design overview
- [[20_MCP_LLM_Reasoning_Loop]] — The 4-step reasoning sequence these constraints govern
- [[19_search_bpp_catalog_Tool_Spec]] — The tool subject to these constraints
