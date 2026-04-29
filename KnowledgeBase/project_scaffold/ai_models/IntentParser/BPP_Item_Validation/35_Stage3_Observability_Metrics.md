---
tags: [bpp-validation, observability, architecture, intent-parser]
cssclasses: [procurement-doc, ai-doc]
status: "#approved"
related: ["[[36_Drift_Detection_Rules]]", "[[37_LangSmith_Tracing_Spec]]", "[[17_Threshold_Sensitivity_Analysis]]"]
---

# Stage 3 Observability Metrics

## Full Metrics Table

| Metric | Type | Alert Condition |
|---|---|---|
| `item_validation_cache_hit_rate` | Gauge | < 50% after 2-week warm-up → threshold or seeding review |
| `item_validation_similarity_score` | Histogram | Median < 0.80 → embedding model review |
| `item_validation_mcp_fallback_rate` | Counter | > 50% → threshold recalibration |
| `item_validation_mcp_latency_ms` | Histogram | P95 > 6000ms → timeout or BPP connectivity issue |
| `item_validation_not_found_rate` | Counter | > 20% → Stage 2 prompt review or BPP coverage gap |
| `item_validation_cache_write_latency_ms` | Histogram | P99 > 500ms → PostgreSQL performance review |
| `item_validation_threshold_breaches` | Counter | Sustained rise → AMBIGUOUS zone widening; consider threshold adjustment |
| `item_validation_path_a_writes` | Counter | Tracks `CatalogCacheWriter` throughput |
| `item_validation_path_b_writes` | Counter | Tracks `MCPResultAdapter` throughput |

## Metric Interpretations

### `item_validation_cache_hit_rate`

The primary convergence indicator. Should rise monotonically from 0% at deployment as the feedback loop populates the cache. < 50% after 2 weeks indicates either:
- Threshold set too strict (too many queries fall through to MCP)
- Insufficient seeding (see [[33_Cold_Start_Strategy]])

### `item_validation_mcp_fallback_rate`

> 50% sustained after 2-week warm-up triggers the drift detection rule in [[36_Drift_Detection_Rules]].

### `item_validation_not_found_rate`

> 20% triggers the second drift detection rule in [[36_Drift_Detection_Rules]]: evidence of over-specified Stage 2 extractions or BPP catalog coverage gaps.

### `item_validation_path_a_writes` and `item_validation_path_b_writes`

Together these track the relative contribution of proactive vs reactive cache population. A healthy system shows `path_a_writes` as baseline noise and `path_b_writes` decreasing over time as the cache warms and fewer MCP probes are needed.

---

## Related Notes

- [[36_Drift_Detection_Rules]] — Automated drift detection using these metrics
- [[37_LangSmith_Tracing_Spec]] — Per-request tracing complementing these aggregate metrics
- [[17_Threshold_Sensitivity_Analysis]] — How threshold adjustments affect fallback rates
