# Database Schema

PostgreSQL 16 + pgvector. 24 SQL migration files under `database/sql/`, executed in lexicographic (NN_) order which matches the FK dependency chain. All migrations are idempotent (`IF NOT EXISTS`, `IF EXISTS`, `DO $$ … $$` guards).

- (Source: database/sql/ — all files read directly -- Confidence: High)
- (Source: database/README.md -- Confidence: High)

## 1. Overview

| Aspect | Detail |
|---|---|
| Engine | PostgreSQL 16 |
| Extension: vectors | pgvector 0.7.0 (`vector` type, HNSW indexes) |
| Extension: UUIDs | uuid-ossp (`uuid_generate_v4()`) and pgcrypto (`gen_random_uuid()`) |
| Tables | 16 primary + 3 negotiation-engine-specific (19 total) |
| ENUM types | 20 custom types across 00_extensions_and_types.sql (+ 2 additive values via migrations 19, 22) |
| Indexes | 22 named B-tree/partial indexes (17_indexes.sql) + 2 HNSW vector indexes + 5 migration-added indexes |
| Schema setup | `python database/setup_database.py [--create-db] [--drop-all] [--continue-on-exists]` |

The main database is `procurement_agent`. A second database called `negotiation` runs in the Dockerised postgres service (host port 55432) and holds the negotiation engine's LangGraph checkpoint tables and the three negotiation audit tables defined in 20_negotiation_schema.sql.

(Source: docker-compose.yml, database/README.md -- Confidence: High)

---

## 2. Tables by Group

### 2.1 Identity and Request

| Table | Migration | PK | Key Columns | Foreign Keys | Purpose |
|---|---|---|---|---|---|
| `users` | `01_users.sql` | `user_id UUID` | `email`, `name`, `role user_role`, `department`, `approval_threshold DECIMAL(15,2)`, `keycloak_id`, `idp_provider idp_provider_type` | — | RBAC persons. Source of truth is Keycloak; keycloak_id = JWT `sub` claim. |
| `procurement_requests` | `03_procurement_requests.sql` | `request_id UUID` | `raw_input_text TEXT`, `channel channel_type`, `urgency_flag BOOLEAN`, `category VARCHAR(100)`, `status procurement_status`, `pending_chosen_item_id VARCHAR(255)`, `pending_transaction_id VARCHAR(255)` | `requester_id → users(user_id) RESTRICT` | Root anchor of every purchase request. The two `pending_*` columns (added by migration 22b) allow approval resumption after session TTL expiry. |

### 2.2 NL Intent Pipeline

| Table | Migration | PK | Key Columns | Foreign Keys | Purpose |
|---|---|---|---|---|---|
| `parsed_intents` | `04_parsed_intents.sql` | `intent_id UUID` | `intent_class intent_class_type`, `confidence_score FLOAT [0,1]`, `model_version VARCHAR(50)`, `parsed_at TIMESTAMP` | `request_id → procurement_requests UNIQUE CASCADE` | Stage 1 NL Intent Parser output. 1:1 with `procurement_requests`. |
| `beckn_intents` | `05_beckn_intents.sql` | `beckn_intent_id UUID` | `item VARCHAR(255)`, `descriptions JSONB[]`, `quantity INT`, `unit VARCHAR(50)`, `location_coordinates VARCHAR(50)` ("lat,lon"), `delivery_timeline_hours INT`, `budget_min/max DECIMAL(15,2)`, `currency CHAR(3)`, `compliance_requirements JSONB[]` | `intent_id → parsed_intents UNIQUE CASCADE` | Anti-corruption layer. Canonical encoded intent. 1:1 with `parsed_intents`. `delivery_timeline_hours` is always hours (not ISO 8601). |

### 2.3 Discovery

| Table | Migration | PK | Key Columns | Foreign Keys | Purpose |
|---|---|---|---|---|---|
| `discovery_queries` | `06_discovery_queries.sql` | `query_id UUID` | `network_id VARCHAR(100)`, `cache_hit BOOLEAN`, `results_count INT`, `queried_at TIMESTAMP` | `beckn_intent_id → beckn_intents RESTRICT` | Record of each POST /discover call. Many per beckn_intent. `cache_hit=TRUE` indicates response served from Redis (15-min TTL). |
| `bpp` | `02_bpp.sql` | `bpp_id UUID` | `name`, `network_id VARCHAR(100)`, `endpoint_url VARCHAR(500)`, `reliability_score FLOAT [0,1]`, `on_time_delivery_rate FLOAT [0,1]`, `last_seen_at TIMESTAMP` | — | Beckn Provider Platforms (sellers) on the network. Defined early because seller_offerings and purchase_orders both reference it. |
| `seller_offerings` | `08_seller_offerings.sql` (+ `21_order_detail_fidelity.sql`) | `offering_id UUID` | `item_id VARCHAR(255)`, `item_name VARCHAR(255)` (added by 21), `price DECIMAL(15,2) > 0`, `currency CHAR(3)`, `delivery_eta_hours INT > 0`, `quality_rating FLOAT [0,5]`, `certifications JSONB`, `inventory_count INT`, `format_variant INT [1–5]`, `is_normalized BOOLEAN` | `query_id → discovery_queries RESTRICT`, `bpp_id → bpp RESTRICT` | Normalized BPP offerings post-discovery. `format_variant` records the original BPP catalog format before normalization (1=BECKN_V2_FLAT_RESOURCES through 5=UNKNOWN/LLM). |

### 2.4 Scoring, Negotiation, Approval, and Order

| Table | Migration | PK | Key Columns | Foreign Keys | Purpose |
|---|---|---|---|---|---|
| `scored_offers` | `09_scored_offers.sql` | `score_id UUID` | `rank INT > 0`, `total_score FLOAT [0,100]`, `price_score`, `delivery_score`, `quality_score`, `compliance_score` (all FLOAT [0,100]), `tco_value DECIMAL(15,2)`, `explanation_text TEXT`, `user_overridden BOOLEAN`, `model_version VARCHAR(50)` | `offering_id → seller_offerings UNIQUE CASCADE` | Comparison Scoring Engine output. 1:1 with `seller_offerings`. `user_overridden=TRUE` feeds the calibration override-rate metric. `total_score` = composite_score × 100. |
| `negotiation_outcomes` | `10_negotiation_outcomes.sql` | `negotiation_id UUID` | `strategy_applied negotiation_strategy_type`, `initial_price DECIMAL(15,2)`, `counter_offer_price DECIMAL(15,2)`, `final_price DECIMAL(15,2)`, `discount_percent FLOAT [0,20]`, `acceptance_status acceptance_status_type` | `score_id → scored_offers UNIQUE CASCADE` | Negotiation Engine result. 1:1 with `scored_offers`. `discount_percent` hard cap at 20.0 (CHECK constraint, non-bypassable). `strategy=skipped` row is auto-created when negotiation is bypassed. `counter_offer_price=NULL` when strategy is skipped or advisory. |
| `approval_decisions` | `11_approval_decisions.sql` | `approval_id UUID` | `approval_level approval_level_type`, `amount_total DECIMAL(15,2) > 0`, `status approval_status_type`, `is_emergency BOOLEAN`, `deadline_at TIMESTAMP`, `notification_channel notification_channel_type`, `decided_at TIMESTAMP` | `negotiation_id → negotiation_outcomes UNIQUE RESTRICT`, `requester_id → users RESTRICT`, `approver_id → users SET NULL` | Approval state machine. 1:1 with `negotiation_outcomes`. Routing: `amount_total <= requester.threshold` → auto; `<= approver.threshold` → manager; else → cfo. `is_emergency=TRUE` sets `deadline_at = NOW() + 60min`. `approver_id=NULL` for auto approvals. |
| `purchase_orders` | `12_purchase_orders.sql` (+ `21_order_detail_fidelity.sql`) | `po_id UUID` | `item_id VARCHAR(255)`, `quantity INT > 0`, `unit VARCHAR(50)`, `agreed_price DECIMAL(15,2)`, `currency CHAR(3)`, `delivery_terms TEXT`, `beckn_confirm_ref VARCHAR(255) UNIQUE`, `erp_po_ref VARCHAR(255) UNIQUE`, `status po_status_type`, `fulfillment_eta TIMESTAMPTZ` (added by 21) | `approval_id → approval_decisions UNIQUE RESTRICT`, `bpp_id → bpp RESTRICT` | Confirmed PO. Created only after `approval_decisions.status IN ('approved', 'auto_approved')` and ERP budget check passes. `beckn_confirm_ref` = Beckn /confirm protocol reference. `erp_po_ref=NULL` until ERP sync completes. |

### 2.5 ERP Sync

| Table | Migration | PK | Key Columns | Foreign Keys | Purpose |
|---|---|---|---|---|---|
| `erp_sync_records` | `13_erp_sync_records.sql` (+ `19_erp_enum_extensions.sql` + `19b_erp_sync_records_outbox.sql`) | `sync_id UUID` | `erp_system erp_system_type`, `sync_type erp_sync_type`, `status erp_sync_status`, `erp_reference_id VARCHAR(255)`, `budget_available BOOLEAN`, `synced_at TIMESTAMP`; outbox columns: `idempotency_key VARCHAR(128) UNIQUE`, `attempts INT`, `next_attempt_at TIMESTAMPTZ`, `lease_until TIMESTAMPTZ`, `worker_id VARCHAR(64)`, `last_error TEXT`, `payload JSONB`, `updated_at TIMESTAMPTZ` | `po_id → purchase_orders RESTRICT` (nullable post-19b — outbox enqueues before PO row exists) | ERP sync operations with SAP S/4HANA or Oracle ERP Cloud. `budget_check` sync type is a blocking prerequisite before /confirm (CHECK constraint: `budget_available NOT NULL` when `sync_type='budget_check'`). Migration 19b promotes the table into a retryable outbox with pessimistic locking via `FOR UPDATE SKIP LOCKED`. |

### 2.6 Compliance and Intelligence

| Table | Migration | PK | Key Columns | Foreign Keys | Purpose |
|---|---|---|---|---|---|
| `audit_trail_events` | `14_audit_trail_events.sql` | `event_id UUID` | `event_type audit_event_type NOT NULL`, `agent_action TEXT NOT NULL`, `reasoning_payload JSONB DEFAULT '{}'`, `kafka_offset BIGINT NOT NULL`, `splunk_indexed BOOLEAN DEFAULT FALSE`, `event_timestamp TIMESTAMP`, `retention_until TIMESTAMP DEFAULT NOW() + 7 years` | `request_id → procurement_requests SET NULL`, `po_id → purchase_orders SET NULL`, `actor_id → users SET NULL` (all nullable) | Complete agent decision log. SOX 404 / GDPR / IT Act 2000 compliant. `actor_id=NULL` for autonomous agent actions. `kafka_offset` is a placeholder (Kafka not deployed in Phases 1-3, hardcoded to 0). `splunk_indexed` is a placeholder (SIEM not deployed). `reasoning_payload` stores LLM chain-of-thought (LangSmith deferred). |
| `agent_memory_vectors` | `15_agent_memory_vectors.sql` + `22_agent_memory_vector_dim.sql` | `vector_id UUID` | `entity_type memory_entity_type NOT NULL`, `embedding_vector vector(384) NOT NULL` (corrected from 3072 by migration 22a), `metadata JSONB DEFAULT '{}'`, `embedding_model embedding_model_type DEFAULT 'text-embedding-3-large'` (stale default — actual inserts use 'all-MiniLM-L6-v2' added by migration 22a), `indexed_at TIMESTAMP` | `source_request_id → procurement_requests SET NULL` | pgvector similarity store for agent memory. HNSW cosine ANN search, similarity threshold >=0.75, top-k=3. Actual embedding model is BAAI/bge-small-en-v1.5 (384 dims). |
| `model_governance_records` | `16_model_governance_records.sql` | `record_id UUID` | `model_name model_name_type NOT NULL`, `model_version VARCHAR(50)`, `provider ai_provider_type NOT NULL`, `accuracy_score FLOAT [0,1]`, `override_rate FLOAT [0,1]`, `evaluation_date DATE`, `status governance_status_type DEFAULT 'active'` | — | Weekly AI model evaluation registry. `UNIQUE (model_name, model_version, evaluation_date)`. Review thresholds: `intent_parsing accuracy < 0.95`, `comparison_scoring accuracy < 0.85`, `negotiation_strategy accuracy < 0.80`. Override thresholds: comparison_scoring > 30%, negotiation_strategy > 25%. Not yet populated (governance pipeline deferred to Phase 4). |

### 2.7 Semantic Cache (Stage 3)

| Table | Migration | PK | Key Columns | Purpose |
|---|---|---|---|---|
| `bpp_catalog_semantic_cache` | `18_bpp_catalog_semantic_cache.sql` | `id UUID` | `item_name TEXT NOT NULL`, `item_embedding vector(1536) NOT NULL`, `descriptions TEXT[]`, `bpp_id TEXT`, `bpp_uri TEXT`, `provider_id TEXT`, `category_tag TEXT`, `source TEXT CHECK IN ('bpp_publish','mcp_feedback')`, `embedding_strategy TEXT CHECK IN ('item_name_only','item_name_and_specs')`, `created_at TIMESTAMPTZ`, `last_seen_at TIMESTAMPTZ`, `hit_count INT DEFAULT 0`, `UNIQUE (item_name, bpp_id)` | Stage 3 BPP item existence validation. Two write paths: Path A (CatalogCacheWriter, on_discover callback) uses `item_name_only` strategy; Path B (MCPResultAdapter, successful MCP probe) uses `item_name_and_specs` strategy. Three-zone decision: >= 0.92 VALIDATED, 0.75–0.91 AMBIGUOUS, < 0.75 CACHE_MISS. |

### 2.8 Negotiation Engine (separate `negotiation` database)

These three tables live in the `negotiation` database (Docker host port 55432), not in `procurement_agent`. They are provisioned by `20_negotiation_schema.sql` which is bind-mounted as an init script. The LangGraph checkpoint tables (`checkpoints`, `checkpoint_writes`, `checkpoint_blobs`) are created separately by `AsyncPostgresSaver.setup()` at engine startup.

(Source: docker-compose.yml lines 473-479, database/sql/20_negotiation_schema.sql -- Confidence: High)

| Table | PK | Key Columns | Foreign Keys | Purpose |
|---|---|---|---|---|
| `negotiation_session` | `transaction_id TEXT` | `buyer_intent JSONB`, `category TEXT`, `status TEXT CHECK IN ('active','completed','escalated','failed','timed_out')`, `final_outcome TEXT`, `rounds_used SMALLINT`, `created_at/updated_at TIMESTAMPTZ` | — | One row per negotiation lifecycle. Root of the negotiation FK chain. |
| `negotiation_round` | `round_id UUID` | `round_no SMALLINT`, `supplier_id TEXT`, `our_offer JSONB`, `their_response JSONB`, `decision TEXT CHECK IN ('counter','accept','reject','escalate','timeout')`, `started_at/settled_at TIMESTAMPTZ`, `UNIQUE (transaction_id, round_no)` | `transaction_id → negotiation_session CASCADE` | One row per round per session. |
| `negotiation_policy_decision` | `decision_id UUID` | `rule_violated TEXT` (G1–G12), `severity TEXT CHECK IN ('LOW','MEDIUM','HIGH')`, `attempted_value JSONB`, `allowed_value JSONB`, `action_taken TEXT CHECK IN ('CLAMP','ESCALATE','LOG','BLOCK')`, `policy_version TEXT`, `reviewer TEXT`, `decided_at TIMESTAMPTZ` | `round_id → negotiation_round CASCADE`, `transaction_id → negotiation_session CASCADE` | Guardrail audit log. Mirrors the Kafka `procurement.negotiation.policy_violations.v1` topic (when Kafka is available). |

---

## 3. ENUM Types

All ENUMs are defined in `00_extensions_and_types.sql` unless noted. Two ENUMs have additive values appended by later migrations.

(Source: database/sql/00_extensions_and_types.sql, 19_erp_enum_extensions.sql, 22_agent_memory_vector_dim.sql -- Confidence: High)

| ENUM Type | Values | Used By |
|---|---|---|
| `user_role` | `requester`, `approver`, `admin` | `users.role` |
| `idp_provider_type` | `keycloak`, `okta`, `azure_ad` | `users.idp_provider` |
| `channel_type` | `web`, `slack`, `teams` | `procurement_requests.channel` |
| `procurement_status` | `draft`, `parsing`, `discovering`, `scoring`, `negotiating`, `pending_approval`, `confirmed`, `cancelled` | `procurement_requests.status` |
| `intent_class_type` | `procurement`, `query`, `support`, `out_of_scope` | `parsed_intents.intent_class` |
| `negotiation_strategy_type` | `aggressive`, `accept_margin`, `advisory`, `escalate`, `skipped` | `negotiation_outcomes.strategy_applied` |
| `acceptance_status_type` | `accepted`, `rejected`, `advisory`, `escalated`, `skipped` | `negotiation_outcomes.acceptance_status` |
| `approval_level_type` | `auto`, `manager`, `cfo` | `approval_decisions.approval_level` |
| `approval_status_type` | `pending`, `approved`, `rejected`, `escalated`, `auto_approved` | `approval_decisions.status` |
| `notification_channel_type` | `slack`, `teams`, `email` | `approval_decisions.notification_channel` |
| `po_status_type` | `pending`, `confirmed`, `shipped`, `delivered`, `cancelled` | `purchase_orders.status` |
| `erp_system_type` | `sap_s4hana`, `oracle_erp_cloud` (base); **`mock`** added by migration 19 | `erp_sync_records.erp_system` |
| `erp_sync_type` | `budget_check`, `po_creation`, `goods_receipt`, `invoice_matching` | `erp_sync_records.sync_type` |
| `erp_sync_status` | `success`, `failed`, `pending` (base); **`in_progress`** added by migration 19 | `erp_sync_records.status` |
| `audit_event_type` | `discover`, `normalize`, `score`, `negotiate`, `approve`, `confirm`, `override`, `erp_sync`, `notification` | `audit_trail_events.event_type` |
| `memory_entity_type` | `transaction`, `negotiation`, `seasonal`, `supplier`, `override` | `agent_memory_vectors.entity_type` |
| `embedding_model_type` | `text-embedding-3-large`, `e5-large-v2` (base); **`all-MiniLM-L6-v2`** added by migration 22a | `agent_memory_vectors.embedding_model` |
| `model_name_type` | `intent_parsing`, `comparison_scoring`, `negotiation_strategy`, `memory_retrieval` | `model_governance_records.model_name` |
| `ai_provider_type` | `openai`, `anthropic` | `model_governance_records.provider` |
| `governance_status_type` | `active`, `review_triggered`, `deprecated` | `model_governance_records.status` |

**Known schema discrepancy:** `embedding_model_type` does not include `BAAI/bge-small-en-v1.5`, which is the actual model used by the data-normalizer service for agent memory writes. `ai_provider_type` does not include `ollama`, which is the actual primary LLM provider. Any INSERT that attempts to store the actual model or provider name will fail at the DB constraint unless the column uses TEXT instead of the ENUM. The DEFAULT on `agent_memory_vectors.embedding_model` remains `'text-embedding-3-large'` even after migration 22a — it was not updated.

(Source: database/sql/00_extensions_and_types.sql, 22_agent_memory_vector_dim.sql, code_findings in gap analysis -- Confidence: High)

---

## 4. Indexes

All 22 named B-tree/partial indexes are defined in `17_indexes.sql`. Additional indexes are created inline by `18_bpp_catalog_semantic_cache.sql`, `19b_erp_sync_records_outbox.sql`, `20_negotiation_schema.sql`, and `22_agent_memory_vector_dim.sql`.

(Source: database/sql/17_indexes.sql and per-migration index definitions -- Confidence: High)

### From 17_indexes.sql (22 B-tree / partial indexes)

| Index Name | Table | Columns | Type | Condition | Purpose |
|---|---|---|---|---|---|
| `idx_procurement_requests_requester` | `procurement_requests` | `(requester_id, created_at DESC)` | B-tree | — | Fast lookup of all requests by user, newest first |
| `idx_procurement_requests_status` | `procurement_requests` | `(status)` | B-tree partial | `status NOT IN ('confirmed','cancelled')` | Filter active-only requests without touching terminal rows |
| `idx_audit_events_request` | `audit_trail_events` | `(request_id, event_timestamp)` | B-tree partial | `request_id IS NOT NULL` | Primary traceability query: full audit chain for a request |
| `idx_audit_events_type` | `audit_trail_events` | `(event_type, event_timestamp)` | B-tree | — | SOX reporting queries filtered by event type and time window |
| `idx_audit_events_po` | `audit_trail_events` | `(po_id, event_timestamp)` | B-tree partial | `po_id IS NOT NULL` | Audit events linked to a specific PO |
| `idx_audit_events_splunk_pending` | `audit_trail_events` | `(splunk_indexed, event_timestamp)` | B-tree partial | `splunk_indexed = FALSE` | Batch SIEM push job — find un-indexed events |
| `idx_seller_offerings_query` | `seller_offerings` | `(query_id)` | B-tree | — | All offerings returned by a discovery query |
| `idx_seller_offerings_bpp` | `seller_offerings` | `(bpp_id)` | B-tree | — | All offerings from a given BPP |
| `idx_scored_offers_overridden` | `scored_offers` | `(user_overridden, scored_at)` | B-tree partial | `user_overridden = TRUE` | 30-day override-rate calibration query |
| `idx_purchase_orders_bpp` | `purchase_orders` | `(bpp_id, status)` | B-tree partial | `status NOT IN ('delivered','cancelled')` | Active orders per BPP for operations dashboard |
| `idx_purchase_orders_status` | `purchase_orders` | `(status, created_at DESC)` | B-tree | — | Status-filtered order listing |
| `idx_model_governance_name` | `model_governance_records` | `(model_name, evaluation_date DESC)` | B-tree | — | Latest evaluation per model name |
| `idx_model_governance_status` | `model_governance_records` | `(status)` | B-tree partial | `status <> 'deprecated'` | Active / under-review models only |
| `idx_bpp_network` | `bpp` | `(network_id)` | B-tree | — | Lookup BPPs by Beckn network ID |
| `idx_erp_sync_po` | `erp_sync_records` | `(po_id, sync_type)` | B-tree | — | ERP sync history for a PO grouped by operation |
| `idx_erp_sync_pending` | `erp_sync_records` | `(status, synced_at)` | B-tree partial | `status = 'pending'` | ERP outbox retry queue |
| `idx_discovery_queries_intent` | `discovery_queries` | `(beckn_intent_id, queried_at DESC)` | B-tree | — | All queries triggered by a beckn_intent, newest first |
| `idx_approval_decisions_status` | `approval_decisions` | `(status)` | B-tree partial | `status IN ('pending','escalated')` | Approval dashboard — actionable decisions only |
| `idx_approval_decisions_approver` | `approval_decisions` | `(approver_id, status)` | B-tree partial | `approver_id IS NOT NULL` | Approver inbox — open decisions per user |
| `idx_agent_memory_entity_type` | `agent_memory_vectors` | `(entity_type)` | B-tree | — | RAG retrieval routing by entity type |
| `idx_agent_memory_request` | `agent_memory_vectors` | `(source_request_id)` | B-tree partial | `source_request_id IS NOT NULL` | Vectors from a specific request |

Note: `idx_agent_memory_entity_type` and `idx_agent_memory_request` are listed in database/README.md as part of the 22 named indexes in 17_indexes.sql, but migration 22a also defines them inline (`idx_agent_memory_entity` and `idx_agent_memory_hnsw`) — the 22a versions may supersede or duplicate those in 17_indexes.sql. Both files use `CREATE INDEX IF NOT EXISTS` so there is no error on re-run.

### Migration-added indexes

| Index Name | Migration | Table | Columns | Type | Purpose |
|---|---|---|---|---|---|
| `hnsw_bpp_catalog_embedding_cosine` | `18_bpp_catalog_semantic_cache.sql` | `bpp_catalog_semantic_cache` | `(item_embedding vector_cosine_ops)` | HNSW m=16, ef_construction=64 | Cosine ANN search for Stage 3 item validation |
| `uq_erp_sync_idempotency` | `19b_erp_sync_records_outbox.sql` | `erp_sync_records` | `(idempotency_key)` | Unique partial | `WHERE idempotency_key IS NOT NULL` — at-most-once enqueue per (txn, vendor, operation) |
| `idx_erp_sync_due` | `19b_erp_sync_records_outbox.sql` | `erp_sync_records` | `(next_attempt_at)` | B-tree partial | `WHERE status IN ('pending','in_progress')` — outbox worker hot-path claim query |
| `idx_neg_round_txn` | `20_negotiation_schema.sql` | `negotiation_round` | `(transaction_id, round_no)` | B-tree | Replay access for negotiation rounds |
| `idx_neg_policy_txn` | `20_negotiation_schema.sql` | `negotiation_policy_decision` | `(transaction_id, decided_at)` | B-tree | Compliance queries by transaction |
| `idx_neg_policy_rule` | `20_negotiation_schema.sql` | `negotiation_policy_decision` | `(rule_violated, severity)` | B-tree | Compliance queries by guardrail rule |
| `idx_agent_memory_hnsw` | `22_agent_memory_vector_dim.sql` | `agent_memory_vectors` | `(embedding_vector vector_cosine_ops)` | HNSW m=16, ef_construction=64 | Sub-linear cosine ANN search for memory retrieval (<100ms target) |
| `idx_agent_memory_entity` | `22_agent_memory_vector_dim.sql` | `agent_memory_vectors` | `(entity_type)` | B-tree | Entity-type pre-filter |

---

## 5. pgvector Tables

### 5.1 `agent_memory_vectors`

The primary store for agent learning and supplier loyalty scoring.

(Source: database/sql/22_agent_memory_vector_dim.sql, services/data-normalizer/README.md -- Confidence: High)

| Attribute | Value |
|---|---|
| Vector column | `embedding_vector vector(384)` |
| Index | HNSW cosine (`hnsw (embedding_vector vector_cosine_ops)`), m=16, ef_construction=64 |
| Embedding model | BAAI/bge-small-en-v1.5 (fastembed ONNX, ~65 MB, no PyTorch dependency) |
| Similarity threshold | >= 0.75 (items below this score are excluded from retrieval results) |
| Top-k | 3 per query |
| ef_search at query time | 100 (set per session: `SET hnsw.ef_search = 100`) |
| Text stored | `"{item} ordered from {provider} at {price} {currency} delivery in {hours}h"` |
| Write path | orchestrator `_persist_memory()` (fire-and-forget `asyncio.create_task`) → POST `/normalize/memory/write` → data-normalizer → fastembed embed → INSERT |
| Read path | orchestrator `_fetch_memory_context(raw_query, limit=3, 5s timeout)` → POST `/normalize/memory/search` → pgvector HNSW ANN cosine → top-3 results |

**Scoring delta formula** applied to composite score after memory retrieval:

```
memory_delta(provider) = sum[ 0.03 × exp(−days_old × ln(2) / 90) ]
                         for each past PO from this provider
                         (max 5 orders considered, capped at ±0.10)
```

New providers receive delta = 0. Half-life is 90 days. This keeps the scoring bias bounded and time-decayed.

**Implementation vs. spec mismatch:**

| Aspect | Spec (00_extensions_and_types.sql / 15_agent_memory_vectors.sql) | Actual (migration 22a + CLAUDE.md) |
|---|---|---|
| Vector dimension | 3072 | 384 |
| Embedding model | text-embedding-3-large (OpenAI API) | BAAI/bge-small-en-v1.5 (local ONNX) |
| Primary store | Qdrant + pgvector mirror | pgvector only |
| Column DEFAULT | `'text-embedding-3-large'` (not updated by migration) | Should be `'all-MiniLM-L6-v2'` |

### 5.2 `bpp_catalog_semantic_cache`

Stage 3 BPP item existence validation cache, populated by IntentParser.

(Source: database/sql/18_bpp_catalog_semantic_cache.sql -- Confidence: High)

| Attribute | Value |
|---|---|
| Vector column | `item_embedding vector(1536)` |
| Index | HNSW cosine (`hnsw (item_embedding vector_cosine_ops)`), m=16, ef_construction=64 |
| Embedding model | all-MiniLM-L6-v2 (sentence-transformers, 384 dims) — the migration comment says `text-embedding-3-small (1536 dims)`, which is the spec value; as-built uses the local model |
| UNIQUE constraint | `(item_name, bpp_id)` — one entry per item per BPP |
| ef_search at query time | 100 (set per session) |

**Three-zone decision boundary:**

| Cosine similarity | Zone | Action |
|---|---|---|
| >= 0.92 | VALIDATED | Accept: item confirmed to exist in BPP catalog |
| 0.75 – 0.91 | AMBIGUOUS | Accept with lower confidence; may trigger MCP probe |
| < 0.75 | CACHE_MISS | Not found in semantic cache; falls through to MCP sidecar probe |

Note: the thresholds used in IntentParser code (VALIDATED >= 0.85, AMBIGUOUS >= 0.45) differ slightly from the SQL comment values above. The code values take precedence at runtime.

(Source: IntentParser/README.md -- Confidence: High)

**Two write paths:**

```
Path A (CatalogCacheWriter): on_discover callback fires
  → embed(item_name) via all-MiniLM-L6-v2
  → INSERT with source='bpp_publish', strategy='item_name_only'

Path B (MCPResultAdapter): successful MCP probe returns items
  → embed(item_name + " | " + join(descriptions)) via all-MiniLM-L6-v2
  → INSERT with source='mcp_feedback', strategy='item_name_and_specs'
```

Path B entries are higher quality (richer embedding context). `hit_count` and `last_seen_at` are updated on cache hit for eviction heuristics.

---

## 6. Key Placeholder Columns

Several columns exist to future-proof the schema for infrastructure that has not been deployed in Phases 1-3. They are populated with defaults and will be wired to real backends in Phase 4.

(Source: code_findings in gap analysis, database/sql/14_audit_trail_events.sql -- Confidence: High)

### 6.1 `audit_trail_events`

| Column | Type | Current behaviour | Planned behaviour (Phase 4) |
|---|---|---|---|
| `kafka_offset BIGINT NOT NULL` | BIGINT | Hardcoded to `0` in orchestrator `_persist_audit()` call (workflow.py comment: `TODO(kafka): real offset when topic is wired`) | Actual Kafka offset on `procurement.audit.v1` topic; enables event replay and correlation |
| `splunk_indexed BOOLEAN NOT NULL DEFAULT FALSE` | BOOLEAN | Never set to TRUE; no SIEM exporter deployed | Set to TRUE by a Splunk/ServiceNow batch consumer after the event is indexed |
| `retention_until TIMESTAMP NOT NULL DEFAULT (NOW() + INTERVAL '7 years')` | TIMESTAMP | Populated correctly; no deletion job runs against it | Nightly archival job will DELETE rows where `retention_until < NOW()` |
| `reasoning_payload JSONB NOT NULL DEFAULT '{}'` | JSONB | Populated by orchestrator at every audit write point with LLM step data | When LangSmith is wired (Phase 4), this column will also carry per-call LangSmith trace IDs |
| `actor_id UUID → users` | UUID nullable | NULL for all autonomous agent decisions; set when a human approves/overrides | No change — NULL for agent actions is the intended design |

### 6.2 `erp_sync_records` outbox columns (added by migration 19b)

| Column | Purpose |
|---|---|
| `idempotency_key VARCHAR(128)` | `sha256(transaction_id \| vendor \| sync_type)` — forwarded as `Idempotency-Key` header to SAP/Oracle |
| `attempts INT DEFAULT 0` | Total push attempts; row moves to DLQ when `status='failed' AND attempts >= MAX_ATTEMPTS` |
| `next_attempt_at TIMESTAMPTZ DEFAULT NOW()` | Earliest wall-clock for retry; bumped by exponential backoff on transient failure (schedule: 5, 30, 120, 600, 3600 seconds) |
| `lease_until TIMESTAMPTZ` | SET by worker on claim via `FOR UPDATE SKIP LOCKED`; another worker may reclaim if expired |
| `worker_id VARCHAR(64)` | `hostname:pid` or Kubernetes pod name; diagnostic only |
| `last_error TEXT` | Last exception message from a failed push attempt |
| `payload JSONB` | Vendor-neutral `NormalizedPO` JSON snapshot at enqueue time; enables stateless retry by any worker replica |
| `updated_at TIMESTAMPTZ DEFAULT NOW()` | Outbox row mutation timestamp |

---

## 7. Redis Schema

Redis 7 is used for two purposes: Beckn async discovery decoupling (ADR-0001) and ONIX adapter response caching. There is no persistent data model — all entries are ephemeral.

(Source: docs/architecture/decisions/0001-use-redis-pubsub-for-async-beckn-responses.md, services/beckn-bap-client/README.md, config/README.md -- Confidence: High)

### 7.1 Beckn Discovery Pub/Sub

```
Channel pattern:  beckn_results:{transaction_id}
```

| Property | Value |
|---|---|
| Pattern | Pub/Sub channel (not a key — no TTL, no persistence) |
| Publisher | `beckn-bap-client` `/on_discover` handler — publishes the raw `on_discover` ONIX callback payload |
| Subscribers | `mcp-sidecar` (`bap_client.py` subscribes before firing POST /discover); orchestrator's `CallbackCollector` (notified via the dual-path dual-publish) |
| Message format | Raw JSON of the Beckn `on_discover` callback payload (`message.catalogs[]` in Beckn v2 flat-resource wire format) |
| Lifetime | Until the subscriber reads the message; no explicit TTL (channel ceases to exist once un-subscribed) |

**Protocol (ADR-0001 five-step sequence):**

```
1. mcp-sidecar generates transaction_id (UUID)
2. mcp-sidecar SUBSCRIBE beckn_results:{transaction_id}  ← must happen before step 3
3. mcp-sidecar asyncio.create_task(POST /discover {transaction_id, ...})  ← fire-and-forget
4. beckn-bap-client /on_discover handler: PUBLISH beckn_results:{transaction_id} <payload>
5. mcp-sidecar subscriber receives payload within REDIS_RESULT_TIMEOUT (default 15s)
```

If no message arrives within `REDIS_RESULT_TIMEOUT`, the sidecar returns `{"found": false, ...}`. The subscriber must be created before the request is fired to avoid a race between the PUBLISH and SUBSCRIBE.

### 7.2 ONIX Adapter Response Cache

```
Key pattern:  (managed internally by the fidedocker/onix-adapter image)
```

| Property | Value |
|---|---|
| Purpose | ONIX adapter caches Beckn protocol responses to avoid redundant network calls |
| TTL | 15 minutes (confirmed in CLAUDE.md "Redis 7 (Pub/Sub broker + ONIX cache)") |
| Publisher / Manager | `onix-bap` Go process |
| Consumer | `onix-bap` itself (cache hit avoids re-calling the Beckn network) |

The exact key format is internal to the ONIX adapter image. The REDIS_ADDR env var (`redis:6379`) points both `onix-bap` and `onix-bpp` to the same Redis instance.

### 7.3 Negotiation Engine Channel

```
Channel pattern:  beckn_on_select_results
```

| Property | Value |
|---|---|
| Pattern | Pub/Sub channel |
| Publisher | `demo-gateway` — after calling SupplierAgent (Claude proxy at :8012) and receiving a supplier response, publishes to this channel |
| Subscriber | `negotiation_engine` — `OnSelectListener` subscribes and calls `graph.ainvoke(Command(resume=payload))` to resume the parked LangGraph buyer graph |
| Purpose | Async resume of a LangGraph negotiation state machine that parked at `wait_for_async_callback` |
| Env var | `BECKN_ON_SELECT_CHANNEL` (negotiation_engine) / `REDIS_ON_SELECT_CHANNEL` (demo-gateway) both default to `beckn_on_select_results` |

### 7.4 Redis Connection

| Service | Env var | Docker Compose value |
|---|---|---|
| `beckn-bap-client` | `REDIS_URL` | `redis://redis:6379` |
| `mcp-sidecar` (local) | `REDIS_URL` | `redis://localhost:6379` (must be real env var, not just .env) |
| `onix-bap` / `onix-bpp` | `REDIS_ADDR` | `redis:6379` |
| `erp-adapter` | `REDIS_URL` | `redis://redis:6379` |
| `negotiation_engine` | `REDIS_URL` | `redis://redis:6379/0` |
| `demo-gateway` | `REDIS_URL` | `redis://redis:6379/0` |
| `orchestrator` | `REDIS_URL` | `""` (disabled by default; enable for WebSocket push tracking) |
