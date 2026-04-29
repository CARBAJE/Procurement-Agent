---
tags: [bpp-validation, architecture, intent-parser, beckn, feedback-loop, catalog-normalizer, pgvector, mcp]
cssclasses: [procurement-doc, ai-doc]
status: "#approved"
related: ["[[14_Cost_Asymmetry_Procurement_Validation]]", "[[23_CatalogNormalizer_SRP_Boundary]]", "[[22_Feedback_Loop_Overview]]"]
---

# Architectural Principles

## P1 — Primary Path Has No Live Network Call

The VALIDATED path completes Stage 3 with only a PostgreSQL query (~10–20ms). Deterministic, bounded, no timeout risk. The entire validation resolves in memory against the local pgvector index. No external service, no async callback, no timeout uncertainty. This is the fundamental design invariant of the hybrid architecture.

## P2 — MCP Is an LLM Affordance, Not a Mechanical Fallback

The BPP probe is embedded in the LLM reasoning loop, enabling semantic self-correction of `BecknIntent.item`. This is consistent with the ReAct framework in [[agent_framework_langchain_langgraph]]. The LLM inspects results, selects the best semantic match, and may reformulate the query — behaviors that a mechanical HTTP call cannot replicate. The MCP fallback is a reasoning affordance, not a retry mechanism.

## P3 — PostgreSQL Is the Right Store for This Cache

Bounded corpus, ACID write guarantees for the feedback loop, colocation with procurement transactional data. Qdrant is reserved for the unbounded agent memory RAG corpus. The `bpp_catalog_semantic_cache` has a finite namespace (enterprise procurement catalogs converge). Using Qdrant for this would add infrastructure overhead and operational complexity with no performance benefit at catalog scale.

## P4 — Strict Threshold Asymmetry Is Non-Negotiable for Procurement

False positives → wrong-item orders (high cost). False negatives → extra latency only (low cost). The threshold is set to minimize false positives. This asymmetry is formally derived in [[14_Cost_Asymmetry_Procurement_Validation]]: a 1-in-100 false positive rate is the maximum acceptable for enterprise procurement at the Precision ≥ 0.99 target.

## P5 — The CatalogNormalizer's SRP Is Inviolable

It normalizes raw BPP formats for the Comparison Engine. It is never modified, never called from Lambda 1, and never called on already-normalized data. Cache population is handled by dedicated, separate writers (`CatalogCacheWriter` and `MCPResultAdapter`). The existing 17-unit test suite covers `CatalogNormalizer`'s contract exactly — no new behavior should be injected into it. See [[23_CatalogNormalizer_SRP_Boundary]].

## P6 — The Feedback Loop Is the Value Accumulation Mechanism

Each MCP fallback that succeeds narrows the gap between the two tiers. The system becomes faster purely through usage — a compounding improvement that rewards adoption. The more queries the system processes, the warmer the cache, the lower the MCP fallback rate, the faster every subsequent query. This is the economic moat of the architecture: the system improves without retraining.

## P7 — Validation Result Is Explicit in the API Contract

`ValidationResult` is a first-class field in `ParseResponse`. The orchestrator routes on `status`. The frontend displays suggestions on `AMBIGUOUS`. The validation behavior is fully observable and testable. No hidden validation state — every downstream consumer can inspect exactly what the validator decided and why.

## P8 — Reserve Live BPP Discover Calls for Actual Buyer Intent

The Beckn Protocol semantically treats every `discover` call as real buyer intent. The semantic cache eliminates validation probes from the BPP network. MCP fallback calls are bounded, semantically scoped to existence confirmation, and carry no follow-up `select` signals. This preserves BPP network hygiene: BPPs only see real procurement interest, not validation traffic. This is a protocol compliance principle, not just a performance principle.

---

## Related Notes

- [[14_Cost_Asymmetry_Procurement_Validation]] — P4 formal derivation
- [[23_CatalogNormalizer_SRP_Boundary]] — P5 technical analysis
- [[22_Feedback_Loop_Overview]] — P6 feedback loop design
