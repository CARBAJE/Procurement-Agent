---
tags: [user-story, emergency, time-pressure, compliance, ppe, multi-location, urgency-detection, auto-approve]
cssclasses: [procurement-doc, story-doc]
status: "#processed"
related: ["[[nl_intent_parser]]", "[[beckn_bap_client]]", "[[approval_workflow]]", "[[audit_trail_system]]", "[[communication_slack_teams]]", "[[business_impact_metrics]]"]
---

# User Story 3: Emergency Procurement Under Time Pressure

## Persona
**Anita Desai** — Facilities Manager, hospital chain.
Critical medical supply (PPE kits) running low due to unexpected patient surge.

## Current State (As-Is)

- Calls 8 suppliers one by one. Half don't pick up. Two are out of stock.
- Gets 3 verbal quotes, negotiates on phone, places emergency order.
- Cannot document the process under time pressure.
- Auditors later **flag the purchase as non-compliant**.
- End-to-end: **4–6 hours** of frantic phone calls.

> [!guardrail] The Compliance Failure Mode
> Manual emergency procurement creates a systematic compliance gap: the urgency of the situation forces the procurement manager to skip documentation steps, which then gets flagged by auditors. This is not a human failure — it is a **process design failure**. The agent solves this by capturing the full audit trail automatically in real-time, regardless of time pressure.

## Step-by-Step Agent Journey

**Input:** "URGENT: 10,000 PPE kits, Level 3 protection, deliver to 4 hospital locations within 24 hours."

1. [[nl_intent_parser]] detects urgency flag from `"URGENT:"` prefix.
2. **Emergency procurement mode activated:**
   - Wider search radius.
   - Parallel queries to **all Beckn networks simultaneously** via [[beckn_bap_client]].
   - Relaxed price thresholds.
3. Within 15 seconds: 6 sellers with available stock identified. 2 can deliver within 24 hours.
4. [[comparison_scoring_engine]] auto-selects fastest supplier meeting quality requirements (Level 3 certification mandatory).
5. [[approval_workflow]] flags CFO with **60-minute auto-approve countdown**.
6. CFO approves immediately. Order confirmed across **4 delivery locations simultaneously** via [[beckn_bap_client]].
7. [[audit_trail_system|Full audit trail captured automatically]] — every decision documented with reasoning, even under emergency conditions.

> [!architecture] Technical Workflow
> `NL Parser (urgency detection)` → `Emergency Mode Activation` → `Parallel multi-network discover (concurrent sync queries to multiple Discovery Services)` → `Compliance Filter (Level 3 cert)` → `Speed-Priority Scoring` → `[[approval_workflow|Approval Routing]] (CFO + countdown)` → `/confirm (multi-location)` → `[[event_streaming_kafka|Kafka]] (audit)` → `[[communication_slack_teams|Notification]]`.

> [!insight] Emergency to Compliant in 3 Minutes
> The historical failure mode — hours of calls, incomplete documentation, audit flag, potential penalty — is replaced with 3 minutes of automated action with full compliance. The [[audit_trail_system|audit trail]] captures everything: which sellers were found, why the fastest was selected, when CFO approval was granted. This is the story that resonates most strongly with hospital, utilities, and defence procurement audiences.

## Expected Outcomes

| Metric | Before | After |
|---|---|---|
| Emergency procurement time | 4–6 hours | 3 minutes |
| Compliance status | Flagged non-compliant | Full compliance maintained |
| Documentation | Incomplete, reconstructed | Complete, real-time, auditable |
