---
tags: [component, normalizer, catalog, beckn, microservice, lambda-2, schema-mapping, llm-fallback, format-detection]
cssclasses: [procurement-doc, component-doc]
status: "#implemented"
related: ["[[beckn_bap_client]]", "[[microservices_architecture]]", "[[comparison_scoring_engine]]", "[[agent_framework_langchain_langgraph]]", "[[phase2_core_intelligence_transaction_flow]]"]
---

# Component: Catalog Normalizer

> [!architecture] Role in the System
> The Catalog Normalizer transforms **heterogeneous BPP catalog payloads** from `on_discover` callbacks into a unified `DiscoverOffering` schema consumable by the [[comparison_scoring_engine|Comparison Engine]]. It replaces the `_parse_on_discover()` method previously embedded in `BecknClient`, which only handled 2 of 5+ possible BPP response formats.

## Architecture: 3-Step Pipeline

```
Payload raw on_discover (dict)
        │
        ▼
Step 1 — FormatDetector.detect(catalog) → FormatVariant (1–5)
        │
        ├── Variant 1–4 → SchemaMapper.map(catalog, variant, bpp_id, bpp_uri)
        │      (deterministic, covers 80%+ of cases, no LLM needed)
        │
        └── Variant 5 (UNKNOWN) → LLMFallbackNormalizer.normalize(catalog, bpp_id, bpp_uri)
               instructor + Ollama qwen3:1.7b — same pattern as IntentParser/core.py
        │
        ▼
Step 2 — Pydantic v2 validation (applied automatically by DiscoverOffering)
        │
        ▼
list[DiscoverOffering] → returned to client.py → DiscoverResponse
```

## Supported Format Variants

| Variant | Enum Value | Description | Detection Predicate | Mapping Method |
|---|---|---|---|---|
| `BECKN_V2_FLAT_RESOURCES` | 1 | `resources[]` in catalog root (real Beckn v2 Catalog Service) | `isinstance(c.get("resources"), list) and len > 0` | `_map_v2_flat_resources` |
| `ONDC_CATALOG` | 4 | Has `fulfillments[]` + `tags[]` (ONDC-specific fields) | `"fulfillments" in c and "tags" in c` | `_map_ondc` |
| `LEGACY_PROVIDERS_ITEMS` | 2 | `providers[].items[]` (mock_onix / legacy format) | `isinstance(c.get("providers"), list) and any("items" in p ...)` | `_map_legacy_providers` |
| `BPP_CATALOG_V1` | 3 | `items[]` with `provider` as string ID | `isinstance(c.get("items"), list) and isinstance(items[0]["provider"], str)` | `_map_bpp_v1` |
| `UNKNOWN` | 5 | No fingerprint matched | — (fallback) | LLM Fallback |

> [!note] Detection Order
> ONDC_CATALOG (variant 4) is checked **before** LEGACY_PROVIDERS_ITEMS (variant 2) because ONDC catalogs also contain `providers[].items[]`. The more specific fingerprint must match first.

## Format Detection Strategy

`FormatDetector.detect()` iterates `FINGERPRINT_RULES` — an ordered list of `(FormatVariant, predicate)` pairs — and returns the **first match**. This makes detection O(n) where n is the number of known formats (currently 4), with zero IO and zero LLM calls.

```python
FINGERPRINT_RULES = [
    (FormatVariant.BECKN_V2_FLAT_RESOURCES, _has_resources),
    (FormatVariant.ONDC_CATALOG, _has_fulfillments_and_tags),   # ← before legacy
    (FormatVariant.LEGACY_PROVIDERS_ITEMS, _has_providers_items),
    (FormatVariant.BPP_CATALOG_V1, _has_items_with_string_provider),
]
```

**Why "first match wins":** O(1) amortized for the common cases (Formats A and B represent 80%+ of real traffic), requires no scoring or confidence weighting, and makes detection deterministic and trivially testable.

## LLM Fallback

Activated only when `FormatVariant.UNKNOWN` is returned (no fingerprint matched).

- **Model:** `NORMALIZER_MODEL` env var, default `qwen3:1.7b`
- **Client:** `instructor.from_openai(OpenAI(base_url=OLLAMA_URL, api_key="ollama"), mode=instructor.Mode.JSON)`
- **Pattern:** Identical to `IntentParser/core.py` — same `instructor` + Ollama setup for consistency across the project.
- **Schema:** `NormalizedCatalog(offerings: list[RawOffering])` where `RawOffering` has all `DiscoverOffering` fields as optional with safe defaults.
- **Retry:** `max_retries=3`
- **Error handling:** Any exception → logs warning, returns `[]`. **Never propagates exceptions.** The LangGraph graph handles `offerings=[]` gracefully (routes directly to `present_results`).

## Integration with the System

### How it replaces `_parse_on_discover()`

`client.py` previously embedded the parsing logic inside `BecknClient`. After Phase 2:

1. `_parse_on_discover()` is **removed** from `BecknClient`.
2. A module-level singleton `_normalizer = CatalogNormalizer()` is created in `client.py`.
3. `_build_discover_response()` calls `_normalizer.normalize({"message": {"catalog": catalog}}, bpp_id, bpp_uri)` for each catalog in the callback.

### LangGraph graph — unchanged

`CatalogNormalizer` is transparent to the LangGraph nodes. The `discover_node` still receives a `DiscoverResponse` with `offerings: list[DiscoverOffering]`. No changes to `graph.py`, `nodes.py`, or `state.py`.

### Module structure

```
src/normalizer/
├── __init__.py         # exports CatalogNormalizer only
├── formats.py          # FormatVariant enum + FINGERPRINT_RULES
├── detector.py         # FormatDetector — pure function, no IO
├── schema_mapper.py    # SchemaMapper — deterministic mappers for variants 1–4
├── llm_fallback.py     # LLMFallbackNormalizer — instructor + Ollama
└── normalizer.py       # CatalogNormalizer — public facade
```

## Acceptance Criteria — Phase 2

- [x] Handles 5+ BPP catalog formats (4 deterministic + 1 LLM fallback for unknowns)
- [x] Format A (`resources[]`) and Format B (`providers[].items[]`) behavior is **identical** to the previous `_parse_on_discover()` — moved verbatim, no regressions
- [x] 17 unit tests in `tests/test_normalizer.py` — all pass without Ollama running
- [x] Existing tests (`test_discover.py`, `test_agent.py`) continue passing without changes
- [x] LLM fallback returns `[]` on error — never raises
- [x] `BecknClient` is a thin HTTP layer — no format-detection logic remains inside it

## Testing Guide

All tests run **without Ollama** and **without Docker**. Every example below shows the exact input going in and the exact output expected to come out.

Prerequisites:

```bash
cd Procurement-Agent/Bap-1
# Verify the environment works before running individual tests
pytest tests/test_normalizer.py -v --tb=short
# Expected: 17 passed
```

---

### Test 1 — Format A detection (`BECKN_V2_FLAT_RESOURCES`)

**What it proves:** a catalog whose root contains `resources[]` is identified as variant 1.

**Input going into `FormatDetector.detect()`:**
```json
{
  "resources": [
    {
      "id": "item-1",
      "descriptor": { "name": "A4 Paper" },
      "provider": { "id": "prov-1", "descriptor": { "name": "OfficeWorld" } },
      "price": { "value": 195.0, "currency": "INR" },
      "rating": { "ratingValue": "4.8" }
    }
  ]
}
```

**Expected output:** `FormatVariant.BECKN_V2_FLAT_RESOURCES` (integer value `1`)

**Run it:**
```bash
pytest tests/test_normalizer.py::test_detect_format_a -v
```

**Expected terminal output:**
```
tests/test_normalizer.py::test_detect_format_a PASSED
```

---

### Test 2 — Format A mapping — full field extraction

**What it proves:** given a Format A catalog, `SchemaMapper` extracts all fields correctly into a `DiscoverOffering`.

**Input:** same JSON as Test 1 above, plus `bpp_id="test-bpp"` and `bpp_uri="http://test-bpp.example"`.

**Expected output — the resulting `DiscoverOffering` object:**
```
bpp_id          = "test-bpp"
bpp_uri         = "http://test-bpp.example"
provider_id     = "prov-1"
provider_name   = "OfficeWorld"
item_id         = "item-1"
item_name       = "A4 Paper"
price_value     = "195.0"
price_currency  = "INR"
rating          = "4.8"
```

**Run it:**
```bash
pytest tests/test_normalizer.py::test_map_v2_flat_resources -v
```

**Expected terminal output:**
```
tests/test_normalizer.py::test_map_v2_flat_resources PASSED
```

---

### Test 3 — Format B detection (`LEGACY_PROVIDERS_ITEMS`)

**What it proves:** a catalog structured as `providers[].items[]` is identified as variant 2.

**Input going into `FormatDetector.detect()`:**
```json
{
  "providers": [
    {
      "id": "prov-2",
      "descriptor": { "name": "PaperDirect" },
      "rating": "4.5",
      "items": [
        {
          "id": "item-2",
          "descriptor": { "name": "A4 Paper Ream" },
          "price": { "value": 189.0, "currency": "INR" }
        }
      ]
    }
  ]
}
```

**Expected output:** `FormatVariant.LEGACY_PROVIDERS_ITEMS` (integer value `2`)

**Run it:**
```bash
pytest tests/test_normalizer.py::test_detect_format_b -v
```

---

### Test 4 — Format B mapping — rating lives on the provider, not the item

**What it proves:** in Format B the rating comes from the provider object, not from inside each item. The mapper must read it from the right place.

**Input:** same JSON as Test 3. Notice `"rating": "4.5"` is at provider level, not inside `items[]`.

**Expected output — the resulting `DiscoverOffering`:**
```
provider_id    = "prov-2"
provider_name  = "PaperDirect"
item_id        = "item-2"
item_name      = "A4 Paper Ream"
price_value    = "189.0"
rating         = "4.5"          ← taken from provider, not from item
```

**Run it:**
```bash
pytest tests/test_normalizer.py::test_map_legacy_providers -v
```

---

### Test 5 — Format C detection (`BPP_CATALOG_V1`)

**What it proves:** a catalog with flat `items[]` where `provider` is a plain string (not an object) is identified as variant 3.

**Input going into `FormatDetector.detect()`:**
```json
{
  "items": [
    {
      "id": "item-3",
      "provider": "prov-3",
      "descriptor": { "name": "Bulk A4" },
      "price": { "value": 170.0, "currency": "INR" }
    }
  ]
}
```

**Key difference from Format B:** `"provider"` is the string `"prov-3"`, not an object with `id` and `descriptor`.

**Expected output:** `FormatVariant.BPP_CATALOG_V1` (integer value `3`)

**Run it:**
```bash
pytest tests/test_normalizer.py::test_detect_format_c -v
```

---

### Test 6 — Format C mapping — provider string becomes both ID and name

**What it proves:** because Format C has no provider name (only a string ID), the mapper uses that string as both `provider_id` and `provider_name`.

**Expected output:**
```
provider_id    = "prov-3"
provider_name  = "prov-3"   ← same value, no name available in this format
item_id        = "item-3"
item_name      = "Bulk A4"
price_value    = "170.0"
rating         = None        ← Format C has no rating field
```

**Run it:**
```bash
pytest tests/test_normalizer.py::test_map_bpp_v1 -v
```

---

### Test 7 — Format D detection (`ONDC_CATALOG`)

**What it proves:** a catalog that has both `fulfillments[]` AND `tags[]` at the root is identified as variant 4 — even though it also has `providers[].items[]` (which would match Format B if checked first).

**Input going into `FormatDetector.detect()`:**
```json
{
  "fulfillments": [{ "id": "ff-1", "TAT": "P1D" }],
  "tags": [{ "code": "category", "value": "stationery" }],
  "providers": [
    {
      "id": "prov-4",
      "descriptor": { "name": "QuickShip" },
      "items": [
        {
          "id": "item-4",
          "descriptor": { "name": "A4 Express" },
          "price": { "value": 210.0, "currency": "INR" },
          "fulfillment_ids": ["ff-1"]
        }
      ]
    }
  ]
}
```

**Expected output:** `FormatVariant.ONDC_CATALOG` (integer value `4`) — **not** `LEGACY_PROVIDERS_ITEMS`.

**Run it:**
```bash
pytest tests/test_normalizer.py::test_detect_format_d -v
```

---

### Test 8 — Format D mapping — delivery time resolved from `fulfillment_ids`

**What it proves:** the ONDC mapper cross-references the item's `fulfillment_ids` list against the `fulfillments[]` catalog to compute the delivery time in hours.

**How the cross-reference works:**
```
fulfillments[0].id  = "ff-1"
fulfillments[0].TAT = "P1D"   →   _iso_duration_to_hours("P1D") = 24

item.fulfillment_ids = ["ff-1"]   →   lookup "ff-1" in map   →   24 hours
```

**Expected output — the resulting `DiscoverOffering`:**
```
item_id           = "item-4"
item_name         = "A4 Express"
provider_name     = "QuickShip"
price_value       = "210.0"
fulfillment_hours = 24          ← resolved from "P1D" via the lookup table
```

**Run it:**
```bash
pytest tests/test_normalizer.py::test_map_ondc_duration_conversion -v
```

---

### Test 9 — ISO 8601 duration conversion

**What it proves:** the helper `_iso_duration_to_hours()` correctly converts the three duration formats that BPPs use.

| Input string | What it means | Expected hours |
|---|---|---|
| `"P1D"` | 1 day | `24` |
| `"PT2H"` | 2 hours | `2` |
| `"P2DT6H"` | 2 days + 6 hours | `54` |

**Run all three:**
```bash
pytest tests/test_normalizer.py -v -k "iso_duration"
```

**Expected terminal output:**
```
tests/test_normalizer.py::test_iso_duration_p1d    PASSED   (P1D  → 24)
tests/test_normalizer.py::test_iso_duration_pt2h   PASSED   (PT2H → 2)
tests/test_normalizer.py::test_iso_duration_p2dt6h PASSED   (P2DT6H → 54)
```

---

### Test 10 — Unknown format detection

**What it proves:** when none of the 4 fingerprints match, the detector returns `UNKNOWN`, which routes the catalog to the LLM fallback.

**Input going into `FormatDetector.detect()`:**
```json
{
  "something_weird": true,
  "no_known_keys": []
}
```

This JSON has no `resources`, no `providers`, no `items`, no `fulfillments+tags` — nothing recognizable.

**Expected output:** `FormatVariant.UNKNOWN` (integer value `5`)

**Run it:**
```bash
pytest tests/test_normalizer.py::test_detect_unknown -v
```

---

### Test 11 — LLM fallback: returns structured output when model responds correctly

**What it proves:** when `UNKNOWN` is detected, the LLM path is called, and if the model returns valid JSON, it is converted to a `DiscoverOffering` list. The model is mocked — no Ollama needed.

**What the mock simulates:** the LLM returning this structured extraction:
```json
{
  "offerings": [
    {
      "item_id": "llm-1",
      "item_name": "LLM Item",
      "provider_id": "llm-prov",
      "provider_name": "LLM Provider",
      "price_value": "99.0",
      "price_currency": "INR"
    }
  ]
}
```

**Expected output — the resulting `DiscoverOffering`:**
```
item_id       = "llm-1"
item_name     = "LLM Item"
provider_id   = "llm-prov"
provider_name = "LLM Provider"
price_value   = "99.0"
bpp_id        = "test-bpp"    ← injected by the normalizer, not from the LLM
```

**Run it:**
```bash
pytest tests/test_normalizer.py::test_llm_fallback_mocked -v
```

---

### Test 12 — LLM fallback: returns `[]` silently when the model fails

**What it proves:** if Ollama is down, the model times out, or it returns malformed JSON after 3 retries — the normalizer returns an empty list and logs a warning instead of crashing the agent.

**What the mock simulates:** the LLM call raising `RuntimeError("Ollama unavailable")`.

**Expected output:** `[]` — no exception propagated, agent continues normally.

**Run it:**
```bash
pytest tests/test_normalizer.py::test_llm_fallback_returns_empty_on_error -v
```

---

### Test 13 — `CatalogNormalizer` routes to mapper for known formats

**What it proves:** when the full facade receives a Format A payload, it calls `SchemaMapper` and does **not** call the LLM — even though LLM is available.

**Input payload (as it arrives from the Beckn callback):**
```json
{
  "message": {
    "catalog": {
      "resources": [
        {
          "id": "item-1",
          "descriptor": { "name": "A4 Paper" },
          "provider": { "id": "prov-1", "descriptor": { "name": "OfficeWorld" } },
          "price": { "value": 195.0, "currency": "INR" },
          "rating": { "ratingValue": "4.8" }
        }
      ]
    }
  }
}
```

**Expected behavior:**
- `SchemaMapper.map()` is called exactly once
- `LLMFallbackNormalizer.normalize()` is called zero times
- Result has 1 offering

**Run it:**
```bash
pytest tests/test_normalizer.py::test_normalizer_routes_to_mapper_on_known -v
```

---

### Test 14 — `CatalogNormalizer` routes to LLM for unknown formats

**What it proves:** when the full facade receives an unrecognized catalog, it skips the mapper entirely and calls the LLM fallback.

**Input payload:**
```json
{
  "message": {
    "catalog": {
      "something_weird": true,
      "no_known_keys": []
    }
  }
}
```

**Expected behavior:**
- `SchemaMapper.map()` is called zero times
- `LLMFallbackNormalizer.normalize()` is called exactly once
- Result is `[]` (because the mock returns empty)

**Run it:**
```bash
pytest tests/test_normalizer.py::test_normalizer_routes_to_llm_on_unknown -v
```

---

### Test 15 — Full client integration with Format A

**What it proves:** the complete path `_build_discover_response()` → `CatalogNormalizer.normalize()` → `DiscoverOffering` works end to end inside `BecknClient`, without a real HTTP server.

**What the test simulates:**
1. A fake `on_discover` callback arrives with a Format A catalog
2. The callback is placed directly into the `CallbackCollector` queue
3. `_build_discover_response()` is called with that callback
4. The result is a proper `DiscoverResponse`

**Expected output:**
```
response.offerings[0].item_name = "A4 Paper"
response.offerings[0].bpp_id   = "test-bpp"
len(response.offerings)         = 1
```

**Run it:**
```bash
pytest tests/test_normalizer.py::test_client_uses_normalizer -v
```

---

### Run the full suite and check for regressions

After all individual tests pass, verify nothing broke in the rest of the project:

```bash
# Full test suite — all 77 tests
pytest tests/ -v

# Expected summary:
# 17 normalizer tests  +  60 pre-existing tests  =  77 passed, 0 failed
```

---

### Testing the real LLM fallback with Ollama running

> [!warning] This requires Ollama running locally with `qwen3:1.7b` pulled. The unit tests above do **not** require this — they mock the LLM call.

```bash
# 1. Pull the model if not already available
ollama pull qwen3:1.7b

# 2. Verify Ollama is responding
curl http://localhost:11434/v1/models

# 3. Run the agent with a normal query — the real Beckn network returns Format A or B
#    and the normalizer handles them deterministically (no LLM activated)
python run.py "500 A4 paper Bangalore 3 days"

# 4. To force the LLM fallback path, open a Python shell and call it directly
#    with a catalog structure that matches none of the 4 fingerprints:
python -c "
from src.normalizer.llm_fallback import LLMFallbackNormalizer

fallback = LLMFallbackNormalizer()
unknown_catalog = {
    'catalog_data': {
        'product_list': [
            {'sku': 'A4-001', 'vendor': 'ABC Corp', 'unit_price': 180, 'currency': 'INR'}
        ]
    }
}
result = fallback.normalize(unknown_catalog, 'test-bpp', 'http://test.example')
print(f'Offerings found: {len(result)}')
for o in result:
    print(f'  {o.item_name} — {o.price_value} {o.price_currency} from {o.provider_name}')
"
```

> [!note] The LLM fallback is never activated by the 17 unit tests above — those all mock the LLM call. It only activates in production when a BPP returns a catalog structure that matches none of the 4 known fingerprints.

## References

- [[beckn_bap_client]] — the HTTP client that delegates to this normalizer
- [[comparison_scoring_engine]] — consumes `list[DiscoverOffering]` produced here
- [[agent_framework_langchain_langgraph]] — LangGraph graph unchanged by this component
- [[phase2_core_intelligence_transaction_flow]] — milestone that delivered this component
