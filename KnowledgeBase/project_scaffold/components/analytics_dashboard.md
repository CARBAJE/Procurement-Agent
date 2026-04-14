---
tags: [component, frontend, analytics, metrics, spend-analysis, benchmarking, recharts, d3]
cssclasses: [procurement-doc, component-doc]
status: "#processed"
related: ["[[frontend_react_nextjs]]", "[[data_visualization]]", "[[databases_postgresql_redis]]", "[[event_streaming_kafka]]", "[[phase3_advanced_intelligence_enterprise_features]]", "[[story4_strategic_sourcing_analysis]]", "[[business_impact_metrics]]", "[[technical_performance_metrics]]"]
---

# Component: Analytics Dashboard

> [!architecture] Role in the System
> The Analytics Dashboard is the **CPO's command center** — a [[frontend_react_nextjs|React/Next.js]] page powered by [[data_visualization|Recharts and D3.js]] that visualizes procurement KPIs, savings trends, and supplier performance. It also hosts the **Benchmarking Report** feature ([[story4_strategic_sourcing_analysis|Story 4]]), where the agent runs shadow `discover` queries across ONDC to compare current contract terms against live market pricing — in advisory mode, with no purchases executed.

## Metrics Displayed (6+ Required, Phase 3)

| # | Metric | Chart Type | Data Source |
|---|---|---|---|
| 1 | Procurement cycle time (before vs. after) | Grouped bar | [[databases_postgresql_redis\|PostgreSQL]] |
| 2 | Cost savings from negotiation (90-day rolling) | Line chart | PostgreSQL |
| 3 | Platform licensing cost savings | Comparison bar | Baseline input + PostgreSQL |
| 4 | Team productivity (requests per FTE/month) | KPI card + trend | PostgreSQL |
| 5 | Audit preparation time reduction | Before/after card | Baseline + PostgreSQL |
| 6 | Supplier performance | Ratings, fulfillment, return rates | [[event_streaming_kafka\|Kafka]] → PostgreSQL |

> [!tech-stack] Recharts + D3 Combination
> Standard KPI charts (lines, bars, cards) use [[data_visualization|Recharts]] for its React-native, declarative API. Complex custom charts (category heatmaps, supplier radar charts) use [[data_visualization|D3.js]] where Recharts' abstraction is insufficient. Both libraries are bundled in the [[frontend_react_nextjs]] app.

## CPO Benchmarking Feature ([[story4_strategic_sourcing_analysis|Story 4]])

- Initiates shadow `discover` queries across ONDC for each of 50 procurement categories.
- Advisory mode — queries for price discovery only, **no purchases executed**.
- Compares current contract terms against live market offers.
- Flags categories where enterprise overpays by > 10%.
- Generates benchmarking report with: flagged categories, total identified savings (e.g., ₹8.3 crore annually), per-category alternative suppliers with pricing, ratings, and suggested negotiation approach.

> [!milestone] Phase 3 Acceptance (Weeks 9–12)
> From [[phase3_advanced_intelligence_enterprise_features|Phase 3 Analytics Dashboard milestone]]:
> - Dashboard shows **6+ metrics** with drill-down capability (click category → see supplier breakdown).
> - Benchmarking report generated from live shadow `discover` queries.

> [!insight] CPO Value Proposition
> The quarterly sourcing analysis that previously took 3 analysts 2 weeks is completed in **4 hours** with full open-market coverage across all 50 categories. The ₹8–12 crore in annually identified savings gives CPOs concrete data-backed negotiation leverage. This makes the analytics dashboard one of the highest-ROI features for enterprise leadership adoption. See [[business_impact_metrics]] and [[user_adoption_metrics]].
