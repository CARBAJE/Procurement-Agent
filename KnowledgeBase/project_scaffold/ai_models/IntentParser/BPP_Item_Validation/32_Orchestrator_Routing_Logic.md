---
tags: [bpp-validation, api-contract, architecture, beckn]
cssclasses: [procurement-doc, ai-doc]
status: "#approved"
related: ["[[31_ParseResponse_Extended_Schema]]", "[[15_Three_Zone_Decision_Space]]"]
---

# Orchestrator Routing Logic

## Full Routing Table

| `validation.status` | Orchestrator Action |
|---|---|
| `VALIDATED` | Proceed to Lambda 2 discover. `beckn_intent.item` is trusted. |
| `MCP_VALIDATED` | Proceed to Lambda 2 discover. `beckn_intent.item` updated to MCP-confirmed canonical name. |
| `AMBIGUOUS` | **Block Lambda 2.** Return `suggestions` to frontend. Await user selection. Re-submit with confirmed item. |
| `NOT_FOUND` | **Block Lambda 2.** Return `suggestions` (near-miss cache candidates) or empty list. Prompt user to rephrase. |

## Routing Behavior Notes

### VALIDATED and MCP_VALIDATED

Both proceed to Lambda 2's authoritative discover call unchanged. The difference is that `MCP_VALIDATED` carries a potentially updated `beckn_intent.item` (BPP canonical name from the MCP probe) while `VALIDATED` uses the original LLM-extracted item name that was confirmed by the semantic cache.

Lambda 2's single authoritative `POST /discover` call is preserved in both cases — the validation step does not replace it, only front-loads a confidence check.

### AMBIGUOUS

Lambda 2 is **blocked** — the procurement pipeline halts pending user input. The frontend receives the `suggestions` list from [[31_ParseResponse_Extended_Schema]] with `confidence_label` values. The user selects the correct item and re-submits with the confirmed item name, which then routes back through Stage 3 (expected to hit the VALIDATED zone).

### NOT_FOUND

Lambda 2 is **blocked**. The frontend receives either near-miss cache candidates (AMBIGUOUS-zone items from the cache that didn't meet the strict threshold) or an empty list. The user is prompted to rephrase. This is the graceful degradation path for items genuinely absent from the BPP network.

---

## Related Notes

- [[31_ParseResponse_Extended_Schema]] — Full schema of the ParseResponse feeding this routing logic
- [[15_Three_Zone_Decision_Space]] — Zone definitions that produce the status values
