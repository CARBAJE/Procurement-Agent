# Glossary — Agentic AI Procurement Agent on Beckn Protocol

Alphabetically ordered reference for all domain-specific terms, architectural concepts, and database identifiers used in this project. Each entry gives a single-sentence definition followed by a cross-reference to the document where the concept is explained in depth.

For system context see [Architecture](ARCHITECTURE.md). For technology choices see [Components](COMPONENTS.md). For why each major decision was made see [System Design](SYSTEM_DESIGN.md).

---

## A

**ACK**
The synchronous HTTP 200 response that the ONIX adapter returns immediately to any Beckn `POST` (e.g., `/discover`, `/select`) to acknowledge receipt; it contains no catalog or order data — the real payload arrives later via a separate `on_*` webhook callback. See [Architecture](ARCHITECTURE.md) §3 (Beckn Protocol Integration).

**advisory mode**
An execution mode (set via `PROCUREMENT_EXECUTION_MODE=advisory`) in which the agent surfaces ranked supplier options to the buyer but takes no autonomous Beckn action; the buyer makes the final selection manually in the frontend. See [Architecture](ARCHITECTURE.md) §5 (Orchestrator Pipeline).

**agent_memory_vector** (table: `agent_memory_vectors`)
A PostgreSQL table storing 384-dimensional HNSW-indexed cosine vectors that encode past procurement decisions, enabling the orchestrator to apply time-decayed supplier loyalty bonuses when scoring future offers; embeddings are produced by the `BAAI/bge-small-en-v1.5` model via fastembed but the `embedding_model` column stores the proxy label `all-MiniLM-L6-v2` due to an ENUM constraint gap. See [Components](COMPONENTS.md) §4 (Embedding Models).

**AND-token matching**
The catalog-matching algorithm in sim-bpp that tokenises a discovery query, discards tokens absent from the catalog vocabulary (e.g., quantities, city names), and then requires that **all** remaining tokens appear in a candidate item's name or keywords before the item is returned — preventing false-positive matches on over-broad queries. See [System Design](SYSTEM_DESIGN.md) §AND-Token Catalog Matching.

**ANN (Approximate Nearest Neighbor)**
A vector-search technique that returns the closest embeddings to a query vector in sub-linear time by trading exact precision for speed; this project uses pgvector's HNSW index for ANN over 384-dimensional cosine vectors in the `bpp_catalog_semantic_cache` and `agent_memory_vectors` tables. See [Components](COMPONENTS.md) §4 (Embedding Models).

**asyncio.create_task**
The Python asyncio function used project-wide to schedule a coroutine on the running event loop without blocking the caller; all non-critical side-effect calls (persistence writes, the Beckn `/discover` POST inside the MCP sidecar) are wrapped in `asyncio.create_task` rather than `await`-ed to keep the critical latency path free. See [System Design](SYSTEM_DESIGN.md) §asyncio-First + Fire-and-Forget.

**audit_trail_event** (table: `audit_trail_events`)
A PostgreSQL append-only table that records every procurement lifecycle event (nine event types including `request_received`, `intent_parsed`, `discovery_complete`, `order_confirmed`) with a `retention_until` timestamp, `kafka_offset` placeholder, `splunk_indexed` flag, and a `reasoning_payload` JSONB column for LLM trace data; designed for SOX 404 compliance with a 7-year retention target. See [Architecture](ARCHITECTURE.md) §6 (Main Happy-Path Sequence).

**autonomous mode**
An execution mode (set via `PROCUREMENT_EXECUTION_MODE=autonomous`) in which the orchestrator commits a Beckn order automatically when the order value falls within the requester's pre-configured approval threshold and the ERP budget gate returns `allowed: true`. See [Architecture](ARCHITECTURE.md) §5 (Orchestrator Pipeline).

---

## B

**BAP (Beckn Application Platform)**
The buyer-side protocol participant in the Beckn network that initiates the procurement lifecycle (`discover → select → init → confirm → status`) and receives `on_*` callbacks from BPPs; in this project the BAP role is fulfilled by the `beckn-bap-client` service (:8002) routed through `onix-bap` (:8081). See [Architecture](ARCHITECTURE.md) §3 (ONIX Adapter Pair).

**beckn_network**
The Docker Compose bridge network (`driver: bridge`) on which all 18 containerised services communicate using Docker DNS names (e.g., `http://data-normalizer:8006`); services reach the native-host PostgreSQL via `host.docker.internal:5432`. See [Architecture](ARCHITECTURE.md) §2 (Logical Layers).

**Beckn Protocol**
An open, interoperable, transaction-layer protocol for decentralised commerce that defines a standard lifecycle (`discover → select → init → confirm → status → track`) between a BAP (buyer) and a BPP (seller) mediated by network-registered ONIX adapters; this project implements Beckn v2.0.0. See [Architecture](ARCHITECTURE.md) §3 (Beckn Protocol Integration).

**BecknIntent**
The canonical Pydantic v2 model (`shared/models.BecknIntent`) produced by IntentParser Stage 2 that encodes a natural-language procurement request as a structured object with strictly typed fields: `item` (string), `descriptions[]` (list), `quantity` (int), `location_coordinates` (`"lat,lon"` decimal string), `delivery_timeline` (int hours), and `budget_constraints` (`BudgetConstraints`). See [Architecture](ARCHITECTURE.md) §4 (IntentParser 3-Stage Pipeline).

**BPP (Beckn Provider Platform)**
The seller-side protocol participant that receives Beckn discovery and order requests, returns catalogs and order confirmations via `on_*` callbacks, and advances the fulfillment lifecycle; in development this role is played by sim-bpp (:3002) routed through `onix-bpp` (:8082). See [Architecture](ARCHITECTURE.md) §3 (ONIX Adapter Pair).

**BudgetConstraints**
A typed Pydantic v2 sub-model (`{"max": float, "min": float}`) that is a required field of `BecknIntent`; using a typed model (rather than a raw string) enforces that budget values are numeric and prevents downstream services from needing to parse free-form budget text. See [Architecture](ARCHITECTURE.md) §4 (IntentParser 3-Stage Pipeline).

---

## C

**Circuit breaker**
A fault-isolation pattern (implemented via the `pybreaker` library in `erp-adapter`) that trips to OPEN after five consecutive vendor API failures, causing all subsequent calls to fail immediately rather than blocking for the 800 ms timeout; it resets to CLOSED automatically after 60 seconds, and its per-vendor state is exposed on `GET /readyz`. See [System Design](SYSTEM_DESIGN.md) §Per-Vendor Circuit Breakers.

**conda environment**
The Conda virtual environment (conventionally named `infosys_project`) used to run the two unbundled local Python services — IntentParser (:8001) and mcp-sidecar (:3000) — outside of Docker; both services must be activated within this environment before running `uvicorn`. See [Architecture](ARCHITECTURE.md) §2 (Logical Layers).

**cosine similarity**
The similarity metric used for all vector comparisons in the project — computed as the dot product of two L2-normalised embedding vectors — with threshold bands of `>= 0.85` (VALIDATED, cache hit), `0.45–0.85` (AMBIGUOUS, MCP sidecar probe), and `< 0.45` (CACHE_MISS, recovery flow) in IntentParser Stage 3. See [Components](COMPONENTS.md) §4.2 (Similarity Thresholds).

---

## D

**DeDi registry**
The Decentralised Distributed registry used in a production Beckn network to resolve BPP endpoint URLs from provider identifiers; bypassed in this project by setting `targetType: url` in all four ONIX routing YAML files, which makes the full Beckn flow self-contained within the Docker bridge network. See [System Design](SYSTEM_DESIGN.md) §DeDi Registry Bypass.

**DiscoverOffering**
The normalised representation of a single BPP catalog item produced by `catalog-normalizer` (:8005); `beckn-bap-client` owns its own internal `DiscoverOffering` model distinct from the shared one — the catalog-normalizer converts raw `on_discover` catalog payloads into this typed structure before scoring. See [Architecture](ARCHITECTURE.md) §6 (Main Happy-Path Sequence).

---

## E

**ED25519**
The elliptic-curve digital signature algorithm used by `onix-bap` to sign every outbound Beckn request via the `signer.so` plugin compiled into the `fidedocker/onix-adapter` Go image; the ONIX schema validator is pinned to commit `d43ec30d` because a later upstream commit introduced a `$ref` resolution bug that broke ED25519 signature validation. See [System Design](SYSTEM_DESIGN.md) §ONIX Schema Validator Pin.

**erp_sync_record(s)** (table: `erp_sync_records`)
A PostgreSQL outbox table (migration `19b_erp_sync_records_outbox.sql`) where the orchestrator writes a pending PO push record atomically with the `purchase_orders` insert; a background worker in `erp-adapter` polls `WHERE status = 'pending'` using `FOR UPDATE SKIP LOCKED`, calls the vendor ERP API, and updates the row status — effectively replacing a Kafka producer/consumer for the ERP event bus in Phases 1–3. See [System Design](SYSTEM_DESIGN.md) §Outbox Pattern for ERP PO Push.

**ERPAdapter Protocol**
A `typing.Protocol` (structural subtype) in `erp-adapter` that defines six methods (`check_budget`, `push_po`, `get_po_status`, `evaluate_policy`, `get_health`, `get_vendor_name`) that every vendor adapter (SAP, Oracle, mock) must implement; the active adapter(s) are selected at startup via the `ERP_VENDORS` environment variable without requiring changes to the orchestrator or budget-gate logic. See [System Design](SYSTEM_DESIGN.md) §Vendor-Neutral ERPAdapter Protocol.

---

## F

**fastembed**
A Python library that runs ONNX-format embedding models without a PyTorch dependency; used by `data-normalizer` to generate 384-dimensional `BAAI/bge-small-en-v1.5` embeddings for the `agent_memory_vectors` table, deliberately avoiding adding the ~1.5 GB PyTorch package to the data-normalizer container image. See [Components](COMPONENTS.md) §4 (Embedding Models).

**fire-and-forget**
The project-wide pattern where non-critical side-effect coroutines (audit writes, memory writes, ERP sync records) are launched with `asyncio.create_task` and allowed to run concurrently without blocking the orchestrator's critical-path response; these tasks never raise exceptions to the caller and are given a 5-second timeout. See [System Design](SYSTEM_DESIGN.md) §asyncio-First + Fire-and-Forget.

---

## H

**HITL (Human-in-the-Loop)**
A general design pattern where an automated agent pauses and surfaces a decision to a human before proceeding; in this project it appears in two contexts: the `hitl` execution mode (human approves a Beckn commit) and as a LangGraph interrupt node in the negotiation engine when a counter-offer gap exceeds the policy threshold. See [Architecture](ARCHITECTURE.md) §5.2 (Negotiation Engine LangGraph).

**HITL mode**
An execution mode (set via `PROCUREMENT_EXECUTION_MODE=hitl`) in which the orchestrator surfaces the top-ranked offer to the buyer for manual approval before issuing the Beckn `select → init → confirm` sequence; the pipeline pauses at `POST /approvals/{id}/decide`. See [Architecture](ARCHITECTURE.md) §5 (Orchestrator Pipeline).

**HMAC**
HMAC-SHA256 webhook verification used by `erp-adapter` to authenticate inbound ERP vendor callbacks; each vendor maintains a primary secret (`{VENDOR}_WEBHOOK_HMAC_SECRET`) and a rotation secret (`{VENDOR}_WEBHOOK_HMAC_SECRET_NEXT`) so that secret rotation is zero-downtime. See [System Design](SYSTEM_DESIGN.md) §Dual-Secret HMAC Rotation.

**HNSW (Hierarchical Navigable Small World)**
The graph-based ANN index type used for both pgvector tables (`bpp_catalog_semantic_cache` and `agent_memory_vectors`); the agent memory table uses `ef_search=100` for higher recall during similarity retrieval, while the catalog cache index uses pgvector defaults. See [Components](COMPONENTS.md) §7.3 (Database Schema Summary).

---

## I

**IntentParser**
The three-stage NLP pipeline (FastAPI service, :8001) that converts a natural-language purchase request into a validated `BecknIntent`; Stage 1 classifies intent via qwen3:8b, Stage 2 extracts the `BecknIntent` struct via qwen3 (complexity-routed), and Stage 3 validates the item against the pgvector semantic cache and MCP sidecar. See [Architecture](ARCHITECTURE.md) §4 (IntentParser 3-Stage Pipeline).

---

## K

**kafka_offset**
A `BIGINT` placeholder column present in both `audit_trail_events` and `erp_sync_records` tables that stores `NULL` in Phases 1–3; it is reserved as a non-breaking migration path for Phase 4 when a real Kafka producer is wired and each record needs its corresponding Kafka topic offset for exactly-once semantics. See [Components](COMPONENTS.md) §6 (Implementation vs Original Spec).

---

## L

**LangGraph**
An open-source library from LangChain that models agent workflows as directed `StateGraph` instances with typed state, conditional edges, and durable checkpointing; used in this project for the negotiation engine's buyer/supplier negotiation graph and formerly prototyped in Bap-1 for the orchestrator. See [Architecture](ARCHITECTURE.md) §5 (LangGraph State Machines).

---

## M

**MCP (Model Context Protocol)**
An open protocol that exposes tool functions to LLM agents over a transport layer (HTTP SSE in this project); IntentParser Stage 3 connects to the mcp-sidecar (:3000) as an MCP client, calling the `search_bpp_catalog` tool to validate procurement items against live BPP catalogs. See [Architecture](ARCHITECTURE.md) §4 (IntentParser 3-Stage Pipeline).

**MLflow**
An open-source ML lifecycle platform used by the `ComparativeAndScoreing` MLOps sub-stack (`docker-compose.mlops.yaml`) for experiment tracking, model registry, and artifact storage; the prediction-api retrieves the registered RankNet model from MLflow at startup. See [Components](COMPONENTS.md) §1 (Full Technology Matrix).

---

## N

**NDCG@5 (Normalised Discounted Cumulative Gain at rank 5)**
The ranking quality metric used to evaluate the comparative-scoring service; it measures how well the model ranks the most relevant supplier offers in the top five positions, with a discount applied to lower-ranked positions — the Phase 2 ML target is NDCG@5 ≥ 0.85. See [Components](COMPONENTS.md) §3.1 (Models in Use).

---

## O

**on_confirm**
The Beckn asynchronous callback (`POST /bap/receiver/on_confirm`) that the BPP sends to the BAP after a `confirm` request is processed; it carries the final `order_id` and `Contract.status.code = "ACTIVE"` — the valid enum values are `DRAFT | ACTIVE | CANCELLED | COMPLETE`; ONIX rejects `"CONFIRMED"`. See [Architecture](ARCHITECTURE.md) §6 (Main Happy-Path Sequence).

**on_discover**
The Beckn asynchronous callback (`POST /on_discover`) that delivers the BPP catalog payload to the BAP after a `discover` request; it is routed to a dedicated endpoint in `beckn-bap-client` (not the generic `/bap/receiver`) so the handler can both publish to the Redis `beckn_results:{transaction_id}` channel and notify the orchestrator's `CallbackCollector` simultaneously. See [System Design](SYSTEM_DESIGN.md) §on_discover Split Routing.

**on_init**
The Beckn asynchronous callback (`POST /bap/receiver/on_init`) sent by the BPP after an `init` request; it carries payment terms that the orchestrator must relay to the buyer before issuing the `confirm` step. See [Architecture](ARCHITECTURE.md) §6 (Main Happy-Path Sequence).

**on_select**
The Beckn asynchronous callback (`POST /bap/receiver/on_select`) sent by the BPP after a `select` request confirming item availability and updated pricing; in the negotiation engine, receiving `on_select` resumes the LangGraph buyer graph via `OnSelectListener` on the `beckn_on_select_results` Redis channel. See [Architecture](ARCHITECTURE.md) §5.2 (Negotiation Engine LangGraph).

**ONIX adapter**
The Go binary (`fidedocker/onix-adapter`) that acts as the Beckn protocol middleware between the BAP/BPP services and the network; it applies a middleware chain of routing, ED25519 signing, and schema validation on every Beckn message, and is deployed as two instances — `onix-bap` (:8081) and `onix-bpp` (:8082) — pinned to commit `d43ec30d`. See [System Design](SYSTEM_DESIGN.md) §ONIX Schema Validator Pin.

**orchestrator**
The FastAPI + aiohttp pipeline state machine (service `:8004`) that sequences the five procurement steps — intent parsing, discovery, scoring, ERP budget gate, and Beckn `select → init → confirm` — and exposes two flows: `POST /run` (end-to-end) and `POST /compare` + `POST /commit` (two-phase with human review). See [Architecture](ARCHITECTURE.md) §5.1 (Orchestrator Pipeline).

**Outbox pattern**
The transactional messaging pattern used by `erp-adapter` to guarantee that every committed purchase order eventually triggers a PO push to the vendor ERP without requiring a Kafka broker; the orchestrator writes a row to `erp_sync_records` in the same PostgreSQL transaction as the `purchase_orders` insert, and a background worker picks it up via `FOR UPDATE SKIP LOCKED`. See [System Design](SYSTEM_DESIGN.md) §Outbox Pattern for ERP PO Push.

---

## P

**pgvector**
A PostgreSQL extension (version 0.7.0) that adds a native `vector(n)` column type and HNSW / IVFFlat indexes for approximate nearest-neighbour search directly inside PostgreSQL 16; used here to store 384-dimensional BPP catalog embeddings and agent memory vectors, eliminating the need for a separate Qdrant deployment. See [System Design](SYSTEM_DESIGN.md) §pgvector Instead of Qdrant.

**Phase2Scorer**
The ML-based supplier ranking component in `comparative-scoring` (:8003) that calls the optional `prediction-api` RankNet model (from `docker-compose.mlops.yaml`) to rank `DiscoverOffering` items by predicted relevance; when the `prediction-api` is unavailable, `comparative-scoring` falls back to the Phase 1 minimum-price heuristic. See [Components](COMPONENTS.md) §1 (Full Technology Matrix).

**procurement_request** (table: `procurement_requests`)
The first PostgreSQL record written at the start of every pipeline run, created by `data-normalizer`'s `POST /normalize/request` endpoint before intent parsing begins; all subsequent records (intent, discovery, scoring, order) reference this row's primary key, forming the audit trail root. See [Architecture](ARCHITECTURE.md) §6 (Main Happy-Path Sequence).

**purchase_order** (table: `purchase_orders`)
The PostgreSQL record created by `data-normalizer` after a successful Beckn `confirm` callback, capturing the `order_id`, `order_state`, vendor details, and total amount; it is the anchor for `erp_sync_records` outbox rows and for audit trail events of type `order_confirmed`. See [Architecture](ARCHITECTURE.md) §6 (Main Happy-Path Sequence).

---

## Q

**query broadening**
The Stage 3 recovery technique that progressively simplifies a failed procurement query (strip modifiers, synonyms, drop constraints) to find any BPP catalog match; implemented in `IntentParser/recovery.py` via a regex-based simplifier first, then optionally Claude Sonnet 4.6 via `ANTHROPIC_API_KEY` as a last resort. See [Architecture](ARCHITECTURE.md) §4 (IntentParser 3-Stage Pipeline).

---

## R

**RankNet**
A pairwise learning-to-rank neural network model (PyTorch `nn.Linear`) trained in the `ComparativeAndScoreing` MLOps sub-stack to predict supplier offer preference from features such as price, delivery time, and rating; served by the optional `prediction-api` and consumed by the `Phase2Scorer` in `comparative-scoring`. See [Components](COMPONENTS.md) §1 (Full Technology Matrix).

**reasoning_payload**
A `JSONB` column in `audit_trail_events` that stores LLM trace data (model name, token counts, prompt/completion excerpts) for every LLM call made during a pipeline run; populated in Phases 1–3 as a local substitute for LangSmith tracing, which is deferred to Phase 4. See [Components](COMPONENTS.md) §6 (Implementation vs Original Spec).

**recovery flow**
The IntentParser sub-pipeline that activates when Stage 3 validation returns `not_found`; it calls `broaden_procurement_query`, retries Stage 3 once with the broadened query, and if still not found, invokes three stub functions (`log_unmet_demand`, `notify_buyer_no_stock`, `trigger_open_rfq_flow`) that are currently no-op logger calls pending Phase 4 implementation. See [Architecture](ARCHITECTURE.md) §4 (IntentParser 3-Stage Pipeline).

**Redis pub/sub**
The message-passing mechanism used to decouple the asynchronous `on_discover` Beckn callback from the synchronous MCP sidecar response path; the sidecar subscribes to `beckn_results:{transaction_id}` before firing the discover request, and `beckn-bap-client` publishes the catalog payload to the same channel when the callback arrives — eliminating the asyncio deadlock described in ADR-0001. See [System Design](SYSTEM_DESIGN.md) §ADR-0001.

**retention_until**
A `TIMESTAMPTZ` column in `audit_trail_events` set to `NOW() + INTERVAL '7 years'` at insert time, marking when the record may be archived or deleted; no automated enforcement job exists in Phases 1–3 — the column is a placeholder for a Phase 4 nightly cleanup cron job required for SOX 404 compliance. See [Components](COMPONENTS.md) §6 (Implementation vs Original Spec).

**RFQ (Request for Quotation)**
A formal procurement document sent to suppliers when no matching item is found in the Beckn network; triggered in the recovery flow stub `trigger_open_rfq_flow` — currently a no-op logger call that would in a production system generate and dispatch an RFQ to registered BPPs via the Beckn `init` action with open terms. See [Architecture](ARCHITECTURE.md) §4 (IntentParser 3-Stage Pipeline).

---

## S

**sentence-transformers**
A Python library (PyTorch-backed) that provides pre-trained transformer-based text embedding models; used by IntentParser Stage 3 and the mcp-sidecar to encode procurement queries and catalog item descriptions into 384-dimensional `all-MiniLM-L6-v2` vectors for cosine similarity search in pgvector. See [Components](COMPONENTS.md) §4 (Embedding Models).

**sim-bpp**
The local Node.js BPP simulator (:3002) that replaced the `fidedocker/sandbox-2.0` image; it hot-reloads `catalog.json` at request time, implements all 10 Beckn actions, uses AND-token catalog matching to reduce false positives, and — when `SIM_BPP_AUTO_ADVANCE=true` — automatically advances confirmed orders through the fulfillment lifecycle publishing Kafka events at each transition. See [System Design](SYSTEM_DESIGN.md) §sim-bpp Replacing sandbox-2.0.

**splunk_indexed**
A `BOOLEAN` placeholder column in `audit_trail_events` (default `FALSE`) that indicates whether a record has been exported to a Splunk SIEM; no Splunk exporter is wired in Phases 1–3 — the column is reserved for a Phase 4 Kafka-to-Splunk consumer. See [Components](COMPONENTS.md) §6 (Implementation vs Original Spec).

**SSE (Server-Sent Events)**
The HTTP streaming transport used by the MCP protocol in this project; the mcp-sidecar exposes its tool functions (including `search_bpp_catalog`) over an SSE endpoint at `http://localhost:3000/sse`, and IntentParser Stage 3 connects as an MCP SSE client. See [Components](COMPONENTS.md) §1 (Full Technology Matrix).

---

## T

**targetType: url**
The ONIX routing configuration value set in all four routing YAML files (`config/generic-routing-BAPCaller.yaml`, etc.) that instructs the ONIX adapter to route Beckn messages directly to a configured URL rather than performing a DeDi registry lookup; enables a fully offline Beckn flow inside the Docker bridge network and can be reverted to `bap`/`bpp` with a single-line change for production network registration. See [System Design](SYSTEM_DESIGN.md) §DeDi Registry Bypass.
