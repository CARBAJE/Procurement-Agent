---
tags: [intent-parser, fields, extraction, becknintent, structured-output, procurement]
cssclasses: [procurement-doc, ai-doc]
status: "#approved"
related: ["[[06_BecknIntent_Schema]]", "[[03_Stage2_BecknIntentParser]]", "[[20_Edge_Cases_Handled]]", "[[23_Beckn_Protocol_Structured_Fields_Context]]"]
---

# Fields Extracted by the Intent Parsing Pipeline

> [!architecture] Role
> This note documents all fields that the intent parsing pipeline extracts from the user's natural-language query. The extracted fields are the **semantic content** of `BecknIntent` — the Beckn-protocol-compatible JSON that drives all downstream procurement steps.

---

## Complete Field List

### Item Name and Technical Specifications
Extracted as two separate [[06_BecknIntent_Schema|`BecknIntent`]] fields:

- **`item`** — Concise, canonical product label used as the primary search key in the BPP `discover` query:
  - `"A4 paper"`, `"SS flanged valve"`, `"ergonomic office chair"`

- **`descriptions`** — Atomic technical specification tokens; each element is one spec component:
  - `["A4", "80gsm", "ISO certified"]`
  - `["SS316", "flanged", "2 inch", "ASME"]`
  - `["Intel Core i7", "16GB RAM", "512GB SSD", "FHD display"]`

---

### Quantity and Unit of Measure
- **`quantity: int`** — Numeric count. Unit of measure is implicit in the item name or `descriptions`:
  - `"500 units"` → `quantity=500`
  - `"200 reams"` → `quantity=200` (unit "reams" may appear in `descriptions`)
  - `"50 meters"` → `quantity=50` (unit "meters" may appear in `descriptions`)

---

### Delivery Location
- **`location_coordinates: str`** — Always resolved to `"lat,lon"` format by the [[13_Location_Resolution|`resolve_location()`]] validator:
  - `"Bangalore"` → `"12.9716,77.5946"`
  - `"Mumbai office"` → `"19.0760,72.8777"`
  - Unknown cities → passthrough (LLM output)

---

### Delivery Deadline
- **`delivery_timeline: int`** — Duration in **hours**, normalized from natural language:
  - `"within 5 days"` → `120`
  - `"next week"` → `168`
  - `"72 hours"` → `72`
  - Enforced `> 0` by `@field_validator`

---

### Budget Constraints
- **`budget_constraints: BudgetConstraints`** — Numeric price range (see [[07_BudgetConstraints_Schema]]):
  - `"under ₹2,000"` → `{min: 0.0, max: 2000.0}`
  - `"₹500 to ₹800"` → `{min: 500.0, max: 800.0}`
  - Currency symbols stripped; only float values stored

---

### Urgency Flag
- **Not a `BecknIntent` field** — detected by the [[02_Stage1_IntentClassifier|Stage 1 system prompt]] as a modifier on the intent, not a structural field.
- Detection: `"URGENT:"` prefix in the user query
- Effect: activates **emergency procurement mode** — shorter timelines, priority BPP matching
- Documented fully in [[story3_emergency_procurement|Story 3]]

---

### Government Compliance Flags
- **Not a `BecknIntent` field** — extracted as supplementary context when government procurement rules apply.
- **L1 mode**: Mandatory lowest-price selection, quality floor enforcement (minimum rating ≥ 4.0)
- **Quality floor**: `rating >= 4.0` constraint applied to all `DiscoverOffering` results
- Documented fully in [[story5_government_emarketplace|Story 5]]

---

## What Is NOT Extracted

The following are intentionally outside the extraction scope:

| Data | Reason Not Extracted |
|---|---|
| Delivery address (street-level) | Beckn Protocol uses GPS coordinates, not addresses |
| Supplier preference | Buyer applications (BAP) do not pre-select BPPs; discovery is open |
| Payment terms | Handled at the `init`/`confirm` transaction stage, not `discover` |
| Historical pricing | Not available at parse time; provided by BPP catalog |

---

## Related Notes
- [[06_BecknIntent_Schema]] — Full Pydantic definition of the extracted fields
- [[03_Stage2_BecknIntentParser]] — Stage that performs the extraction
- [[07_BudgetConstraints_Schema]] — `BudgetConstraints` nested model
- [[13_Location_Resolution]] — How location strings are resolved to coordinates
- [[20_Edge_Cases_Handled]] — Edge cases in field extraction (multi-location, urgency, government L1)
- [[23_Beckn_Protocol_Structured_Fields_Context]] — Why the Beckn Protocol requires exactly these field types
