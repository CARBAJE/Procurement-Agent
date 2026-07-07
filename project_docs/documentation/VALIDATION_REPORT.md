# Documentation Validation Report

**Date:** 2026-07-07
**Reviewer:** Documentation cross-consistency automated review
**Scope:** All 18 files in `documentation/`

---

## 1. Files Reviewed

| # | File | Lines (approx) |
|---|---|---|
| 1 | README.md | 221 |
| 2 | PROJECT_OVERVIEW.md | ~120 |
| 3 | ARCHITECTURE.md | ~400 |
| 4 | SYSTEM_DESIGN.md | ~300 |
| 5 | COMPONENTS.md | ~400 |
| 6 | DATA_FLOW.md | ~250 |
| 7 | INSTALLATION.md | ~250 |
| 8 | ENVIRONMENT.md | ~380 |
| 9 | CONFIGURATION.md | ~200 |
| 10 | DATABASE.md | ~650 |
| 11 | API_REFERENCE.md | ~600 |
| 12 | SECURITY.md | ~300 |
| 13 | DEPLOYMENT.md | ~350 |
| 14 | TESTING.md | ~300 |
| 15 | DEVELOPMENT_GUIDE.md | ~768 |
| 16 | CONTRIBUTING.md | ~332 |
| 17 | TROUBLESHOOTING.md | ~680 |
| 18 | GLOSSARY.md | ~249 |

---

## 2. Issues Found and Fixed

| # | File | Issue Type | Description | Fix Applied |
|---|---|---|---|---|
| 1 | `ARCHITECTURE.md` line 3 | Broken cross-reference | Header note linked to `[Modules](MODULES.md)` and `[Data Model](DATA_MODEL.md)` — neither file exists in `documentation/`. | Changed `[Modules](MODULES.md)` → `[Components](COMPONENTS.md)` and `[Data Model](DATA_MODEL.md)` → `[Database](DATABASE.md)`. |
| 2 | `ARCHITECTURE.md` line 11 | Factual contradiction | "Sixteen containers run on a bridged Docker network" — `DEPLOYMENT.md`, `README.md`, `CONTRIBUTING.md`, and `COMPONENTS.md` all confirm 18 Docker containers. | Changed "Sixteen" to "Eighteen". |
| 3 | `TESTING.md` line 5 | Broken cross-reference | Related-docs line referenced `[Repository Structure](REPOSITORY_STRUCTURE.md)` and `[Local Development Setup](LOCAL_DEV_SETUP.md)` — neither file exists in `documentation/`. | Replaced with `[Installation](INSTALLATION.md)` (for setup) and `[Development Guide](DEVELOPMENT_GUIDE.md)` (for repository layout). |
| 4 | `ENVIRONMENT.md` line 5 | Broken cross-reference | Related-docs line referenced `[Services](SERVICES.md)` — this file does not exist in `documentation/`. | Replaced `[Services](SERVICES.md)` with `[Components](COMPONENTS.md)`. |
| 5 | `ENVIRONMENT.md` line 334 | Factual contradiction | sim-bpp section described as "Local Beckn BPP simulator written in Python" — sim-bpp is Node.js (Express), as confirmed by `COMPONENTS.md`, `README.md`, `DEPLOYMENT.md`, `API_REFERENCE.md`, `CONTRIBUTING.md`, and the GLOSSARY entry for sim-bpp. The source path `services/sim-bpp/src/handler.py` (a Python path) was also wrong. | Changed "written in Python" to "written in Node.js (Express)" and updated source path to `services/sim-bpp/`. |
| 6 | `README.md` Documentation Index | Broken cross-references (×10) | Documentation Index table contained 10 links to files that do not exist in `documentation/`: `SERVICES.md`, `BECKN_PROTOCOL.md`, `INTENT_PARSER.md`, `ERP_INTEGRATION.md`, `NEGOTIATION.md`, `AUDIT_TRAIL.md`, `ANALYTICS.md`, `FRONTEND.md`, `MLOPS.md`, `DECISIONS.md`. | Replaced the entire table with one entry per existing documentation file (all 18 files). |
| 7 | `DATABASE.md` section 7.2 | Factual contradiction / inconsistent port | Redis Negotiation Engine Channel table listed `demo-gateway` as `(:8005)` — port 8005 belongs to `catalog-normalizer`. The correct host port for `frontend_demo_gateway` (demo-gateway) is 8015, as confirmed by `DEVELOPMENT_GUIDE.md` port map, `TROUBLESHOOTING.md` health table, `CONTRIBUTING.md`, and `DEVELOPMENT_GUIDE.md` §10.4 (Known Problem 10.4 explicitly states the 8005 vs 8015 discrepancy). | Changed `:8005` to `:8015`. |
| 8 | `SYSTEM_DESIGN.md` line 259 | Factual contradiction | ADR-0001 status line stated "Accepted — May 2025" — the project timeline spans April–July 2026 (confirmed by `README.md` Project Status, current date context, and git history). | Changed "May 2025" to "May 2026". |
| 9 | `GLOSSARY.md` header + throughout | Broken cross-references (×32 occurrences) | Opening paragraph and nearly every glossary entry cross-referenced `[Technologies](TECHNOLOGIES.md)` and `[Design Decisions](DESIGN_DECISIONS.md)` — neither file exists in `documentation/`. Affected entries: ACK, advisory mode, agent_memory_vector, AND-token matching, ANN, asyncio.create_task, audit_trail_event, autonomous mode, BAP, beckn_network, Beckn Protocol, BecknIntent, BPP, BudgetConstraints, Circuit breaker, conda environment, cosine similarity, DeDi registry, DiscoverOffering, ED25519, erp_sync_record, ERPAdapter Protocol, fastembed, fire-and-forget, HITL, HMAC, HNSW, IntentParser, kafka_offset, LangGraph, MCP, MLflow, NDCG@5, on_confirm, on_discover, on_init, on_select, ONIX adapter, orchestrator, Outbox pattern, pgvector, Phase2Scorer, procurement_request, purchase_order, query broadening, RankNet, reasoning_payload, recovery flow, Redis pub/sub, retention_until, RFQ, sentence-transformers, sim-bpp, splunk_indexed, SSE, targetType: url. | Replaced all `[Technologies](TECHNOLOGIES.md)` occurrences with `[Components](COMPONENTS.md)` and all `[Design Decisions](DESIGN_DECISIONS.md)` occurrences with `[System Design](SYSTEM_DESIGN.md)`. 32 total replacements across the file. |

---

## 3. Outstanding Issues

None. All issues found during the review were fixed in-place using the Edit tool. A final grep across all 18 files confirmed zero remaining references to non-existent documentation files.

The following items were noted but are **intentional external references** (not bugs) and were deliberately left unchanged:

| File | Reference | Reason |
|---|---|---|
| `DEVELOPMENT_GUIDE.md` §2.4, "See Also" | `../docs/architecture/decisions/0001-use-redis-pubsub-for-async-beckn-responses.md` | Relative path to a codebase file that does exist in the repo at `docs/architecture/decisions/`. This is a valid cross-reference to a non-documentation-folder file; the intent is to link to the actual ADR document in the repo. |
| `CONTRIBUTING.md` §5.1 | `../docs/architecture/decisions/0001-use-redis-pubsub-for-async-beckn-responses.md` | Same as above. |
| `DEPLOYMENT.md` | `../docs/architecture/decisions/0001-use-redis-pubsub-for-async-beckn-responses.md` | Same as above. |
| `DATABASE.md` header | `../docs/architecture/decisions/0001-use-redis-pubsub-for-async-beckn-responses.md` | Same as above. |
| `DEVELOPMENT_GUIDE.md` "See Also" | `Bap-1/CLAUDE.md` | Reference to existing codebase file; intentional cross-reference. |
| `CONTRIBUTING.md` §3, §5 | `Bap-1/CLAUDE.md` | Same as above. |

---

## 4. Overall Assessment

The 18 documentation files are well-structured and internally consistent in their technical content. The issues found fell into three categories:

**Broken cross-references** were the most numerous problem: 16 unique file references to non-existent documents were found across five files. The most impactful was `GLOSSARY.md`, which contained 32 broken links to two non-existent files (`TECHNOLOGIES.md` and `DESIGN_DECISIONS.md`) — these have been redirected to the closest existing equivalents (`COMPONENTS.md` and `SYSTEM_DESIGN.md` respectively). The `README.md` Documentation Index was also missing links to 14 of the 18 actual files in the folder while listing 10 files that do not exist; this table has been replaced with a complete, accurate index.

**Factual contradictions** were found in three locations. The container count in `ARCHITECTURE.md` (16 instead of 18) is corrected. The sim-bpp language attribution in `ENVIRONMENT.md` (Python instead of Node.js) is corrected. The demo-gateway port in `DATABASE.md` section 7.2 (8005 instead of 8015) is corrected.

**Date inaccuracy**: `SYSTEM_DESIGN.md` recorded ADR-0001's acceptance as May 2025 when the project ran April–July 2026; this has been corrected to May 2026.

No inconsistent terminology (e.g. "Intent Parser" vs "IntentParser"), no missing GLOSSARY links in first-introduction contexts beyond what was already addressed, and no contradictory port numbers (beyond the demo-gateway issue already fixed) were found across the 18-file corpus.
