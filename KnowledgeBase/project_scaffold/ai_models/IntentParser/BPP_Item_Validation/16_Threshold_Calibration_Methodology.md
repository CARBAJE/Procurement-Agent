---
tags: [bpp-validation, threshold, validation, embedding]
cssclasses: [procurement-doc, ai-doc]
status: "#approved"
related: ["[[14_Cost_Asymmetry_Procurement_Validation]]", "[[15_Three_Zone_Decision_Space]]", "[[17_Threshold_Sensitivity_Analysis]]"]
---

# Threshold Derivation Methodology

## Principle

The threshold value must be derived empirically, not set by intuition.

## Evaluation Dataset Construction

**Positive pairs** — same item, different terminology:
- `("SS316 flange valve 2in", "stainless 316L flanged valve 2 inch")`
- `("A4 paper 80gsm", "A4 printer paper 80 g/m²")`

**Hard negative pairs** — different items, similar vocabulary:
- `("hydraulic gate valve", "hydraulic ball valve")`
- `("A4 paper", "A4 notebook")`
- `("Cat6 cable", "Cat5e cable")`

**Easy negative pairs** — different domain:
- `("printer paper", "hydraulic pump")`

## 4-Step Procedure

1. Embed all strings with `text-embedding-3-small`.
2. Compute pairwise cosine similarity for all pairs.
3. Find the threshold that achieves ≥ 0.99 precision on the positive class.
4. Validate on a held-out test set.

## Empirical Guidance

Short technical procurement names (< 10 tokens) with `text-embedding-3-small` produce:

- **≥ 0.93** for true synonyms (positive pairs)
- **0.75–0.89** cluster for hard negatives
- **Below 0.65** for easy negatives (different domain)

This places the optimal threshold in the **0.90–0.94** band.

**Conservative PoC starting point: 0.92.**

This starting point reflects:
- True synonyms reliably exceed 0.93 → 0.92 threshold admits near-synonyms with one additional confidence unit of buffer
- Hard negatives cluster below 0.89 → 0.92 excludes them with a 0.03 safety margin
- The AMBIGUOUS zone (0.75–0.91) captures the hard-negative cluster for human review rather than automatic processing

---

## Related Notes

- [[14_Cost_Asymmetry_Procurement_Validation]] — Why precision ≥ 0.99 is the target
- [[15_Three_Zone_Decision_Space]] — The three-zone structure built on the 0.92 threshold
- [[17_Threshold_Sensitivity_Analysis]] — Sensitivity analysis across threshold values
