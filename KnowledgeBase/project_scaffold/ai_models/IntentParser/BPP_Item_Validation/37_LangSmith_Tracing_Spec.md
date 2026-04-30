---
tags: [bpp-validation, observability, intent-parser, architecture]
cssclasses: [procurement-doc, ai-doc]
status: "#approved"
related: ["[[35_Stage3_Observability_Metrics]]", "[[12_Full_System_Validation_Flow]]"]
---

# LangSmith Tracing Specification

## Tracing Context

Every Stage 3 execution is a **child span** of the `POST /parse` LangSmith trace. This means all Stage 3 validation data is captured within the same trace as Stage 1 (IntentClassifier) and Stage 2 (BecknIntentParser), providing a unified view of the full parse request lifecycle.

## Span Specification

```
Span name:  item_validation
Input:      { item, descriptions, query_vector_preview[0:8] }
Output:     ValidationResult
Tags:       cache_hit, mcp_used, similarity_score, status, embedding_strategy
Sub-spans:  pg_vector_query (latency), mcp_tool_call (latency, if triggered)
```

## Span Fields Detail

### Input

- `item` — The `BecknIntent.item` string from Stage 2
- `descriptions` — The `BecknIntent.descriptions` list from Stage 2
- `query_vector_preview[0:8]` — First 8 dimensions of the 1536-dim query vector (for debugging embedding model behavior without storing the full vector)

### Output

- `ValidationResult` — The full `ValidationResult` object from [[31_ParseResponse_Extended_Schema]] (`status`, `cache_hit`, `similarity_score`, `validated_item`, `mcp_used`, `suggestions`)

### Tags

Structured tags on the span for filtering and analytics in LangSmith:

- `cache_hit` (bool) — Whether the primary path produced a VALIDATED result
- `mcp_used` (bool) — Whether the MCP fallback was triggered
- `similarity_score` (float) — Top cosine similarity score from the pgvector query
- `status` (str) — `VALIDATED` | `AMBIGUOUS` | `MCP_VALIDATED` | `NOT_FOUND`
- `embedding_strategy` (str) — Strategy of the matched row (`item_name_only` | `item_name_and_specs`)

### Sub-spans

- `pg_vector_query` — Captures pgvector query latency; always present
- `mcp_tool_call` — Captures MCP tool call latency; only present when triggered (cache miss); may appear 1–2 times per validation cycle per [[21_MCP_Bounding_Constraints]]

---

## Related Notes

- [[35_Stage3_Observability_Metrics]] — Aggregate Prometheus/Grafana metrics complementing this per-request tracing
- [[12_Full_System_Validation_Flow]] — The full flow these traces instrument
