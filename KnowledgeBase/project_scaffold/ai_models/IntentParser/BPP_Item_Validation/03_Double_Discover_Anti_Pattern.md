---
tags: [bpp-validation, architecture, beckn, intent-parser]
cssclasses: [procurement-doc, ai-doc]
status: "#approved"
related: ["[[05_Live_Network_Validation_Root_Cause]]", "[[06_Rejected_Approaches_Decision_Matrix]]", "[[18_MCP_Fallback_Tool_Overview]]"]
---

# Double-Discover Anti-Pattern (Rejected Approach A)

## Proposal

After Stage 2 produces a `BecknIntent`, call `POST /discover` on Lambda 2 as a validation probe before returning the intent to the orchestrator.

---

## Why It Fails

| Problem | Impact |
|---|---|
| **Double-discover** | Every valid query generates **2 full Beckn network requests**. BPPs cannot distinguish probes from real intent. |
| **Protocol misuse** | The Beckn `discover` call semantically signals buyer intent to BPPs. There is no "catalog check" endpoint. Using `discover` for validation triggers BPP analytics, rate limiting, and potential session side-effects. |
| **Latency** | CALLBACK_TIMEOUT is 10 seconds. Adding a validation probe at Lambda 1 adds up to 10 seconds before the user sees a parse result. |
| **Lambda coupling** | Lambda 1 gains a hard runtime dependency on Lambda 2, violating the independent-scaling principle of the Step Functions model. |

---

## MCP Variant Note

The MCP variant of this approach adds LLM self-correction capability but does not eliminate the double-discover or latency problems. The root cause — making live BPP network calls at intent-parse time — is identical. See [[05_Live_Network_Validation_Root_Cause]].

---

## Verdict

**Rejected as a primary strategy.** Acceptable only as a cold-start fallback with a reduced 3-second timeout and strict call count limit (≤ 2).

---

## Related Notes

- [[05_Live_Network_Validation_Root_Cause]] — The shared root cause of both naive approaches
- [[06_Rejected_Approaches_Decision_Matrix]] — Full decision matrix comparing all three approaches
- [[18_MCP_Fallback_Tool_Overview]] — The MCP tool used in the approved fallback (bounded, sidecar, LLM-in-loop)
