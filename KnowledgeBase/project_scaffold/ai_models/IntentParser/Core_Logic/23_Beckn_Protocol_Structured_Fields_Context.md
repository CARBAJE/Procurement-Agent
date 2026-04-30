---
tags: [intent-parser, beckn, protocol, structured-fields, anti-corruption-layer, location, timeline, budget]
cssclasses: [procurement-doc, ai-doc]
status: "#approved"
related: ["[[06_BecknIntent_Schema]]", "[[09_Pydantic_v2_Schema_Enforcement]]", "[[13_Location_Resolution]]", "[[03_Stage2_BecknIntentParser]]"]
---

# Beckn Protocol — Why Structured Procurement Fields Are Non-Negotiable

> [!info] Beckn Protocol Context
> The **Beckn Protocol** is a decentralized, open-specification commerce network designed so that any buyer application (BAP) can discover and transact with any seller application (BPP) without a central marketplace intermediary. Message exchange happens via standardized JSON payloads sent to protocol endpoints (`discover`, `publish`, `select`, `init`, `confirm`, `status`) — see [[beckn_bap_client]].

---

## Three Fields With Protocol-Enforced Types

The Beckn `discover` query requires structured, typed fields — not free-text strings. Three fields in [[06_BecknIntent_Schema|`BecknIntent`]] reflect non-negotiable Beckn Protocol type requirements:

### 1. `location_coordinates` — GPS Object (`"lat,lon"`)

**Protocol requirement:** The Beckn `discover` payload's `location` field is a `GPS` object, which is defined as a `"lat,lon"` string — for example, `"12.9716,77.5946"`. Free-text city names (`"Bangalore"`) are **not valid** in this position.

**Pipeline handling:**
- The LLM is instructed via system prompt to produce a coordinate string
- The [[13_Location_Resolution|`resolve_location()` function]] called inside the `apply_location_lookup` validator handles this transformation deterministically for known Indian cities
- Unknown locations pass through as raw strings — the [[beckn_bap_client|BAP client]] rejects malformed locations at the protocol validation layer

**Why this can't be deferred:** If the BAP client receives `"Bangalore"` where a GPS object is expected, the BPP returns a protocol error. All items in the BPP catalog — regardless of their actual location — are excluded from the response.

---

### 2. `delivery_timeline` — Numeric Duration in Hours

**Protocol requirement:** The Beckn delivery timeline is expressed as a numeric duration in hours. The protocol does not accept relative strings like `"5 days"`, `"by Friday"`, or `"ASAP"`.

**Pipeline handling:**
- Stage 2 system prompt provides explicit conversion rules: `1 day = 24h`, `1 week = 168h`
- The `@field_validator("delivery_timeline")` enforces `> 0` (physically impossible values trigger [[12_Retry_Mechanism_Validation_Feedback_Loop|instructor retry]])
- The LLM performs the conversion during extraction — the validator confirms correctness

**Why exact hours matter:** BPP fulfillment filtering uses the timeline as a constraint — BPPs that cannot deliver within the specified hours are excluded from `discover` results. A timeline of `"5 days"` as a string would cause a protocol parse error; a timeline of `0` would return no results (no BPP delivers in 0 hours).

---

### 3. `budget_constraints` — Numeric Range with `min` and `max`

**Protocol requirement:** The Beckn price filter is a numeric range. Currency symbols (`₹`, `INR`, `$`) are not valid; only float values.

**Pipeline handling:**
- Stage 2 system prompt rule: `"Use only numeric values, no currency symbols"`
- [[07_BudgetConstraints_Schema|`BudgetConstraints`]] nested model with `min: float` and `max: float`
- The LLM strips currency markers; Pydantic's type system rejects non-numeric strings

**Why a range, not a scalar:** Buyers often specify only an upper bound (`"under ₹2,000"`). The `BudgetConstraints(min=0.0, max=2000.0)` model handles this naturally — `min` defaults to `0.0`. A single `max_budget` field would require special-casing for two-sided budget queries.

---

## `BecknIntent` as an Anti-Corruption Layer

The [[06_BecknIntent_Schema|`BecknIntent`]] Pydantic schema, combined with [[09_Pydantic_v2_Schema_Enforcement|`@field_validator`]] and [[13_Location_Resolution|`resolve_location()`]], acts as an **anti-corruption layer** at the LLM output boundary:

```
LLM output (probabilistic, unstructured):
  "deliver to Bangalore office within 5 days, under ₹2,000 per unit"
                │
                ▼
BecknIntent schema enforcement:
  location_coordinates = "12.9716,77.5946"  ← deterministic validator
  delivery_timeline    = 120                 ← 5 days × 24
  budget_constraints   = {min: 0.0, max: 2000.0}  ← currency stripped
                │
                ▼
BAP Client output (deterministic, protocol-valid):
  POST /discover { location: {gps: "12.9716,77.5946"}, ...timeline: 120, ...price: {min: 0, max: 2000} }
```

Without `BecknIntent` enforcing these constraints at extraction time, every [[beckn_bap_client|BAP client]] call would require defensive transformation code — type checks, unit conversions, currency stripping — duplicated across every downstream service.

---

## Beckn Protocol Endpoints Context

For reference, the complete Beckn transaction flow:

| Endpoint | Direction | Purpose |
|---|---|---|
| `discover` | BAP → BPP | Find available items matching criteria |
| `publish` | BPP → BAP | BPP announces catalog availability |
| `select` | BAP → BPP | Select specific item from discovered results |
| `init` | BAP → BPP | Initialize order (collect terms) |
| `confirm` | BAP → BPP | Confirm and place order |
| `status` | BAP → BPP | Check order/delivery status |

The intent parsing pipeline feeds exclusively into `discover`. All other endpoints are handled by subsequent Lambda steps in the Step Functions state machine.

---

## Related Notes
- [[06_BecknIntent_Schema]] — The schema that enforces these Beckn-specific types
- [[09_Pydantic_v2_Schema_Enforcement]] — How `@field_validator` enforces the types at runtime
- [[13_Location_Resolution]] — `resolve_location()` for GPS coordinate enforcement
- [[07_BudgetConstraints_Schema]] — The `BudgetConstraints` nested model
- [[03_Stage2_BecknIntentParser]] — The stage that performs extraction with these constraints
