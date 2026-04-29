---
tags: [bpp-validation, architecture, beckn, intent-parser]
cssclasses: [procurement-doc, ai-doc]
status: "#approved"
related: ["[[02_Item_Field_Failure_Modes]]", "[[07_Hybrid_Architecture_Overview]]"]
---

# The Silent Semantic Gap

## Where the Validation Gap Lives

The current procurement pipeline is a strict linear chain of Lambdas orchestrated by Step Functions. Lambda 1 extracts the `item` field from the user's query using a two-stage LLM pipeline. This extraction is purely semantic — the LLM identifies *what the user wants* but has no knowledge of *what the BPP network actually carries*.

```
User Query (NL)
      │
      ▼
┌─────────────────────────────────────────────────────────┐
│  Lambda 1: IntentParser  (port 8001)                    │
│  ─────────────────────────────────────────────────────  │
│  Stage 1 │ IntentClassifier → ParsedIntent              │
│          │ Guard: intent ∉ {SearchProduct, RequestQuote,│
│          │        PurchaseOrder} → abort pipeline       │
│          ▼                                              │
│  Stage 2 │ BecknIntentParser → BecknIntent              │
│          │ { item, descriptions, quantity, location,    │
│          │   delivery_timeline, budget_constraints }    │
│          │                                              │
│  ⚠ GAP  │ item field is NOT validated against BPP      │
└─────────────────────────────────────────────────────────┘
      │
      │  BecknIntent (item may not exist in any BPP)
      ▼
┌─────────────────────────────────────────────────────────┐
│  Lambda 2: BecknBAP Client  (port 8002)                 │
│  POST /discover → ONIX (8081) → BPP Network             │
│  Awaits on_discover callback  (CALLBACK_TIMEOUT: 10s)   │
│  Returns: DiscoverOffering[]                            │
│                                                         │
│  ⚠ SILENT FAILURE: zero offerings = no signal          │
└─────────────────────────────────────────────────────────┘
      │
      ▼
┌─────────────────────────────────────────────────────────┐
│  Lambda 3: Comparative Scoring  (port 8003)             │
└─────────────────────────────────────────────────────────┘
```

The failure is **semantic, not syntactic**: the `BecknIntent` is structurally valid Pydantic output, passes all schema validators, and reaches Lambda 2 cleanly. The failure surfaces only after the full 10-second BPP round-trip, when the user discovers the pipeline produced nothing useful.

## Silent Failure: Zero Offerings Gives No Error Signal

Zero offerings returned from Lambda 2 produces **no error signal**. The pipeline completes successfully from a schema and protocol standpoint. There is no exception, no validation error, and no timeout. The structural validity of `BecknIntent` as Pydantic output means every downstream check passes — the mismatch exists purely in the semantic space between the user's terminology and the BPP catalog's naming conventions.

The failure mode is therefore invisible until Lambda 2 completes its full 10-second async round-trip (BAP → ONIX → BPP → `on_discover` callback → `CallbackCollector` queue).

---

## Related Notes

- [[02_Item_Field_Failure_Modes]] — The two specific failure modes (over-specification, under-specification) that produce the gap
- [[07_Hybrid_Architecture_Overview]] — The approved Stage 3 solution that closes this gap
