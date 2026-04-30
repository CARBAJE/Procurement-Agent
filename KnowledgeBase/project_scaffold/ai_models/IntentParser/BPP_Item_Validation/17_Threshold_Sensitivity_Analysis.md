---
tags: [bpp-validation, threshold, validation, observability]
cssclasses: [procurement-doc, ai-doc]
status: "#approved"
related: ["[[16_Threshold_Calibration_Methodology]]", "[[15_Three_Zone_Decision_Space]]", "[[35_Stage3_Observability_Metrics]]", "[[39_Sprint_Open_Questions]]"]
---

# Threshold Sensitivity Analysis

## Sensitivity Table

| Threshold | False Positive Risk | MCP Fallback Rate | Assessment |
|---|---|---|---|
| 0.80 | High — hard negatives frequently exceed this | Low | ❌ Unacceptable: wrong items proceed |
| 0.85 | Moderate — some hard negatives admitted | Low-moderate | ❌ Too permissive for high-value items |
| 0.90 | Low — most hard negatives excluded | Moderate | ⚠ Acceptable lower bound for low-risk categories |
| **0.92** | **Very low — near-synonym quality required** | **Moderate-high** | **✅ Recommended PoC starting point** |
| 0.95 | Near-zero | High — true synonyms begin missing | ⚠ Many unnecessary MCP calls |
| 0.98 | Near-zero | Very high — only near-identical strings pass | ❌ Cache largely useless |

## The Threshold Is Not Static

**Category-dependent:**
- Office supplies tolerate a lower bound (~0.88)
- Industrial components (valves, pumps, bearings) should use 0.92–0.93 with `category_tag` pre-filtering

Higher-stakes procurement categories (wrong part ordered → operational shutdown) warrant a stricter threshold than general office supplies where returns are low-friction.

**Recalibrated quarterly:**
As the MCP feedback loop enriches the cache (see [[30_Cache_Convergence_and_Invalidation]]), the positive-pair similarity distribution shifts upward as Path B rows accumulate. This potentially allows a marginal increase in threshold without increasing false negatives. Quarterly recalibration using the [[16_Threshold_Calibration_Methodology]] methodology on accumulated query data keeps the threshold optimally positioned.

## Monitoring

The `item_validation_threshold_breaches` metric in [[35_Stage3_Observability_Metrics]] tracks sustained AMBIGUOUS zone widening, which signals that threshold adjustment may be needed.

The `ef_search` parameter interaction with threshold is captured in [[39_Sprint_Open_Questions]] question 1.

---

## Related Notes

- [[16_Threshold_Calibration_Methodology]] — How to empirically derive the threshold
- [[15_Three_Zone_Decision_Space]] — The zone structure this threshold governs
- [[35_Stage3_Observability_Metrics]] — `item_validation_threshold_breaches` metric
- [[39_Sprint_Open_Questions]] — Question 1: pgvector version and ef_search tuning; Question 6: threshold as runtime config
