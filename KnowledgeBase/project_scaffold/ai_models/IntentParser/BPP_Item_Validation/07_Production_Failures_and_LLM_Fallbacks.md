---
tags: [architecture, fallback, unmet-demand, claude, production-readiness]
cssclasses: [procurement-doc, ai-doc]
status: "#draft"
related: ["[[32_Orchestrator_Routing_Logic]]", "[[20_MCP_LLM_Reasoning_Loop]]", "[[21_MCP_Bounding_Constraints]]", "[[12_Full_System_Validation_Flow]]", "[[36_Drift_Detection_Rules]]", "[[00_BPP_Validation_MOC]]"]
---

# Production Failures and LLM Fallbacks

> [!abstract] Scope
> This note documents the **Day 2 / production strategy** for the terminal failure case in Stage 3: when the semantic cache returns a `CACHE_MISS` **and** the bounded MCP fallback tool returns zero results. The PoC exits cleanly at this point. Production must not.

---

## A. The "Clean Dead-End" State (PoC Behaviour)

In the PoC (`Playground/end_to_end_intent_parser_poc.ipynb`), a complete MCP failure — zero BPP catalog matches after the bounded two-call reasoning loop — causes `run_stage3_hybrid_validation()` to return:

```python
ValidationResult(
    status=ValidationZone.NOT_FOUND,
    cache_hit=False,
    similarity_score=None,
    suggestions=[],
    mcp_used=True,
)
```

The [[32_Orchestrator_Routing_Logic|Orchestrator routing table]] maps `NOT_FOUND` to **block Lambda 2** and surface a rephrasing prompt to the buyer. The orchestrator is the sole decision-maker from this point forward.

This is architecturally correct for a PoC: the validation layer stays stateless, the decision is delegated upward, and no side effects are introduced. However, this design leaves genuine **unmet demand** invisible to the network — a production gap that must be closed.

---

## B. Production Recovery Strategies — Unmet Demand

When `status = NOT_FOUND` is confirmed (after both the semantic cache query and the MCP probe have been exhausted), production Lambda 1 must execute the following four recovery actions in sequence.

### B1. Buyer Notification

**What:** Surface an explicit, human-readable message to the buyer UI — not a generic "item not found" error, but a demand-aware notification:

> *"No supplier currently registered on the Beckn network carries an exact match for **[item_name]** with your specified requirements. Your request has been logged and an open RFQ has been broadcast to the network."*

**Why:** Without an explicit notification, the buyer has no signal to distinguish a parsing failure (correctable by rephrasing) from a genuine supply gap (requires a different workflow). Conflating the two erodes trust and generates unnecessary retry load.

**Orchestrator contract:** The `ParseResponse.validation` payload must carry a `buyer_message: str | None` field (null for all non-`NOT_FOUND` states) that the frontend renders verbatim.

---

### B2. Open RFQ Creation

**What:** Trigger an asynchronous broadcast of an open **Request For Quotation** to the Beckn network, keyed on the extracted `BecknIntent` — item name, descriptions, quantity, location, budget constraints, and delivery timeline.

**Mechanism:**

```
NOT_FOUND confirmed
     │
     ▼  (async, non-blocking to the buyer response)
┌─────────────────────────────────────────────┐
│  RFQ Publisher Lambda (new component)        │
│  1. Serialize BecknIntent → open_rfq payload │
│  2. POST /search to Beckn network gateway    │
│  3. Register callback URL for BPP responses  │
│  4. Store rfq_id → buyer_session mapping     │
└─────────────────────────────────────────────┘
```

**Protocol alignment:** The Beckn `search` intent with an open RFQ payload is semantically distinct from the standard `discover` call issued by Lambda 2. It signals to all registered BPPs that a buyer has unmet demand, allowing new suppliers to onboard or dormant suppliers to re-register their catalog.

**Key constraint:** The RFQ broadcast must be **fire-and-forget** from the Lambda 1 perspective. Lambda 1's response latency budget (~200ms) must not be consumed by the Beckn network round-trip. An async Kafka publish event is the correct mechanism.

---

### B3. Unmet Demand Logging

**What:** Write the failed search to a dedicated `unmet_demand_log` PostgreSQL table — separate from `bpp_catalog_semantic_cache` — for supply-chain analytics.

**Proposed schema:**

| Column | Type | Purpose |
|---|---|---|
| `id` | `UUID` | Primary key |
| `item_name` | `TEXT` | LLM-extracted item name from Stage 2 |
| `descriptions` | `TEXT[]` | Full spec tokens from `BecknIntent.descriptions` |
| `quantity` | `TEXT` | Raw quantity string |
| `budget_constraints` | `JSONB` | `{min, max}` budget from `BecknIntent` |
| `location` | `TEXT` | Delivery location coordinates |
| `mcp_query_attempted` | `BOOLEAN` | Whether the MCP tool was invoked |
| `session_id` | `TEXT` | Buyer session identifier |
| `logged_at` | `TIMESTAMPTZ` | Event timestamp |
| `broadened_item_name` | `TEXT` | Category-level name after Query Broadening (if applied) |
| `rfq_id` | `UUID` | Foreign key to the broadcast RFQ record |

**Analytics value:** Aggregated `unmet_demand_log` data answers the question: *"Which item categories are consistently requested but absent from the BPP network?"* This drives supply-side onboarding outreach and catalog gap analysis.

**Observability link:** The `not_found_rate` drift alert defined in [[36_Drift_Detection_Rules]] is powered by aggregate reads against this table.

---

### B4. Query Broadening — Category-Level Retry

**What:** Strip highly specific technical specifications from the extracted `BecknIntent` and retry Stage 3 validation at the **category level** — a single, automatically generated broader search.

**Example:**

| State | Item | Descriptions |
|---|---|---|
| Original `NOT_FOUND` | `"SS flanged ball valve, PN25, DN80, ASTM A351 CF8M"` | `["PN25", "DN80", "ASTM A351 CF8M", "stainless steel", "flanged"]` |
| After broadening | `"ball valve"` | `["stainless steel", "flanged"]` — pressure rating, size, material spec dropped |

**Goal:** Discover whether a *category-level* match exists in the cache or on the network. If a VALIDATED or AMBIGUOUS result is returned at the broader level, the orchestrator can offer category-level suggestions and partial matches to the buyer instead of a hard dead-end.

**Execution:** This is a single retry of `run_stage3_hybrid_validation()` with the broadened item name. It does **not** trigger another MCP call if the broad-level query also misses — the dead-end is accepted at that point.

**LLM requirement:** The spec-stripping logic requires semantic reasoning. See [[#C. The "Local-First, Cloud-Fallback" LLM Strategy]] below.

---

## C. The "Local-First, Cloud-Fallback" LLM Strategy

### C1. Baseline Routing Architecture

All standard, high-volume intent parsing uses **local Ollama models** (`qwen3:8b` for Stage 1 and complex Stage 2 queries, `qwen3:1.7b` for simple Stage 2 queries). This is a deliberate cost and latency optimisation — the models run on-premises with zero per-token API cost and sub-500ms latency for the common path.

```
Standard procurement query
     │
     ▼
Ollama qwen3:8b / qwen3:1.7b (local)
     │
     ├── ParsedIntent + BecknIntent extracted ──→ Stage 3 validation
     │
     └── [most queries end here — no cloud call made]
```

### C2. Fallback Trigger Conditions

The orchestrator must escalate to a cloud-based LLM in the following three cases:

| Trigger | Condition | Action |
|---|---|---|
| **Hallucination detected** | `BecknIntent.item` contains values flagged by the `@field_validator` guard (e.g., brand names in spec fields, impossible coordinate pairs) and retry budget on `qwen3` is exhausted after 3 attempts | Route full query to Claude |
| **Parse failure** | Local model returns a structurally invalid `BecknIntent` after `max_retries=3` and `InstructorRetryException` is raised | Route full query to Claude |
| **Query Broadening required** | `status = NOT_FOUND` after MCP exhaustion; spec-stripping reasoning is needed to safely degrade the `BecknIntent` | Route *broadening subtask* only to Claude |

The first two triggers are covered by the fallback chain already defined in [[../Core_Logic/22_Accuracy_Target_Fallback_Policy|Accuracy Target and Fallback Policy]]. The third is the new trigger introduced by the production recovery strategy.

### C3. The Query Broadening Subtask Prompt

When Claude is invoked for Query Broadening, the orchestrator issues a **focused, bounded subtask** — not a re-parse of the original query. The prompt structure:

```
SYSTEM:
You are a procurement specification analyst. Your task is to produce a
broadened, category-level version of a failed procurement search item.
Remove highly specific technical constraints (pressure ratings, material grades,
dimensional tolerances, standards certifications) while preserving the core
product category and primary material or form factor.
Return a JSON object: {"broadened_item": str, "kept_descriptions": [str]}.

USER:
Original item: "SS flanged ball valve, PN25, DN80, ASTM A351 CF8M"
Original descriptions: ["PN25", "DN80", "ASTM A351 CF8M", "stainless steel", "flanged"]
Status: NOT_FOUND after full semantic cache + MCP probe.
Produce the broadened form.
```

The response is schema-validated via `instructor` (same pattern as Stage 2) and used directly as the input to the broadened Stage 3 retry.

### C4. Why Claude for Spec-Degradation Reasoning

The Query Broadening task is semantically non-trivial and carries **asymmetric failure risk**:

- **Under-broadening:** Retaining too many specs produces the same `NOT_FOUND` — the retry adds latency with no benefit.
- **Over-broadening:** Dropping the core category (e.g., reducing `"DN80 ball valve"` to `"valve"`) produces a result set so wide it cannot form useful suggestions — AMBIGUOUS hits from unrelated valve types generate false confidence.

`qwen3:8b` reliably handles standard procurement extraction but shows brittleness on semantic *degradation* tasks — specifically, it tends to either over-specify (keep too many constraints) or lose the category anchor entirely. Claude's strength is in **instruction-following on reasoning chains with explicit constraints**, which maps precisely to this task:

1. Identify which description tokens are *differentiating specs* (pressure rating, size, material grade, standard) vs. *category anchors* (form factor, primary material, product type).
2. Strip differentiating specs while preserving anchors.
3. Return a well-formed, searchable item name at the category level.

The bounded prompt structure in [[#C3. The Query Broadening Subtask Prompt]] ensures Claude's output is schema-constrained — it cannot deviate into freeform text.

### C5. Cloud Fallback Cost Control

The Claude fallback is invoked **only on confirmed failure paths** (NOT_FOUND after MCP exhaustion, or local model retry exhaustion). It is never invoked on the happy path. Expected invocation rate: proportional to `not_found_rate` (target: <5% of all queries per [[36_Drift_Detection_Rules]]), meaning the per-token cloud cost is bounded to a small fraction of total query volume.

---

## Decision Flow — Production NOT_FOUND Path

```
Stage 3: status = NOT_FOUND (cache miss + MCP zero results)
     │
     ├──[B3] Log to unmet_demand_log (sync, lightweight)
     │
     ├──[B4] Claude: Query Broadening → broadened BecknIntent
     │         │
     │         ├── Broadened Stage 3 retry
     │         │     ├── VALIDATED / AMBIGUOUS → return broadened suggestions to buyer
     │         │     └── NOT_FOUND again → accept dead-end, skip RFQ
     │         │
     │         └── Still NOT_FOUND (no broadened match)
     │
     ├──[B2] Publish open RFQ to Beckn network (async Kafka)
     │
     └──[B1] Return NOT_FOUND + buyer_message + rfq_id to orchestrator
```

---

## Related Notes

- [[32_Orchestrator_Routing_Logic]] — Routing table that maps `NOT_FOUND` to this recovery path
- [[20_MCP_LLM_Reasoning_Loop]] — The MCP probe logic that precedes this failure state
- [[21_MCP_Bounding_Constraints]] — Why the MCP probe is bounded to ≤2 calls and 3s timeout
- [[12_Full_System_Validation_Flow]] — Full sequence diagram; this note extends the `NOT_FOUND` branch
- [[36_Drift_Detection_Rules]] — `not_found_rate >20%` drift rule powered by `unmet_demand_log`
- [[../Core_Logic/22_Accuracy_Target_Fallback_Policy|Accuracy Target and Fallback Policy]] — Hallucination and parse-failure fallback triggers (Triggers 1 & 2 from C2)
