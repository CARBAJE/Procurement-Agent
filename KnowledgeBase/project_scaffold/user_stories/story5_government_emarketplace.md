---
tags: [user-story, government, gem, l1-selection, public-procurement, rti, compliance, quality-floor]
cssclasses: [procurement-doc, story-doc]
status: "#processed"
related: ["[[nl_intent_parser]]", "[[beckn_bap_client]]", "[[comparison_scoring_engine]]", "[[approval_workflow]]", "[[audit_trail_system]]", "[[audit_splunk_servicenow]]", "[[business_impact_metrics]]"]
---

# User Story 5: Government e-Marketplace Procurement

## Persona
**Dr. Meera Krishnan** — District Collector, responsible for procurement across 15 government offices.
Subject to strict public procurement rules: **GeM compliance**, **L1 (lowest bidder) selection mandatory**.

## Current State (As-Is)

- Staff manually enters requirements on GeM portal.
- Waits for bids, manually verifies each bidder's credentials.
- Awards to lowest compliant bidder (L1 rule).
- Process: transparent but extremely slow — **15–30 days**.
- Does not account for quality or delivery reliability in selection criteria.

## Future State — Agent Configuration

The agent is **pre-configured for government procurement rules**:
- L1 (lowest price) selection is **mandatory** among qualified sellers.
- Quality floor applied first: rating ≥ 4.0, compliance certifications present.
- Full Right to Information (RTI) documentation generated automatically.

## Step-by-Step Agent Journey

1. Dr. Krishnan submits requirements through the [[frontend_react_nextjs|agent dashboard]].
2. [[beckn_bap_client|Agent]] searches ONDC for sellers meeting **minimum quality standards** (rating ≥ 4.0, certifications present).
3. Among qualified sellers, [[comparison_scoring_engine|agent auto-selects L1]] (lowest price) per government rules.
4. Full transparency report generated:
   - All sellers considered.
   - Qualification reasoning for each seller.
   - L1 selection justification (price comparison table).
5. **RTI-ready documentation created automatically** — every decision traceable and explainable via [[audit_trail_system]].

> [!architecture] Technical Workflow
> `NL Parser` → `ONDC /search` → `/on_search` → `Compliance Filter (quality floor: rating ≥ 4.0 + certifications)` → `L1 Selection (deterministic: lowest price among qualified)` → `Transparency Report Generation` → `RTI Document Export` → `[[event_streaming_kafka|Kafka → PostgreSQL → Splunk]]`.

> [!guardrail] L1 Compliance Enforcement
> The L1 selection rule is **deterministic and non-overridable** in government mode. The agent cannot select a higher-priced seller without a documented policy exception approved by a designated authority. Any override attempt is logged to [[audit_trail_system|audit events]] and flagged in [[audit_splunk_servicenow|ServiceNow]].
> The quality floor (rating ≥ 4.0) prevents the L1 rule from being exploited by low-quality sellers undercutting on price — addressing the known failure mode of pure L1 selection.

> [!insight] Government Procurement Impact
> Government procurement accounts for a substantial share of ONDC transaction volume. Digitizing the L1 procurement workflow from 15–30 days to 2–3 days while maintaining full RTI compliance is a compelling government use case — particularly when the agent generates RTI documentation automatically, eliminating a major administrative burden for government procurement officers. See [[business_impact_metrics]].

## Expected Outcomes

| Metric | Before | After |
|---|---|---|
| Procurement cycle time | 15–30 days | 2–3 days |
| RTI documentation | Significant manual effort | Generated automatically |
| Quality control | L1 only (no floor) | L1 with quality floor |
| Compliance | Manual verification | Automated, guaranteed |
