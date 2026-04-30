---
tags: [bpp-validation, api-contract, architecture, intent-parser]
cssclasses: [procurement-doc, ai-doc]
status: "#approved"
related: ["[[32_Orchestrator_Routing_Logic]]", "[[15_Three_Zone_Decision_Space]]", "[[20_MCP_LLM_Reasoning_Loop]]"]
---

# Extended `ParseResponse` Schema

## Full Schema Tree

```
ParseResponse  (extended for Stage 3)
├── intent           : str                 "SearchProduct"
├── confidence       : float               Stage 1 LLM classification score
├── beckn_intent     : BecknIntent | null
│   ├── item                    : str      May be updated by MCP self-correction
│   ├── descriptions            : list[str]
│   ├── quantity                : int
│   ├── location_coordinates    : str
│   ├── delivery_timeline       : int
│   └── budget_constraints      : { min: float, max: float }
├── validation       : ValidationResult
│   ├── status           : enum   VALIDATED | AMBIGUOUS | MCP_VALIDATED | NOT_FOUND
│   ├── cache_hit         : bool
│   ├── similarity_score  : float | null   null when cache is empty
│   ├── embedding_strategy: str  | null    strategy of the matched row
│   ├── validated_item    : str  | null    BPP canonical name; null if NOT_FOUND
│   ├── bpp_id            : str  | null    Source BPP of validated item
│   ├── suggestions       : list[Suggestion]
│   │   └── Suggestion { item_name, bpp_id, similarity_score, confidence_label,
│   │                    embedding_strategy }
│   ├── mcp_used          : bool
│   └── mcp_query_used    : str | null     Exact query MCP sent; null if unused
└── routed_to        : str                 LLM model used in Stage 2
```

## Key Field Notes

### `beckn_intent.item`

"May be updated by MCP self-correction" — when the MCP tool identifies the BPP canonical name for the user's query (see [[20_MCP_LLM_Reasoning_Loop]] step 2), `beckn_intent.item` is updated to that canonical name. The `validation.validated_item` field also captures this canonical name.

### `validation.status` Enum Values

| Value | Meaning |
|---|---|
| `VALIDATED` | Cache hit with similarity ≥ 0.92 |
| `MCP_VALIDATED` | MCP probe returned `found: true`; item confirmed and possibly renamed |
| `AMBIGUOUS` | Cache hit with similarity 0.75–0.91; user confirmation required |
| `NOT_FOUND` | Cache miss + MCP probe returned `found: false` |

### `Suggestion` Sub-Type

```
Suggestion {
  item_name         : str    BPP canonical name of the candidate
  bpp_id            : str    Source BPP identifier
  similarity_score  : float  Cosine similarity to the query vector
  confidence_label  : str    Human-readable label ("Very likely match", "Possible match")
  embedding_strategy: str    "item_name_only" or "item_name_and_specs"
}
```

`confidence_label` values are human-readable for frontend display in the AMBIGUOUS zone. The `embedding_strategy` field enables the frontend to optionally signal fidelity to the user.

---

## Related Notes

- [[32_Orchestrator_Routing_Logic]] — How the orchestrator routes on `validation.status`
- [[15_Three_Zone_Decision_Space]] — Zone definitions that map to the `status` enum values
- [[20_MCP_LLM_Reasoning_Loop]] — When and how `beckn_intent.item` gets updated
