---
tags: [intent-parser, edge-cases, emergency, multi-location, government, l1, specifications]
cssclasses: [procurement-doc, ai-doc]
status: "#approved"
related: ["[[19_Fields_Extracted]]", "[[03_Stage2_BecknIntentParser]]", "[[06_BecknIntent_Schema]]", "[[13_Location_Resolution]]"]
---

# Edge Cases Handled by the Intent Parsing Pipeline

> [!architecture] Role
> This note documents the four specific edge cases that the intent parsing pipeline has been designed and tested against. Each represents a real procurement scenario that exercises a non-trivial extraction path.

---

## Edge Case 1 — Multi-Location Delivery

**Source:** [[story3_emergency_procurement|Story 3]] — 4 hospital locations simultaneously.

**Query pattern:**
```
"URGENT: 500 N95 respirator masks each to Bangalore General Hospital, 
Mumbai Breach Candy Hospital, Chennai Apollo, and Delhi AIIMS within 6 hours"
```

**Extraction challenge:**
- Four distinct delivery locations, each requiring a `"lat,lon"` coordinate
- Single `location_coordinates: str` field cannot natively hold multiple values

**Handling:**
The current [[06_BecknIntent_Schema|`BecknIntent`]] schema holds a single `location_coordinates`. Multi-location queries cause the LLM to extract the first location or the "primary" location. This is a known limitation. The emergency procurement mode (triggered by the `"URGENT:"` prefix) dispatches separate pipeline invocations per location at the orchestrator level.

**Implication for evaluation:** Multi-location queries in the [[21_Evaluation_Methodology|test set]] are evaluated for correct extraction of at least one valid location coordinate, and for correct urgency flag detection.

---

## Edge Case 2 — Complex Technical Specifications

**Source:** [[story2_high_value_it_equipment|Story 2]] — 200 laptops with detailed hardware requirements.

**Query pattern:**
```
"200 laptops: Intel Core i7-12th gen, 16GB DDR5 RAM, 512GB NVMe SSD, 
15.6 FHD display, Windows 11 Pro, Thunderbolt 4, fingerprint reader, 
backlit keyboard, ≥8hr battery — deliver to Pune office by next Friday"
```

**Extraction challenge:**
- 9 distinct technical specification tokens to decompose into `descriptions: list[str]`
- Complex delivery timeline (`"next Friday"` → hours from current date)
- No budget specified → `BudgetConstraints(min=0.0, max=float('inf'))`

**Handling:**
- `descriptions` decomposition: `["Intel Core i7 12th gen", "16GB DDR5 RAM", "512GB NVMe SSD", "15.6 FHD", "Windows 11 Pro", "Thunderbolt 4", "fingerprint reader", "backlit keyboard", "8hr+ battery"]`
- `"next Friday"` timeline: the Stage 2 system prompt handles relative dates by instructing the LLM to use 5 days (Mon-Fri) as a proxy → `120h`. Exact date resolution is deferred to the BAP client layer.
- Complex technical queries route to [[10_Heuristic_Complexity_Router|`qwen3:8b` / `gpt-4o`]] via the length signal (`len > 120`).

---

## Edge Case 3 — Government L1 Procurement Constraints

**Source:** [[story5_government_emarketplace|Story 5]] — quality floor ≥ 4.0 rating, L1 mandatory.

**Query pattern:**
```
"Government tender: 1000 office chairs, ergonomic, lumbar support, 
5-wheel base, BIFMA certified — quality floor minimum 4.0 stars, 
L1 selection mandatory, deliver to New Delhi secretariat within 15 days"
```

**Extraction challenge:**
- `"L1 mandatory"` → government procurement rule requiring lowest-cost selection
- `"quality floor minimum 4.0"` → rating constraint applied at comparison stage
- `"government tender"` → triggers compliance-specific routing

**Handling:**
The [[02_Stage1_IntentClassifier|Stage 1 system prompt]] includes context about government procurement workflows. The `"L1"` and `"quality floor"` signals may be extracted as items in `descriptions` (e.g., `["L1 mandatory", "BIFMA certified", "4.0+ rating"]`) or returned as supplementary fields. The [[comparison_scoring_engine|Comparison Engine]] applies L1 and quality floor constraints at scoring time.

**Note:** L1 and quality floor are not native `BecknIntent` fields — they are domain-specific modifiers that require schema extension for full first-class support.

---

## Edge Case 4 — Emergency Urgency Detection

**Source:** [[story3_emergency_procurement|Story 3]] — `"URGENT:"` triggers emergency procurement mode.

**Query pattern:**
```
"URGENT: 200 oxygen concentrators, 93% purity, 5L/min flow rate, 
Bangalore and Mumbai hospitals, within 3 hours"
```

**Extraction challenge:**
- `"URGENT:"` prefix is a protocol signal, not a product specification
- `"3 hours"` delivery timeline is extremely short — BPP availability and logistics may differ
- Multi-location (2 hospitals) — see Edge Case 1

**Handling:**
- `"URGENT:"` is detected at Stage 1 by the classifier system prompt, which includes examples of emergency queries
- The `intent` field is set to `"SearchProduct"` (or `"RequestQuote"` if quoting is implied) with an urgency qualifier in the `reasoning` field
- The `delivery_timeline` is set to `3` (hours) — the [[09_Pydantic_v2_Schema_Enforcement|`timeline_positive` validator]] confirms `> 0`
- Emergency mode activation (priority BPP selection, alternative sourcing) is handled at the orchestrator level, outside the intent parser scope

---

## Related Notes
- [[19_Fields_Extracted]] — Normal field extraction; edge cases are deviations from this baseline
- [[03_Stage2_BecknIntentParser]] — The extraction stage where most edge case handling occurs
- [[13_Location_Resolution]] — Multi-location and coordinate resolution
- [[21_Evaluation_Methodology]] — How edge cases are represented in the test set (100 requests × 15 categories)
