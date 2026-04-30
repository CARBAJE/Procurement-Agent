---
tags: [bpp-validation, threshold, validation, architecture, intent-parser]
cssclasses: [procurement-doc, ai-doc]
status: "#approved"
related: ["[[13_Error_Types_and_Costs]]", "[[14_Cost_Asymmetry_Procurement_Validation]]", "[[16_Threshold_Calibration_Methodology]]", "[[31_ParseResponse_Extended_Schema]]", "[[32_Orchestrator_Routing_Logic]]"]
---

# The Three-Zone Decision Space

## Zone Table

```
SIMILARITY SCORE    ZONE          DECISION                           LATENCY
────────────────────────────────────────────────────────────────────────────
  ≥ 0.92          │ VALIDATED   │ Cache HIT — proceed directly     │ +~15ms
  0.75 – 0.91     │ AMBIGUOUS   │ Return suggestions for user      │ +~15ms
                  │             │ confirmation — do NOT proceed    │
  < 0.75          │ CACHE MISS  │ Trigger MCP fallback (bounded)   │ +15ms
  (no rows)       │ COLD START  │   → MCP fallback                 │   + 1–8s
```

## Critical Note on the AMBIGUOUS Zone

**The AMBIGUOUS zone is NOT a fallback trigger — it is a user confirmation gate.**

The system has found candidate matches but cannot certify them above the strict procurement precision threshold. The system returns the top-3 suggestions with human-readable confidence labels ("Very likely match", "Possible match"). The user selects and the pipeline proceeds with the confirmed item.

This is a deliberate design choice rooted in [[14_Cost_Asymmetry_Procurement_Validation]]: at similarity 0.75–0.91, triggering an MCP fallback would be latency-expensive and might still return a semantically ambiguous result. Instead, the human buyer — who knows what they need — makes the final call.

## Zone Behavior Summary

| Zone | Similarity | Latency | Lambda 2 Blocked? | User Sees |
|---|---|---|---|---|
| VALIDATED | ≥ 0.92 | ~15ms | No — proceeds | Parse result |
| AMBIGUOUS | 0.75–0.91 | ~15ms | Yes | Top-3 suggestions with confidence labels |
| CACHE MISS | < 0.75 | 15ms + 1–8s | Conditional | Result after MCP probe |
| COLD START | No rows | 1–8s | Conditional | Result after MCP probe |

## Confidence Labels

The top-3 suggestions returned in the AMBIGUOUS zone carry human-readable confidence labels. The `Suggestion` sub-type in [[31_ParseResponse_Extended_Schema]] includes `confidence_label` alongside `item_name`, `bpp_id`, `similarity_score`, and `embedding_strategy`.

---

## Related Notes

- [[13_Error_Types_and_Costs]] — Why the threshold boundary is set where it is
- [[14_Cost_Asymmetry_Procurement_Validation]] — The cost model driving the three-zone design
- [[16_Threshold_Calibration_Methodology]] — How the 0.92 threshold was derived
- [[31_ParseResponse_Extended_Schema]] — ParseResponse fields including `suggestions` and `confidence_label`
- [[32_Orchestrator_Routing_Logic]] — How the orchestrator routes on each zone status
