---
tags: [user-story, strategic-sourcing, cpo, benchmarking, advisory-mode, shadow-search, savings-analysis]
cssclasses: [procurement-doc, story-doc]
status: "#processed"
related: ["[[analytics_dashboard]]", "[[beckn_bap_client]]", "[[comparison_scoring_engine]]", "[[data_visualization]]", "[[agent_memory_learning]]", "[[business_impact_metrics]]", "[[phase3_advanced_intelligence_enterprise_features]]"]
---

# User Story 4: Cross-Category Strategic Sourcing Analysis

## Persona
**Vikram Patel** — Chief Procurement Officer (CPO), manufacturing conglomerate.
Wants to benchmark current supplier contracts against open-market alternatives.

## Current State (As-Is)

- 3 analysts spend **2 weeks** on quarterly sourcing analysis.
- Covers only the top 50 procurement categories.
- Each category: only a handful of alternative suppliers checked — manual effort limits coverage.
- Analysis always incomplete; CPO lacks data-backed leverage in contract renewals.

## Step-by-Step Agent Journey

**Action:** Vikram initiates a "sourcing benchmark" run from the [[analytics_dashboard]].

1. Agent runs **shadow `/search` queries** across ONDC for each of 50 categories via [[beckn_bap_client]].
   - **Advisory mode only** — queries are for price discovery, no purchases executed.
2. For each category: [[comparison_scoring_engine]] compares current contract terms against live market offers.
3. Flags categories where the enterprise is **overpaying by more than 10%**.
4. Generates benchmarking report:
   - 12 of 50 categories show significant savings potential.
   - Total identified savings: **₹8.3 crore annually**.
5. Per flagged category: lists alternative suppliers with pricing, ratings, and suggested [[negotiation_engine|negotiation approach]].
6. Vikram uses the report in contract renewal discussions — with data-backed negotiation leverage.

> [!architecture] Technical Workflow
> `CPO Dashboard` → `Advisory /search (50 categories, parallel)` → `/on_search (market pricing)` → `[[comparison_scoring_engine|Comparison Engine]] (contract vs. market rate per category)` → `Savings Calculation` → `[[analytics_dashboard|Benchmarking Report Generation]]` ([[data_visualization|Recharts/D3]] visualizations) → `Export for negotiations`.

> [!insight] The Advisory Mode Advantage
> This story showcases a use case that closed platforms (SAP Ariba, Coupa) **cannot offer at all** — real-time open-market price discovery across all 50 categories simultaneously. The entire ONDC seller network responds to shadow queries with live pricing, giving the CPO a complete market picture rather than the curated subset available on a closed marketplace. The ₹8–12 crore annually in identified savings is typically 10–20× the system's operating cost.

## Expected Outcomes

| Metric | Before | After |
|---|---|---|
| Analysis time | 2 weeks (3 analysts) | 4 hours (automated) |
| Market coverage | Handful of alternatives per category | Full ONDC open market |
| Identified savings | Incomplete | ₹8–12 crore annually |

See [[business_impact_metrics]] for full quantification and context.
