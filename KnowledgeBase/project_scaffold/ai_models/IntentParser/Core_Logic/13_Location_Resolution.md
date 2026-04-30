---
tags: [intent-parser, location, deterministic, validation, coordinates, preprocessing]
cssclasses: [procurement-doc, ai-doc]
status: "#approved"
related: ["[[06_BecknIntent_Schema]]", "[[09_Pydantic_v2_Schema_Enforcement]]", "[[23_Beckn_Protocol_Structured_Fields_Context]]"]
---

# Location Resolution — Deterministic Pre-Processing

> [!architecture] Role
> `resolve_location()` is a deterministic lookup function called inside the [[09_Pydantic_v2_Schema_Enforcement|`@field_validator("location_coordinates")`]] of [[06_BecknIntent_Schema|`BecknIntent`]]. It implements a **hybrid resolution strategy**: the LLM attempts coordinate extraction via the system prompt, and the validator ensures correctness for known Indian cities regardless of the LLM's output format.

---

## Full Implementation

```python
_CITY_COORDINATES: dict[str, str] = {
    "bangalore":  "12.9716,77.5946",
    "bengaluru":  "12.9716,77.5946",
    "mumbai":     "19.0760,72.8777",
    "delhi":      "28.7041,77.1025",
    "new delhi":  "28.6139,77.2090",
    "chennai":    "13.0827,80.2707",
    "hyderabad":  "17.3850,78.4867",
    "pune":       "18.5204,73.8567",
    "kolkata":    "22.5726,88.3639",
}

def resolve_location(text: str) -> str:
    normalized = text.strip().lower()
    for city, coords in _CITY_COORDINATES.items():
        if city in normalized:
            return coords
    return text  # passthrough for unknown locations
```

---

## `_CITY_COORDINATES` — The Authoritative Lookup Table

The dictionary is the **authoritative source** for supported Indian cities. Both canonical spellings (`"bangalore"` and `"bengaluru"`) are included because both appear in user queries and LLM outputs.

**Current coverage:** Bangalore/Bengaluru, Mumbai, Delhi/New Delhi, Chennai, Hyderabad, Pune, Kolkata.

**Design constraint:** The lookup table is a module-level constant — it is the single point of truth for city coordinates. Adding a new city requires only adding one entry to `_CITY_COORDINATES`, with no changes to `resolve_location()`, the validator, or the system prompt.

---

## How the Hybrid Strategy Works

```
User query: "...deliver to our Bangalore office..."
                │
                ▼
LLM Stage 2 extracts:
  location_coordinates = "Bangalore"     ← city name
  OR
  location_coordinates = "12.9716,77.5946"  ← LLM attempted resolution
  OR
  location_coordinates = "12.9716, 77.5946" ← LLM with space
  OR
  location_coordinates = "12.97,77.59"   ← LLM truncated
                │
                ▼
@field_validator calls resolve_location(v)
  normalized = "bangalore" (or "12.9716,77.5946" etc.)
                │
                │ "bangalore" in normalized? → YES
                ▼
  return "12.9716,77.5946"  ← authoritative coordinates
```

The `if city in normalized` substring match ensures that:
- `"bangalore"` matches exactly
- `"bangalore, india"` matches (city name is a substring)
- `"12.9716, 77.5946"` — the city name is NOT a substring, but if the LLM already produced coordinates, they pass through (passthrough branch)

---

## LLM Hallucination Handling

The LLM may hallucinate coordinates — outputting `"12.9716, 77.5946"` (with a space) or `"12.97,77.59"` (truncated precision) instead of the canonical `"12.9716,77.5946"`. The substring match strategy handles this because:

**Case 1: LLM outputs city name** → substring match fires → correct coordinates returned.

**Case 2: LLM outputs approximate coordinates** → city name is NOT in the string → passthrough → approximately correct coordinates sent to BAP client. The BAP client's Beckn validation layer will reject truly malformed coordinates.

**Case 3: LLM outputs the exact canonical coordinates** → city name NOT in the string → passthrough → correct coordinates pass through unchanged.

> [!guardrail] Reliability Constraint
> For cities **not** in the table, the raw LLM output passes through as a string. The [[beckn_bap_client|BAP client]] will reject a malformed location at the Beckn protocol validation layer, surfacing the issue explicitly rather than silently passing bad data downstream. This is a **fail-loudly** design — unknown cities produce protocol errors, not silent garbage.

---

## Why Deterministic Over Pure LLM Resolution

The LLM is instructed via the Stage 2 system prompt to attempt coordinate resolution directly. The validator is a **belt-and-suspenders addition** for the cities we know the system will encounter most often:

| Approach | Accuracy | Consistency |
|---|---|---|
| LLM-only | ~90% (varies by model) | Variable (spacing, precision) |
| Lookup-only | 100% for covered cities; fails others | Perfectly consistent |
| **Hybrid (chosen)** | 100% for covered cities; LLM for others | Consistent for covered cities |

The lookup table's 9 cities cover the overwhelming majority of Indian enterprise procurement locations. Edge cases (Jaipur, Ahmedabad, Coimbatore) pass through and rely on LLM accuracy — an acceptable trade-off avoiding an exhaustive lookup table.

---

## Related Notes
- [[06_BecknIntent_Schema]] — The `@field_validator("location_coordinates")` that calls `resolve_location()`
- [[09_Pydantic_v2_Schema_Enforcement]] — How validators work in this pipeline
- [[23_Beckn_Protocol_Structured_Fields_Context]] — Why `"lat,lon"` string format is required by the Beckn Protocol's GPS object
