---
tags: [bpp-validation, architecture, intent-parser, beckn]
cssclasses: [procurement-doc, ai-doc]
status: "#approved"
related: ["[[01_Silent_Semantic_Gap]]", "[[03_Double_Discover_Anti_Pattern]]"]
---

# Item Field Failure Modes

## Definition of `BecknIntent.item`

`BecknIntent.item` is a short, free-text label. The LLM extracts it from natural language and the label drives the BPP full-text or attribute search. Two failure modes exist.

---

## Failure Mode 1 — Over-Specification (Hallucination of Specificity)

The LLM extracts a label that is more specific than what the BPP catalog contains, causing a string mismatch on the BPP side.

```
User says:       "stainless 316L flanged valve 2 inch ASME"
LLM extracts:    item = "stainless 316L flanged valve 2 inch ASME"
BPP catalog has: "SS316 flange valve 2in"
Result:          String mismatch → zero offerings
```

The LLM faithfully reproduces the user's terminology, but the BPP catalog uses a different canonical naming convention. Despite referring to the exact same physical component, there is zero lexical overlap sufficient to produce a match.

---

## Failure Mode 2 — Under-Specification (Over-Generic Extraction)

The LLM extracts a label that is too generic, causing the BPP search to return results that are correct but polluted with irrelevant variants.

```
User says:       "200 ergonomic office chairs with lumbar support"
LLM extracts:    item = "chair"
BPP catalog has: 847 items matching "chair"
Result:          Correct results polluted with irrelevant variants
```

The truncation discards the differentiating attributes (ergonomic, lumbar support) that the user actually cares about. The procurement system cannot distinguish the intended product class from the entire chair category.

---

## Invisibility of Both Modes

Both failure modes are invisible until Lambda 2 completes. `BecknIntent` is structurally valid in both cases — Pydantic schema validation passes, the item field is a non-empty string, and the object routes to Lambda 2 without any error signal. See [[01_Silent_Semantic_Gap]] for the pipeline context.

---

## Related Notes

- [[01_Silent_Semantic_Gap]] — Pipeline structure and why the failure is silent
- [[03_Double_Discover_Anti_Pattern]] — First naive approach to solve this problem (rejected)
