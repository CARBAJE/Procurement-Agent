---
tags: [bpp-validation, architecture, intent-parser, feedback-loop, catalog-normalizer]
cssclasses: [procurement-doc, ai-doc]
status: "#approved"
related: ["[[07_Hybrid_Architecture_Overview]]", "[[25_CatalogCacheWriter]]", "[[26_MCPResultAdapter]]", "[[29_Component_Responsibilities_Table]]"]
---

# Full Component Interaction Map

## ASCII Art Component Map

```
╔══════════════════════════════════════════════════════════════════════════╗
║  Lambda 1: intention-parser (port 8001)                                  ║
║                                                                          ║
║  ┌──────────────────────────────────────────────────────────────────┐    ║
║  │  IntentParser Module                                             │    ║
║  │  Stage 1: IntentClassifier    (LLM)                              │    ║
║  │  Stage 2: BecknIntentParser   (LLM + instructor + Pydantic v2)   │    ║
║  │  Stage 3: HybridItemValidator                                    │    ║
║  │    ├── EmbeddingClient  ─────────────────► text-emb-3-small      │    ║
║  │    ├── PgVectorClient   ─────────────────► PostgreSQL (pgvector) │    ║
║  │    └── MCPClient        ─────────────────► MCP Server (sidecar)  │    ║
║  └──────────────────────────────────────────────────────────────────┘    ║
║                                                                          ║
║  ┌──────────────────────────────────────────────────────────────────┐    ║
║  │  MCP Server (sidecar)                                            │    ║
║  │  Tool: search_bpp_catalog                                        │    ║
║  │    └── HTTP POST ────────────────────────► BAP Client :8002      │    ║
║  └──────────────────────────────────────────────────────────────────┘    ║
║                                                                          ║
║  ┌──────────────────────────────────────────────────────────────────┐    ║
║  │  MCPResultAdapter  (Path B write — async, non-blocking)          │    ║
║  │    DiscoverOffering[] + BecknIntent → embed → PG INSERT          │    ║
║  └──────────────────────────────────────────────────────────────────┘    ║
╚══════════════════════════════════════════════════════════════════════════╝
         │ (async Path B write)              │ (validated BecknIntent)
         ▼                                  ▼
  ╔══════════════════╗             ╔══════════════════════╗
  ║  PostgreSQL 16   ║             ║  Orchestrator :8004  ║
  ║  pgvector        ║             ╚══════════════════════╝
  ║  bpp_catalog_    ║                      │
  ║  semantic_cache  ║         ╔════════════╩══════════════╗
  ╚══════════════════╝         ║  Lambda 2: BAP Client     ║
         ▲                     ║  :8002 → ONIX → BPP Net   ║
         │ (Path A write)      ╚═══════════════════════════╝
  ╔══════════════════════╗              ▲
  ║  CatalogCacheWriter  ║              │
  ║  (inside BAP Client) ║    ╔═════════╩══════════╗
  ╚══════════════════════╝    ║  CatalogNormalizer  ║
         ▲                    ║  (inside BAP Client)║
         │                    ╚════════════════════╝
  CatalogNormalizer
  produces DiscoverOffering[]
  ─────────────────────────►
  CatalogCacheWriter writes
  to cache (Path A, async)
```

## Connection Labels

| Arrow | From | To | Description |
|---|---|---|---|
| EmbeddingClient → text-emb-3-small | HybridItemValidator | Embedding API | Query vector generation |
| PgVectorClient → PostgreSQL | HybridItemValidator | bpp_catalog_semantic_cache | Cosine similarity search |
| MCPClient → MCP Server | HybridItemValidator | MCP sidecar | Cache miss fallback |
| MCP Server → BAP Client :8002 | MCP sidecar | Lambda 2 | Bounded discover probe |
| MCPResultAdapter → PostgreSQL | MCPResultAdapter | bpp_catalog_semantic_cache | Path B async write |
| Validated BecknIntent → Orchestrator | Lambda 1 output | Orchestrator :8004 | VALIDATED/MCP_VALIDATED routing |
| Orchestrator → BAP Client | Orchestrator | Lambda 2 | Single authoritative discover |
| CatalogNormalizer → CatalogCacheWriter | BAP Client internal | BAP Client internal | Path A: DiscoverOffering[] handoff |
| CatalogCacheWriter → PostgreSQL | BAP Client | bpp_catalog_semantic_cache | Path A async write |

---

## Related Notes

- [[07_Hybrid_Architecture_Overview]] — Stage 3 pipeline detail
- [[25_CatalogCacheWriter]] — Path A writer (CatalogCacheWriter inside BAP Client)
- [[26_MCPResultAdapter]] — Path B writer (MCPResultAdapter inside IntentParser)
- [[29_Component_Responsibilities_Table]] — Tabular component responsibility summary
