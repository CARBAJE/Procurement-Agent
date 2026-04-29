---
tags: [bpp-validation, architecture, beckn, intent-parser]
cssclasses: [procurement-doc, ai-doc]
status: "#approved"
related: ["[[05_Live_Network_Validation_Root_Cause]]", "[[06_Rejected_Approaches_Decision_Matrix]]"]
---

# Iterative Degradation Search (Rejected Approach B)

## Proposal

If the initial probe returns zero results, remove the last word from `item` iteratively until a result is found.

```
"stainless 316L flanged valve 2 inch ASME" → 0 results
"stainless 316L flanged valve 2 inch"       → 0 results
"stainless 316L flanged valve 2"            → 0 results
"stainless 316L flanged valve"              → 3 results ← accept
```

---

## Why It Fails

| Problem | Impact |
|---|---|
| **Latency** | Worst case: `n_words × timeout` = 4 words × 10s = **40 seconds**. Even at 3s/probe: 12 seconds. Unacceptable for interactive procurement. |
| **No semantic model** | Right-truncation does not understand which tokens are load-bearing. `"hydraulic pump 50 bar"` → `"hydraulic pump"` drops the critical pressure spec. `"A4"` alone matches folders, binders, and index cards. |
| **False positives** | A match on a truncated string is not a match for the user's intent. The system reports "validated" while proceeding with an incorrect item class. |
| **BPP load** | `(n+1)` discover calls per query multiplied across all users. |

---

## Verdict

**Rejected as any primary or secondary strategy.** Retained as a tertiary cold-cache fallback only, with hard limits of ≤ 2 iterations, ≤ 2s timeout per probe, applied to the `descriptions` token list (atomically decomposed) rather than the `item` string.

---

## Related Notes

- [[05_Live_Network_Validation_Root_Cause]] — The shared root cause of both naive approaches
- [[06_Rejected_Approaches_Decision_Matrix]] — Full decision matrix comparing all three approaches
