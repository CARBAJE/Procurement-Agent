---
tags: [bpp-validation, mcp, intent-parser, beckn, architecture]
cssclasses: [procurement-doc, ai-doc]
status: "#approved"
related: ["[[19_search_bpp_catalog_Tool_Spec]]", "[[20_MCP_LLM_Reasoning_Loop]]", "[[21_MCP_Bounding_Constraints]]", "[[08_Infrastructure_Component_Alignment]]"]
---

# MCP Fallback Tool Overview

## Sidecar Architecture

The MCP server runs as a **sidecar process within the `intention-parser` service**, exposing one tool to the IntentParser LLM: `search_bpp_catalog`. See [[19_search_bpp_catalog_Tool_Spec]] for the full tool specification.

The MCP server is embedded in the LLM reasoning loop — not a mechanical post-processing HTTP call. When Stage 3 detects a cache miss, control returns to the LLM with the tool available. This enables semantic self-correction of `BecknIntent.item`. See [[20_MCP_LLM_Reasoning_Loop]] for the full reasoning sequence.

The tool is bounded by strict constraints to prevent runaway latency and BPP network abuse. See [[21_MCP_Bounding_Constraints]] for the full constraint table.

## What the MCP Tool Does NOT Do

- Does **not** return the full offering list for user display. It is an existence probe.
- Does **not** replace Lambda 2's discover step. The orchestrator still calls Lambda 2 independently after VALIDATED or MCP_VALIDATED status; this single authoritative call is preserved and unchanged.
- Does **not** signal durable buyer intent to the BPP network (no follow-up `select` call, reduced timeout of 3s vs Lambda 2's 10s default).

## Relationship to [[08_Infrastructure_Component_Alignment]]

The MCP Server is listed in the infrastructure alignment table with role: "Exposes `search_bpp_catalog` tool to the LLM" and rationale: "Embeds validation in the LLM reasoning loop; enables self-correction; consistent with ReAct framework."

---

## Related Notes

- [[19_search_bpp_catalog_Tool_Spec]] — Tool name, description, input parameters, output fields
- [[20_MCP_LLM_Reasoning_Loop]] — 4-step LLM reasoning sequence; semantic self-correction
- [[21_MCP_Bounding_Constraints]] — 3s timeout, ≤2 tool calls, ~8s max latency
- [[08_Infrastructure_Component_Alignment]] — MCP Server in the infrastructure context
