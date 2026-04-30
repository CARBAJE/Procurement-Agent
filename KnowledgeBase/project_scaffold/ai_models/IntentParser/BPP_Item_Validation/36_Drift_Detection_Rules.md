---
tags: [bpp-validation, observability, architecture, intent-parser]
cssclasses: [procurement-doc, ai-doc]
status: "#approved"
related: ["[[35_Stage3_Observability_Metrics]]", "[[16_Threshold_Calibration_Methodology]]"]
---

# Drift Detection Rules

## Rule 1 — `mcp_fallback_rate` > 50% Sustained After 2-Week Warm-Up

**Evidence of:** threshold too strict, embedding model weak clustering, or insufficient seeding.

**Action:** Run threshold recalibration (Section 6.4 methodology — [[16_Threshold_Calibration_Methodology]]) on accumulated query data.

Specifically: collect all query vectors and their matched cache entries from the past 2 weeks, re-compute the positive-pair and hard-negative-pair similarity distributions on actual production data, and find the threshold that achieves ≥ 0.99 precision on that data. The calibrated threshold replaces the PoC starting point of 0.92.

## Rule 2 — `not_found_rate` > 20%

**Evidence of:** users requesting items not in connected BPPs, or Stage 2 extracting over-specified labels.

**Action:** Stage 2 prompt review (over-specification guard), or BPP catalog coverage expansion.

Specifically: audit Stage 2 `BecknIntentParser` prompt behavior on not-found cases — is it extracting over-specific labels that no BPP can match? Or are users genuinely requesting items outside the connected BPP ecosystem? The former is addressed by a Stage 2 prompt refinement to add an over-specification guard; the latter by onboarding additional BPPs.

## Governance Note

Both conditions are logged to [[model_governance_monitoring]] as **override events** and trigger investigation within **48 hours** per governance policy.

These are not silent metrics — they are first-class events in the model governance pipeline, treated with the same urgency as model accuracy regressions.

---

## Related Notes

- [[35_Stage3_Observability_Metrics]] — The metrics these rules monitor
- [[16_Threshold_Calibration_Methodology]] — The recalibration methodology referenced in Rule 1
