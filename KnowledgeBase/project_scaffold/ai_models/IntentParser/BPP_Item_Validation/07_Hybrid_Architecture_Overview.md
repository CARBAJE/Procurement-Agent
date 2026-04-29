---
tags: [bpp-validation, architecture, intent-parser, semantic-cache, mcp, pgvector]
cssclasses: [procurement-doc, ai-doc]
status: "#approved"
related: ["[[08_Infrastructure_Component_Alignment]]", "[[09_bpp_catalog_semantic_cache_Schema]]", "[[12_Full_System_Validation_Flow]]", "[[15_Three_Zone_Decision_Space]]", "[[18_MCP_Fallback_Tool_Overview]]"]
---

# Approved Hybrid Architecture — Strategic Overview

## Stage 3 Introduction

The approved design introduces a **Stage 3: Hybrid Item Validator** inside Lambda 1. It runs after `BecknIntentParser` produces a `BecknIntent` and before returning the result to the orchestrator.

## Full Stage 3 Pipeline

```
Lambda 1: IntentParser (port 8001)
─────────────────────────────────────────────────────────────
Stage 1 │ IntentClassifier  (LLM)
        │ Output: ParsedIntent — domain gatekeeper
        ▼
Stage 2 │ BecknIntentParser  (LLM + instructor + Pydantic)
        │ Output: BecknIntent { item, descriptions, quantity,
        │         location_coordinates, delivery_timeline,
        │         budget_constraints }
        ▼
Stage 3 │ Hybrid Item Validator  ◄── NEW
        │
        │ PRIMARY PATH (~15ms):
        │   embed(item + descriptions) → cosine search → PostgreSQL pgvector
        │   sim ≥ 0.92 → VALIDATED      (proceed)
        │   0.75–0.91  → AMBIGUOUS      (return suggestions to user)
        │   < 0.75     → CACHE MISS     (trigger MCP fallback)
        │
        │ FALLBACK PATH (~1–8s, cache miss only):
        │   MCP tool: search_bpp_catalog → POST /discover on BAP (3s timeout)
        │   found: true  → MCP_VALIDATED (proceed + async cache write)
        │   found: false → NOT_FOUND     (return suggestions or empty)
        ▼
        ParseResponse { intent, beckn_intent, ValidationResult }
```

## Three-Zone Routing

The primary path routes to three zones based on cosine similarity score:

- **VALIDATED** (≥ 0.92): Cache hit with high confidence — proceed to Lambda 2 directly
- **AMBIGUOUS** (0.75–0.91): User confirmation gate — top-3 suggestions returned, Lambda 2 blocked pending selection
- **CACHE MISS** (< 0.75 or empty): MCP fallback triggered — bounded live BPP probe

Only the CACHE MISS zone triggers the fallback path. AMBIGUOUS is not a fallback trigger — it is a user decision point. See [[15_Three_Zone_Decision_Space]] for full zone specifications.

## Output

```
ParseResponse { intent, beckn_intent, ValidationResult }
```

The `ValidationResult` is a first-class field carrying `status`, `similarity_score`, `validated_item`, `mcp_used`, and `suggestions`. See [[31_ParseResponse_Extended_Schema]] for the full schema.

---

## Related Notes

- [[08_Infrastructure_Component_Alignment]] — The six infrastructure components and their roles
- [[09_bpp_catalog_semantic_cache_Schema]] — The pgvector table powering the primary path
- [[12_Full_System_Validation_Flow]] — Complete sequence diagram of the full validation flow
- [[15_Three_Zone_Decision_Space]] — VALIDATED / AMBIGUOUS / CACHE MISS / COLD START specifications
- [[18_MCP_Fallback_Tool_Overview]] — The MCP sidecar tool invoked on cache misses
