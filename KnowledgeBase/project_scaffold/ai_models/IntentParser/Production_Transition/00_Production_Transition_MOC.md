---
tags: [production, architecture, mcp, onix, postgres, moc, zettelkasten, production-readiness]
cssclasses: [procurement-doc, ai-doc, moc]
status: "#draft"
related: ["[[../BPP_Item_Validation/00_BPP_Validation_MOC]]", "[[../BPP_Item_Validation/07_Hybrid_Architecture_Overview]]", "[[../BPP_Item_Validation/07_Production_Failures_and_LLM_Fallbacks]]", "[[../Core_Logic/00_Intent_Parsing_Core_MOC]]", "[[nl_intent_parser]]", "[[beckn_bap_client]]"]
---

# Production Transition — Map of Content

> [!abstract] Purpose
> This MOC maps the engineering work required to transition the **Stage 3 Hybrid BPP Item Validation** from a Proof of Concept (mock data, synchronous I/O, in-process fakes) into a **production-grade, fully connected system**. Every mock component is accounted for, and each note details its real-world replacement.

---

## The PoC → Production Gap

The PoC (`Playground/end_to_end_intent_parser_poc.ipynb`) validated the three-zone decision logic, the HNSW semantic cache, and the recovery flow using mocks. The following table maps each mock to its production replacement and the note that details the transition.

| PoC Component (Mock) | Production Replacement | Transition Note |
|---|---|---|
| `mock_mcp_search_bpp_catalog()` | Real MCP server (SSE transport, sidecar) | [[01_Real_MCP_Server_Integration]] |
| MCP server returns Python dict | MCP server issues `POST /discover` to BAP Client → ONIX → BPPs | [[02_Connecting_MCP_to_ONIX_BPP]] |
| `mock_catalog_normalizer_path_a()` | Real `CatalogNormalizer` in `beckn-bap-client` on `on_discover` callback | [[03_Real_CatalogNormalizer_Integration]] |
| Synchronous `psycopg2` UPSERT | Async `BackgroundTask` / Celery writes (non-blocking) | [[04_Async_Event_Driven_Cache_Writes]] |
| `psycopg2.connect(**DB_CONFIG)` | `asyncpg` connection pool with secrets management | [[05_Database_Connection_Pooling]] |

---

## What Does NOT Change

The following components are validated by the PoC and require **no architectural changes** for production. They are referenced here for completeness.

| Component | Status | Architecture Reference |
|---|---|---|
| `all-MiniLM-L6-v2` embedding via `sentence-transformers` | **Production-ready as-is** — runs on CPU, no API key | [[../BPP_Item_Validation/11_Embedding_Input_Strategy]] |
| `bpp_catalog_semantic_cache` schema (`vector(384)`, HNSW) | **Production-ready** — `18_bpp_catalog_semantic_cache.sql` migrated | [[../BPP_Item_Validation/09_bpp_catalog_semantic_cache_Schema]] |
| Three-zone threshold logic (VALIDATED / AMBIGUOUS / CACHE_MISS) | **Production-ready** — thresholds calibrated for `all-MiniLM-L6-v2` | [[../BPP_Item_Validation/15_Three_Zone_Decision_Space]] |
| `CatalogCacheWriter` (Path A) and `MCPResultAdapter` (Path B) | **Production-ready** — interface contracts stable | [[../BPP_Item_Validation/24_Two_Writers_One_Table_Pattern]] |
| Day-2 recovery: `broaden_procurement_query` + recovery actions | **Architecture defined** — implementation sprint pending | [[../BPP_Item_Validation/07_Production_Failures_and_LLM_Fallbacks]] |

---

## 1. MCP Infrastructure

- [[01_Real_MCP_Server_Integration]] — Replace the Python in-process mock with a real MCP server. Transport choice (SSE over HTTP), sidecar deployment, and the instructor `mode=TOOLS` switch for qwen3 tool-calling.
- [[02_Connecting_MCP_to_ONIX_BPP]] — How the real MCP server executes the `search_bpp_catalog` tool: `POST /discover` to the BAP Client, Beckn request signing (ed25519), the 10-second async callback window, and ONIX network routing.

---

## 2. CatalogNormalizer Integration

- [[03_Real_CatalogNormalizer_Integration]] — Remove `mock_catalog_normalizer_path_a()`. Connect the real `CatalogNormalizer` inside `beckn-bap-client` to the Path A `CatalogCacheWriter`. The `on_discover` callback event as the production Path A trigger.

---

## 3. Async I/O and Database

- [[04_Async_Event_Driven_Cache_Writes]] — Replace synchronous `psycopg2` UPSERT calls with non-blocking async writes. FastAPI `BackgroundTasks` for Phase 1; Celery + message broker for Phase 2. Failure handling and dead-letter patterns.
- [[05_Database_Connection_Pooling]] — Replace `psycopg2.connect()` with an `asyncpg` connection pool. Pool sizing, `pgvector` codec registration, per-connection `hnsw.ef_search` initialization, and secrets management.

---

## 4. Complete Production Data Flow

- [[06_End_to_End_Production_Data_Flow]] — Capstone note: full Mermaid sequence diagram of the entire production system from raw NL query to final `ParseResponse`, including all real components, network hops, and the two cache-write paths.

---

## Transition Dependency Order

The notes above should be implemented roughly in the following order:

```
[05] DB Connection Pool  ←  required by all DB-writing components
      │
      ▼
[04] Async Cache Writes  ←  required by Path A and Path B writers
      │
      ▼
[03] Real CatalogNormalizer  ←  required before Path A writes can flow
      │
      ▼
[01] Real MCP Server  ←  required before real tool-calling works
      │
      ▼
[02] MCP → ONIX  ←  requires real MCP server + BAP Client connectivity
```

The database pool (`05`) is the foundation dependency — nothing else can write to PostgreSQL in production without it.

---

## Document Lineage

> [!note] Sources
> This MOC is derived from:
> - `Playground/end_to_end_intent_parser_poc.ipynb` — the PoC whose mock components are replaced here
> - `Playground/hybrid_item_validation_poc.ipynb` — Stage 3 standalone PoC
> - [[../BPP_Item_Validation/00_BPP_Validation_MOC]] — the approved hybrid architecture specification
>
> **Related vault sections:**
> - [[nl_intent_parser]] — Lambda 1 service implementation
> - [[beckn_bap_client]] — Lambda 2 / BAP Client (hosts CatalogNormalizer and CatalogCacheWriter)
> - [[databases_postgresql_redis]] — PostgreSQL 16 infrastructure
> - [[microservices_architecture]] — Full Step Functions state machine and Lambda map
