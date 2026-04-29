---
tags: [intent-parser, domain-gating, procurement, routing, short-circuit]
cssclasses: [procurement-doc, ai-doc]
status: "#approved"
related: ["[[02_Stage1_IntentClassifier]]", "[[01_Two_Stage_Pipeline_Overview]]", "[[05_ParsedIntent_Schema]]"]
---

# Domain Gating — Procurement Intent Filter

> [!architecture] Role
> The domain gate is the decision point between Stage 1 and Stage 2. It prevents Stage 2 from being invoked on non-procurement queries — ensuring that Beckn field extraction is never attempted on input that would produce incomplete or nonsensical payloads.

---

## The `_PROCUREMENT_INTENTS` Set

```python
_PROCUREMENT_INTENTS = {"SearchProduct", "RequestQuote", "PurchaseOrder"}
```

After [[02_Stage1_IntentClassifier|Stage 1]] produces a [[05_ParsedIntent_Schema|`ParsedIntent`]], the pipeline evaluates:

```python
if parsed_intent.intent not in _PROCUREMENT_INTENTS:
    return {"intent": parsed_intent.intent, "beckn_intent": None}
```

If the intent is **not** in this set, the pipeline **short-circuits immediately**:
- `beckn_intent` is returned as `null`
- Stage 2 (`BecknIntentParser`) is **never invoked**
- The routing heuristic is **never evaluated**
- No additional LLM calls are made

---

## Why Three Intents?

| Intent | Meaning | Beckn action triggered |
|---|---|---|
| `SearchProduct` | User wants to find and compare available items | `POST /discover` → `DiscoverOffering[]` |
| `RequestQuote` | User wants pricing for a specific specification | `POST /discover` with quote context |
| `PurchaseOrder` | User wants to place an order directly | Full transaction flow: select → init → confirm |

All three intents require a `BecknIntent` payload with location, quantity, timeline, and budget to proceed through the [[beckn_bap_client|BAP client pipeline]].

---

## What Short-Circuits

Queries that return `beckn_intent: null` include any intent the LLM synthesizes outside the three procurement labels. Examples from production observation:

| Synthesized Intent | Query Example |
|---|---|
| `"Greeting"` | "Hello, can you help me?" |
| `"CancelOrder"` | "I want to cancel my order #4521" |
| `"TrackOrder"` | "Where is my delivery from last Tuesday?" |
| `"SupportRequest"` | "The invoice was wrong, can you fix it?" |
| `"PriceInquiry"` | "What is the current market price for copper wire?" (no purchase intent) |

These queries are **valid user inputs** — they are not errors. The domain gate routes them out cleanly so a separate workflow (order management, support, pricing lookup) can handle them.

---

## Why Open Vocabulary Requires This Gate

Because [[02_Stage1_IntentClassifier|Stage 1]] uses `intent: str` (open-ended) rather than a `Literal` enum, the LLM can synthesize any PascalCase label. The `_PROCUREMENT_INTENTS` membership check is the explicit filter that separates procurement queries from everything else.

If Stage 1 used a closed enum (`Literal["SearchProduct", "RequestQuote", "PurchaseOrder"]`), this gate would be implicit (the LLM could never return anything outside the enum). The open-vocabulary design trades the closed-enum guard for this explicit check — and gains the ability to handle unanticipated intents gracefully without a redeployment.

---

## Gate Failure Modes

The domain gate has **no failure modes** — it is a simple set membership test in application code. The only risk is a false negative: the LLM synthesizing `"BuyProduct"` instead of `"PurchaseOrder"` for a clear purchase request. This is mitigated by:

1. Few-shot examples in the Stage 1 prompt that demonstrate canonical PascalCase labels for procurement queries
2. Weekly evaluation runs that catch label drift — see [[21_Evaluation_Methodology]]

---

## Related Notes
- [[02_Stage1_IntentClassifier]] — Produces the `intent` string that this gate evaluates
- [[05_ParsedIntent_Schema]] — `ParsedIntent.intent` field definition
- [[01_Two_Stage_Pipeline_Overview]] — Full pipeline diagram showing gate position
