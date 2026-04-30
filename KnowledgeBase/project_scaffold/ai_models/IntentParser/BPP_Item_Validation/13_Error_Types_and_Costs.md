---
tags: [bpp-validation, threshold, validation, architecture]
cssclasses: [procurement-doc, ai-doc]
status: "#approved"
related: ["[[14_Cost_Asymmetry_Procurement_Validation]]", "[[15_Three_Zone_Decision_Space]]", "[[17_Threshold_Sensitivity_Analysis]]"]
---

# The Two Error Modes and Their Costs

## Context

Every binary threshold over a continuous similarity score generates two error types. The relative cost of each determines where the threshold must sit.

---

## Error Type I — False Positive (Threshold Too Low)

The cache returns a match for an item that is semantically different from what the user requested.

```
User requests:  "hydraulic gate valve 2 inch"
Cache returns:  "hydraulic ball valve 2 inch"  at similarity 0.84
Threshold 0.80: → CACHE HIT → procurement proceeds for the WRONG valve type
```

**Cost:** An approved order for an incorrect industrial component triggers operational delays, return logistics, supplier disputes, and erosion of trust in the AI system. In enterprise procurement, this is a **high-severity incident**.

---

## Error Type II — False Negative (Threshold Too High)

The cache fails to recognize a legitimate synonym match and triggers an MCP fallback unnecessarily.

```
User requests:  "stainless flanged valve 2 inch"
Cache contains: "SS316 flange valve 2in"  at similarity 0.91
Threshold 0.93: → CACHE MISS → MCP fallback triggered
```

**Cost:** Added latency (1–8 seconds) and one additional BPP network call. The user still receives correct results. **No procurement error occurs.**

---

## Cost Comparison

| Error Type | Mechanism | Consequence | Severity |
|---|---|---|---|
| Type I (False Positive) | Threshold too low — wrong item passes | Wrong product ordered | High — operational incident |
| Type II (False Negative) | Threshold too high — synonym missed | Extra latency + MCP call | Low — recoverable |

The severe asymmetry between these two costs is the core driver of the threshold design. See [[14_Cost_Asymmetry_Procurement_Validation]] for the formal treatment and threshold target.

---

## Related Notes

- [[14_Cost_Asymmetry_Procurement_Validation]] — Formal cost asymmetry analysis and Precision ≥ 0.99 target
- [[15_Three_Zone_Decision_Space]] — How the threshold maps to the three-zone decision space
- [[17_Threshold_Sensitivity_Analysis]] — Sensitivity table across threshold values 0.80–0.98
