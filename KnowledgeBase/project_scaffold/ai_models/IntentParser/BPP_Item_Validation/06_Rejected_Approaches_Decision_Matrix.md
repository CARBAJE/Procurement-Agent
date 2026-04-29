---
tags: [bpp-validation, architecture, beckn, intent-parser]
cssclasses: [procurement-doc, ai-doc]
status: "#approved"
related: ["[[03_Double_Discover_Anti_Pattern]]", "[[04_Iterative_Degradation_Search]]", "[[07_Hybrid_Architecture_Overview]]"]
---

# Rejected Approaches — Decision Matrix

## Full Decision Matrix

| Criterion | Approach A (Probe) | Approach B (Degradation) | Approved (Hybrid) |
|---|---|---|---|
| **P99 validation latency** | +10s | +12–40s | +10–20ms |
| **BPP network calls per query** | 2× | (n+1)× | 1× (unchanged) |
| **Semantic accuracy** | Pass/fail only | Low — no semantic model | High — cosine similarity |
| **User transparency** | None | None | Explicit suggestions |
| **Protocol compliance** | ❌ Misuses `discover` | ❌ Misuses `discover` n× | ✅ No extra discover calls |
| **Lambda coupling** | ❌ L1 → L2 hard dep. | ❌ L1 → L2 n× | ✅ L1 → PostgreSQL (isolated) |
| **Cold-start behavior** | Works immediately | Works immediately | MCP fallback until warm |
| **Alignment with tech stack** | Partial | Partial | ✅ Full (PostgreSQL existing) |

---

## Interpretation

Both rejected approaches fail across latency, protocol compliance, and Lambda coupling simultaneously. The approved hybrid architecture wins on every criterion that matters for production procurement:

- **P99 latency** drops from 10–40s to 10–20ms on the primary path
- **Protocol compliance** is restored — no extra `discover` calls during intent parsing
- **Semantic accuracy** shifts from binary pass/fail to graded cosine similarity with explicit suggestions
- **Lambda coupling** is eliminated — Lambda 1 depends only on its local PostgreSQL instance

The trade-off is **cold-start behavior**: the approved hybrid requires cache warm-up before the primary path is effective. This is addressed by the [[33_Cold_Start_Strategy]] and the MCP fallback path which operates during warm-up.

---

## Related Notes

- [[03_Double_Discover_Anti_Pattern]] — Approach A detail and rejection rationale
- [[04_Iterative_Degradation_Search]] — Approach B detail and rejection rationale
- [[07_Hybrid_Architecture_Overview]] — The approved hybrid architecture
