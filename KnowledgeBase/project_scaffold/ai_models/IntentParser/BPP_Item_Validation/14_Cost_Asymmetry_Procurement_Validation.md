---
tags: [bpp-validation, threshold, validation, architecture]
cssclasses: [procurement-doc, ai-doc]
status: "#approved"
related: ["[[13_Error_Types_and_Costs]]", "[[15_Three_Zone_Decision_Space]]", "[[16_Threshold_Calibration_Methodology]]", "[[38_Architectural_Principles]]"]
---

# Cost Asymmetry — Why the Threshold Must Be High

## The Asymmetric Cost Statement

The cost asymmetry is severe and unambiguous:

- **False positive** → wrong product ordered → operational and financial damage
- **False negative** → extra latency → recoverable, no incorrect outcome

## Precision vs Recall Formulation

The system therefore optimizes for **high precision** at moderate recall:

```
Precision = TP / (TP + FP)   ← minimize FP  →  set threshold HIGH
Recall    = TP / (TP + FN)   ← FN accepted  →  threshold may be strict
```

## Target

**Precision ≥ 0.99** — at most 1 in 100 cache hits is for a semantically different item.

## Conclusion

The system **optimizes for high precision at moderate recall**. False negatives (cache misses that trigger the MCP fallback) are an acceptable operational cost — they add latency but produce no incorrect procurement outcomes. False positives (wrong item validated as correct) cause high-severity incidents in enterprise procurement.

This cost asymmetry is formalized as Architectural Principle P4 in [[38_Architectural_Principles]]: "Strict threshold asymmetry is non-negotiable for procurement."

---

## Related Notes

- [[13_Error_Types_and_Costs]] — Concrete examples of both error types with their costs
- [[15_Three_Zone_Decision_Space]] — The three-zone structure built on this cost model
- [[16_Threshold_Calibration_Methodology]] — How to empirically derive the threshold value
- [[38_Architectural_Principles]] — P4: Strict threshold asymmetry is non-negotiable for procurement
