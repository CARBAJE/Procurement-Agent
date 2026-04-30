---
tags: [bpp-validation, architecture, beckn, intent-parser, mcp, pgvector]
cssclasses: [procurement-doc, ai-doc]
status: "#approved"
related: ["[[07_Hybrid_Architecture_Overview]]", "[[15_Three_Zone_Decision_Space]]", "[[18_MCP_Fallback_Tool_Overview]]", "[[26_MCPResultAdapter]]"]
---

# Full System Validation Flow

## Complete Sequence Diagram

```mermaid
sequenceDiagram
    participant U as User / Frontend
    participant IP as IntentParser<br/>(Lambda 1, :8001)
    participant EMB as Embedding API<br/>(text-emb-3-small)
    participant PG as PostgreSQL<br/>(pgvector)
    participant MCP as MCP Server<br/>(sidecar)
    participant BAP as BecknBAP Client<br/>(Lambda 2, :8002)
    participant ORCH as Orchestrator<br/>(:8004)

    U->>IP: POST /parse {"query": "500 SS flanged valves Bangalore 5 days"}

    rect rgb(230, 240, 255)
        Note over IP: Stage 1 — IntentClassifier
        IP->>IP: LLM → SearchProduct (confidence 0.97)
    end

    rect rgb(230, 255, 230)
        Note over IP: Stage 2 — BecknIntentParser
        IP->>IP: LLM + instructor + Pydantic
        Note over IP: item="SS flanged valve"<br/>descriptions=["SS316","flanged","2 inch"]<br/>quantity=500, location="12.9716,77.5946"
    end

    rect rgb(255, 250, 210)
        Note over IP: Stage 3 — Hybrid Item Validator

        IP->>EMB: embed("SS flanged valve | SS316 flanged 2 inch")
        EMB-->>IP: query_vector[1536]

        IP->>PG: SELECT item_name, bpp_id, embedding_strategy,<br/>1-(embedding<=>query_vec) AS sim<br/>FROM bpp_catalog_semantic_cache<br/>ORDER BY embedding <=> query_vec LIMIT 5

        alt VALIDATED — similarity >= 0.92
            PG-->>IP: [("SS316 flange valve 2in", "bpp.a.com", 0.945, "item_name_and_specs")]
            IP->>PG: UPDATE last_seen_at=NOW(), hit_count++
            Note over IP: ValidationResult: status=VALIDATED<br/>sim=0.945, cache_hit=true, mcp_used=false
        else AMBIGUOUS — 0.75 <= similarity < 0.92
            PG-->>IP: [("SS316 flange valve 2in", 0.81), ("carbon gate valve", 0.77)]
            Note over IP: ValidationResult: status=AMBIGUOUS<br/>suggestions=[top-3 with confidence_label]
            IP-->>U: ParseResponse {status=AMBIGUOUS, suggestions=[...]}<br/>← Await user confirmation
        else CACHE MISS — similarity < 0.75 OR empty
            PG-->>IP: [] or best_sim < 0.75

            Note over IP: Trigger MCP Fallback (≤ 2 tool calls, 3s timeout each)
            IP->>MCP: tool_call: search_bpp_catalog(<br/>  item_name="SS flanged valve",<br/>  descriptions=["SS316","flanged","2 inch"],<br/>  location="12.9716,77.5946")

            MCP->>BAP: POST /discover {BecknIntent probe}<br/>timeout=3s
            BAP->>BAP: CatalogNormalizer runs internally
            BAP-->>MCP: DiscoverResponse {offerings: [DiscoverOffering...]}

            alt MCP probe returns results
                MCP-->>IP: {found:true, items:[...], query_used:"SS316 flanged valve"}
                Note over IP: ValidationResult: status=MCP_VALIDATED<br/>validated_item="SS316 flange valve 2in"<br/>mcp_used=true
                IP-)PG: async MCPResultAdapter.adapt(mcp_result, original_intent)<br/>source='mcp_feedback', strategy='item_name_and_specs'
            else MCP probe returns nothing
                MCP-->>IP: {found:false, items:[]}
                Note over IP: ValidationResult: status=NOT_FOUND<br/>suggestions=[] or AMBIGUOUS zone near-misses
                IP-->>U: ParseResponse {status=NOT_FOUND, suggestions=[...]}
            end
        end
    end

    Note over IP: VALIDATED and MCP_VALIDATED paths continue
    IP-->>U: ParseResponse {intent, beckn_intent, validation:{status,validated_item,sim,bpp_id,mcp_used}}

    U->>ORCH: POST /discover {confirmed BecknIntent}

    rect rgb(255, 230, 230)
        Note over ORCH,BAP: Steps 2–4: single authoritative discover (unchanged)
        ORCH->>BAP: POST /discover {BecknIntent}
        BAP-->>ORCH: DiscoverOffering[]
    end
```

## Participants

- **User / Frontend** — Initiates the parse request; receives ParseResponse including suggestions on AMBIGUOUS
- **IntentParser** (Lambda 1, :8001) — Runs Stages 1, 2, 3; orchestrates the validation flow
- **Embedding API** (text-emb-3-small) — Produces the 1536-dim query vector for cosine search
- **PostgreSQL** (pgvector) — Hosts `bpp_catalog_semantic_cache`; returns top-5 cosine similarity candidates
- **MCP Server** (sidecar) — Exposes `search_bpp_catalog` tool; routes to BAP Client on cache miss
- **BecknBAP Client** (Lambda 2, :8002) — Target of MCP probe; `CatalogNormalizer` runs internally
- **Orchestrator** (:8004) — Routes on `validation.status`; calls Lambda 2 for authoritative discover only on VALIDATED/MCP_VALIDATED

---

## Related Notes

- [[07_Hybrid_Architecture_Overview]] — Stage 3 pipeline overview
- [[15_Three_Zone_Decision_Space]] — VALIDATED / AMBIGUOUS / CACHE MISS zone specifications
- [[18_MCP_Fallback_Tool_Overview]] — MCP sidecar design and constraints
- [[26_MCPResultAdapter]] — Async cache write after MCP_VALIDATED
