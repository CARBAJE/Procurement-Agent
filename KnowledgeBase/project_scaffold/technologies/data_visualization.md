---
tags: [technology, frontend, visualization, recharts, d3, analytics, dashboard, charts]
cssclasses: [procurement-doc, tech-doc]
status: "#processed"
related: ["[[frontend_react_nextjs]]", "[[analytics_dashboard]]", "[[phase3_advanced_intelligence_enterprise_features]]", "[[business_impact_metrics]]", "[[kpis_metrics]]"]
---

# Data Visualization

> [!architecture] Role in the System
> Data visualization libraries power the [[analytics_dashboard]] component inside the [[frontend_react_nextjs|React/Next.js]] frontend. They render procurement KPIs, spend analysis, savings tracking, and supplier benchmarking reports as interactive charts — giving procurement leadership (CPO persona in [[story4_strategic_sourcing_analysis|Story 4]]) the visual evidence needed for contract renewal negotiations.

## Libraries

| Library | Role |
|---|---|
| Recharts | React-native charting library for standard analytics charts |
| D3.js | Low-level data visualization for custom/complex charts |

> [!tech-stack] Recharts + D3 Combination
> **Recharts** is the primary choice for standard charts (bar, line, area, pie) because it is React-first, declarative, and handles 90% of dashboard needs with minimal code. **D3.js** is used for custom visualizations (e.g., the supplier comparison radar chart, the savings-over-time heatmap) where Recharts' abstraction is insufficient. Both libraries are already included in the [[frontend_react_nextjs]] bundle — no additional dependencies.

## Dashboard Metrics (6+ Required, [[phase3_advanced_intelligence_enterprise_features|Phase 3]])

| # | Metric | Chart Type | Data Source |
|---|---|---|---|
| 1 | Procurement cycle time (before vs. after) | Grouped bar | [[databases_postgresql_redis\|PostgreSQL]] |
| 2 | Cost savings from negotiation (90-day rolling) | Line chart | [[databases_postgresql_redis\|PostgreSQL]] |
| 3 | Platform licensing cost savings | Comparison bar | Manual input + PostgreSQL |
| 4 | Team productivity (requests per FTE) | KPI card + trend | [[databases_postgresql_redis\|PostgreSQL]] |
| 5 | Audit preparation time reduction | Before/after card | Manual baseline + PostgreSQL |
| 6 | Supplier performance (ratings, fulfillment, returns) | Radar / table | [[event_streaming_kafka\|Kafka]] → PostgreSQL |

## CPO Benchmarking Report Feature ([[story4_strategic_sourcing_analysis|Story 4]])

- Shadow `/search` queries across ONDC for each of 50 procurement categories.
- Comparison: current contract terms vs. live market offers.
- Flagged categories: where enterprise overpays by > 10%.
- Visualized as: heatmap of overpayment % by category + bar chart of identified savings.

> [!milestone] Phase 3 Acceptance (Weeks 9–12)
> From [[phase3_advanced_intelligence_enterprise_features|Phase 3 Analytics Dashboard milestone]]:
> - Dashboard shows **6+ metrics** with drill-down capability.
> - Benchmarking report generated from live shadow `/search` queries.
> - Each metric has drill-down (e.g., click on a category to see individual supplier breakdown).

> [!insight] Business Impact of Visualization
> The CPO benchmarking report (Story 4) identified **₹8.3 crore annually** in savings potential across 12 of 50 categories — evidence that would have taken 3 analysts 2 weeks to compile manually. The visual report format gives CPOs concrete negotiation leverage in contract renewals. See [[business_impact_metrics]] for full targets.
