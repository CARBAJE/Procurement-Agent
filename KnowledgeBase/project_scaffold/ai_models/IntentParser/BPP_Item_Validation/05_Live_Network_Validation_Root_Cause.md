---
tags: [bpp-validation, architecture, beckn, intent-parser]
cssclasses: [procurement-doc, ai-doc]
status: "#approved"
related: ["[[03_Double_Discover_Anti_Pattern]]", "[[04_Iterative_Degradation_Search]]", "[[07_Hybrid_Architecture_Overview]]"]
---

# Root Cause — Why Live-Network Validation Fails

## The Shared Root Cause

Both [[03_Double_Discover_Anti_Pattern]] and [[04_Iterative_Degradation_Search]] attempt to validate item existence by making **live BPP network calls at intent-parse time**.

## Why Beckn Discover Is Inherently Expensive

The Beckn discover flow is inherently asynchronous:

```
BAP → ONIX → BPP → on_discover callback → CallbackCollector queue
```

This async round-trip is **structurally expensive** and cannot be made cheap without changing the Beckn protocol itself. The `CALLBACK_TIMEOUT` is 10 seconds at Lambda 2. Even a reduced 3-second timeout (as used in the MCP fallback) still adds substantial latency at intent-parse time.

There is no synchronous "catalog check" endpoint in the Beckn protocol. Every `discover` call:
- Routes through the ONIX gateway to the BPP network
- Triggers BPP analytics and rate limiting logic
- Semantically signals buyer intent to BPPs
- Waits for an async callback response via the `CallbackCollector` queue

## The Architecturally Correct Solution

The architecturally correct solution is to **decouple validation from the live BPP network** by maintaining a local semantic representation of the BPP catalog that can answer "does this item exist?" in milliseconds, without a network call.

This is the foundation of the [[07_Hybrid_Architecture_Overview]] — the approved Stage 3 Hybrid Item Validator uses a PostgreSQL pgvector semantic cache for the primary validation path (~15ms), deferring live BPP network calls exclusively to cache misses and bounding them with strict constraints.

---

## Related Notes

- [[03_Double_Discover_Anti_Pattern]] — Approach A: direct API probe
- [[04_Iterative_Degradation_Search]] — Approach B: word-truncation search
- [[07_Hybrid_Architecture_Overview]] — The approved solution: local semantic cache + bounded MCP fallback
