# Architecture

## 1. Overall Pattern

The system is an event-driven microservices monorepo that translates natural-language purchase requests into validated Beckn Protocol v2.0.0 transactions. Two local Python services run outside Docker (IntentParser on :8001, mcp-sidecar on :3000); sixteen containers run on a bridged Docker network called `beckn_network`. (Source: CLAUDE.md -- Confidence: High)

Redis Pub/Sub is the critical async decoupling layer. Beckn discovery is inherently asynchronous — `POST /discover` returns only an ACK and the catalog arrives later via an `on_discover` webhook. Rather than hold an HTTP connection open (which blocks the asyncio event loop), the system subscribes to a per-transaction Redis channel before firing the request and resolves the channel when the callback arrives. This is the central architectural decision in the codebase. (Source: docs/architecture/decisions/0001-use-redis-pubsub-for-async-beckn-responses.md -- Confidence: High)

The single formal ADR in the repository (ADR-0001) covers this Redis Pub/Sub pattern. Major technology substitutions from the original spec — pgvector over Qdrant, qwen3 over GPT-4o, sim-bpp over sandbox-2.0, PostgreSQL outbox over Kafka — are recorded informally in `KnowledgeBase/project_scaffold/implementation_deviations.md` rather than as additional ADRs. (Source: KnowledgeBase/project_scaffold/implementation_deviations.md -- Confidence: High)

---

## 2. Logical Layers

The architecture has five logical layers from presentation to storage.

| Layer | Services | Technology |
|---|---|---|
| **Presentation** | frontend :3000 | Next.js 13.5.6, Tailwind, shadcn/ui, Radix UI |
| **Orchestration** | orchestrator :8004, demo-gateway :8015 | FastAPI, LangGraph |
| **Core Services** | intention-parser :8001, beckn-bap-client :8002, catalog-normalizer :8005, comparative-scoring :8003, erp-adapter :8007, erp-mock :8008, analytics :8009, notification-dispatcher :8010, negotiation-engine :18004 | FastAPI, aiohttp, Python 3.11+ |
| **Protocol Adapters** | onix-bap :8081, onix-bpp :8082, sim-bpp :3002, mcp-sidecar :3000 | Go (ONIX), Node.js (sim-bpp), Python FastMCP (mcp-sidecar) |
| **Persistence** | PostgreSQL :5432 (native host), Redis :6379, pgvector extension | PostgreSQL 16 + pgvector 0.7.0, Redis 7, asyncpg |

(Source: CLAUDE.md, docker-compose.yml -- Confidence: High)

The `claude_openai_proxy` service (:8012) runs as a loopback-only host process (not Dockerized) wrapping the Claude Code CLI as an OpenAI-compatible endpoint. Two services depend on it at runtime: `negotiation-engine` (via `NEGOTIATION_OPENAI_BASE_URL=http://host.docker.internal:8012/v1`) and `demo-gateway` (via `OLLAMA_BASE_URL=http://host.docker.internal:8012/v1`). It is absent from `docker-compose.yml` and requires manual startup. (Source: services/claude_openai_proxy/README.md, docker-compose.yml -- Confidence: High)

```mermaid
flowchart TD
    subgraph Presentation
        FE["frontend :3000\nNext.js 13"]
    end

    subgraph Orchestration
        ORCH["orchestrator :8004\nFastAPI + LangGraph"]
        DG["demo-gateway :8015\nFrontend BFF"]
    end

    subgraph CoreServices
        IP["intention-parser :8001"]
        BAP["beckn-bap-client :8002"]
        CN["catalog-normalizer :8005"]
        CS["comparative-scoring :8003"]
        DN["data-normalizer :8006"]
        ERP["erp-adapter :8007"]
        ANA["analytics :8009"]
        NE["negotiation-engine :18004\nLangGraph"]
        ND["notification-dispatcher :8010\nKafka consumer"]
    end

    subgraph Protocol
        ONIX_BAP["onix-bap :8081\nGo ED25519"]
        ONIX_BPP["onix-bpp :8082\nGo"]
        SIMBPP["sim-bpp :3002\nNode.js"]
        MCP["mcp-sidecar :3000\nMCP SSE"]
    end

    subgraph Persistence
        PG[("PostgreSQL :5432\n+ pgvector")]
        REDIS[("Redis :6379")]
        KAFKA[("Kafka :9092")]
    end

    subgraph HostServices
        PROXY["claude_openai_proxy :8012\nloopback only"]
    end

    FE -->|wizard API| ORCH
    ORCH --> IP
    ORCH --> BAP
    ORCH --> CS
    ORCH --> DN
    ORCH --> ERP
    ORCH --> DG
    DG --> NE
    NE --> PROXY
    DG --> PROXY
    BAP -->|discover| ONIX_BAP
    ONIX_BAP --> ONIX_BPP
    ONIX_BPP --> SIMBPP
    SIMBPP -->|on_discover| ONIX_BPP
    ONIX_BPP -->|on_discover| BAP
    BAP -->|catalog| CN
    IP -->|MCP SSE| MCP
    MCP --> BAP
    BAP -->|PUBLISH| REDIS
    MCP -->|SUBSCRIBE| REDIS
    NE -->|PUBLISH resume| REDIS
    ORCH --> ANA
    ERP --> KAFKA
    SIMBPP --> KAFKA
    KAFKA --> ND
    DN --> PG
    NE --> PG
    ERP --> PG
    ANA --> PG
```

**Port collision notes.** The `orchestrator` container maps both `:8000` and `:8004` on the host (`:8000` matches the default `BAP_URL` used by the Next.js frontend; `:8004` is used for direct testing). The `negotiation-engine` container uses `:18004` on the host to avoid colliding with orchestrator's `:8004`. The `discovery_engine` service at `services/discovery_engine/` is fully implemented but has no entry in `docker-compose.yml` and is not called by any other service — it is an orphaned implementation of multi-network fan-out discovery. (Source: docker-compose.yml, services/discovery_engine/README.md -- Confidence: High)

---

## 3. Beckn Protocol Integration

### 3.1 ONIX Adapter Pair

All Beckn traffic passes through two Go adapters from the `fidedocker/onix-adapter` image. Direct BPP connections are forbidden. (Source: CLAUDE.md -- Confidence: High)

| Adapter | Port | Role | Middleware chain |
|---|---|---|---|
| `onix-bap` | 8081 | BAP-side | `validateSign` → `addRoute` → `validateSchema` (receiver); `addRoute` → `sign` → `validateSchema` (caller) |
| `onix-bpp` | 8082 | BPP-side | Same pattern, inverted direction |

Six YAML files in `config/` wire the routing. Key rules:

- Target URLs in routing YAMLs must **not** include the action name — ONIX appends it automatically. `http://sim-bpp:3002/api/webhook` + action `discover` → `http://sim-bpp:3002/api/webhook/discover`. Including the action causes a 404. (Source: CLAUDE.md, config/README.md -- Confidence: High)
- All routing uses `targetType: url` to bypass the DeDi registry, enabling full Beckn flow inside the Docker network. (Source: config/README.md -- Confidence: High)
- The ONIX schema validator is pinned to commit `d43ec30d`. Later commits introduced a `$ref` resolution bug in `SignatureHeader`. Do not upgrade without an end-to-end signing test. (Source: config/README.md -- Confidence: High)
- `on_discover` uses a split routing rule: it routes to `http://beckn-bap-client:8002` directly (ONIX appends `/on_discover`), while all other `on_*` callbacks go to `http://beckn-bap-client:8002/bap/receiver`. This is required for the Redis Pub/Sub path. (Source: config/README.md -- Confidence: High)

### 3.2 Async Discovery — ADR-0001

The deadlock problem: the MCP sidecar must fire `/discover` and return a catalog synchronously to IntentParser, but Beckn v2.0.0 returns only an ACK — the catalog arrives later via webhook. Holding the HTTP connection open blocks the asyncio event loop; the `on_discover` callback can never be received.

**Resolution:** Redis Pub/Sub on `beckn_results:{transaction_id}`. The five-step protocol:

1. Generate a UUID `transaction_id`.
2. **Subscribe** to `beckn_results:{transaction_id}` before sending anything.
3. Fire `POST /discover` as `asyncio.create_task(...)` — never `await`. (Source: CLAUDE.md, ADR-0001 -- Confidence: High)
4. The `on_discover` handler in `beckn-bap-client` publishes the catalog payload to `beckn_results:{transaction_id}`.
5. The sidecar's Redis subscriber receives the message and returns the catalog to IntentParser.

The `/on_discover` handler also calls `CallbackCollector.handle_callback("on_discover", payload)` in parallel, so the orchestrator path (which uses `CallbackCollector` directly) is also unblocked by the same webhook. (Source: services/beckn-bap-client/README.md -- Confidence: High)

```mermaid
sequenceDiagram
    participant IP as IntentParser
    participant MCP as mcp-sidecar :3000
    participant BAP as beckn-bap-client :8002
    participant REDIS as Redis :6379
    participant ONIX as onix-bap :8081
    participant BPP as sim-bpp :3002

    IP->>MCP: tools/call search_bpp_catalog
    MCP->>REDIS: SUBSCRIBE beckn_results:{txn_id}
    MCP-->>BAP: asyncio.create_task(POST /discover) [non-blocking]
    BAP->>ONIX: POST /bap/caller/discover
    ONIX->>BPP: POST /api/webhook/discover
    BPP-->>ONIX: ACK (sync)
    BPP->>ONIX: POST on_discover (async)
    ONIX->>BAP: POST /on_discover
    BAP->>REDIS: PUBLISH beckn_results:{txn_id} catalog_payload
    REDIS-->>MCP: message (catalog_payload)
    MCP-->>IP: {found: true, items: [...]}
```

**Failure mode:** if Redis is unavailable, `/on_discover` logs a warning and falls through to `CallbackCollector` only. The mcp-sidecar times out after `REDIS_RESULT_TIMEOUT` seconds (default 15 s) and returns `{"found": false, "items": []}`. (Source: services/beckn-bap-client/README.md -- Confidence: High)

---

## 4. IntentParser 3-Stage Pipeline

Natural language is processed in three sequential stages. Stages 1 and 2 are always executed; Stage 3 runs only on the `/parse/full` endpoint and when the mcp-sidecar is reachable. (Source: IntentParser/README.md -- Confidence: High)

```mermaid
flowchart TD
    INPUT["NL query\n(raw string)"]

    subgraph Stage1["Stage 1 — Intent Classification"]
        S1LLM["qwen3:8b complex\nor qwen3:1.7b simple\nvia Ollama + instructor"]
        S1OUT["ParsedIntent\n{intent_class, confidence,\nentities, quantity, location,\ntimeline, budget}"]
    end

    subgraph Stage2["Stage 2 — BecknIntent Extraction"]
        ROUTE{"_is_complex?\n>120 chars OR >=2 numbers\nOR keywords"}
        COMPLEX["COMPLEX_MODEL\nqwen3:8b (local)\nqwen3:1.7b (Docker)"]
        SIMPLE["SIMPLE_MODEL\nqwen3:1.7b"]
        S2OUT["BecknIntent\n{item, descriptions[], quantity,\nlocation_coordinates 'lat,lon',\ndelivery_timeline hours,\nbudget_constraints {max,min}}"]
    end

    subgraph Stage3["Stage 3 — Hybrid Validation"]
        ANN["pgvector ANN\nbpp_catalog_semantic_cache\nall-MiniLM-L6-v2 384-dim\ncosine HNSW"]
        MCP["MCP Sidecar :3000\nsearch_bpp_catalog\n-> Redis -> ONIX -> sim-bpp"]
        SCORE{"similarity\nscore"}
        V["VALIDATED >= 0.85\nreturn cached offering"]
        A["AMBIGUOUS 0.45-0.85\nMCP probe to confirm"]
        CM["CACHE_MISS < 0.45\nMCP full probe"]
    end

    subgraph Recovery["Recovery Flow (not_found)"]
        BROAD["broaden_procurement_query\nregex strip + Claude fallback\n(ANTHROPIC_API_KEY opt-in)"]
        RETRY["Stage 3 retry"]
        STUBS["log_unmet_demand\nnotify_buyer_no_stock\ntrigger_open_rfq_flow\n(all stubs — Phase 4)"]
    end

    INPUT --> Stage1
    S1LLM --> S1OUT
    S1OUT --> Stage2
    ROUTE -->|complex| COMPLEX
    ROUTE -->|simple| SIMPLE
    COMPLEX --> S2OUT
    SIMPLE --> S2OUT
    S2OUT --> Stage3
    ANN --> SCORE
    SCORE -->|>=0.85| V
    SCORE -->|0.45-0.85| A
    SCORE -->|<0.45| CM
    A --> MCP
    CM --> MCP
    MCP -->|not_found| Recovery
    BROAD --> RETRY
    RETRY -->|still not_found| STUBS
```

**Canonical field encodings enforced by BecknIntent** (Source: shared/README.md -- Confidence: High):

| Field | Encoding | Example |
|---|---|---|
| `delivery_timeline` | `int` hours | `72` (not `"P3D"`) |
| `location_coordinates` | `"lat,lon"` decimal string | `"12.9716,77.5946"` |
| `budget_constraints` | `BudgetConstraints(max, min)` typed | `{"max": 200.0, "min": 0.0}` |

**Docker vs local LLM routing.** In Docker (`intention-parser` container), both `COMPLEX_MODEL` and `SIMPLE_MODEL` are set to `qwen3:1.7b` in `docker-compose.yml`, collapsing the two-tier routing. The `qwen3:8b` model is only used when IntentParser is run locally. (Source: docker-compose.yml lines 14–15, IntentParser/config.py -- Confidence: High)

---

## 5. LangGraph State Machines

### 5.1 Orchestrator Pipeline

The orchestrator drives procurement through a 4-step pipeline. Two execution modes are exposed: `/run` (full pipeline) and `/compare` + `/commit` (two-phase). (Source: services/orchestrator/README.md -- Confidence: High)

```mermaid
flowchart TD
    START(["POST /run\nor /compare+/commit"])

    subgraph Step1["Step 1 — Intent"]
        S1["POST intention-parser :8001 /parse\n→ BecknIntent"]
    end

    subgraph Step2["Step 2 — Discovery"]
        S2["POST beckn-bap-client :8002 /discover\n→ offerings[]"]
        S2_DN["POST data-normalizer :8006\n/normalize/discovery (fire-and-forget)"]
    end

    subgraph Step3["Step 3 — Scoring"]
        S3["POST comparative-scoring :8003 /score\n→ ranked DiscoverOffering"]
        S3_DN["POST data-normalizer :8006\n/normalize/scoring (fire-and-forget)"]
    end

    COMPARE_STOP(["Return offerings\nto frontend\n(POST /compare stops here)"])

    subgraph ERP_GATE["ERP Budget Gate\n(ERP_BUDGET_CHECK_ENABLED=true)"]
        ERP["POST erp-adapter :8007\n/api/v1/budget/check\nsync ≤800ms"]
        ERP_FAIL["fail-closed\n→ 402 budget_exceeded"]
    end

    subgraph Step4["Step 4 — Select → Init → Confirm"]
        S4A["POST beckn-bap-client :8002 /select"]
        S4B["POST beckn-bap-client :8002 /init"]
        S4C["POST beckn-bap-client :8002 /confirm\n→ order_id"]
    end

    subgraph Persist["Persistence + Audit\n(fire-and-forget, 5s timeout)"]
        DN_ORD["POST data-normalizer :8006 /normalize/order"]
        MEM["POST data-normalizer :8006\n/normalize/memory/write"]
        AUD["POST data-normalizer :8006\n/normalize/audit (20+ call sites)"]
    end

    APPROVAL{"Approval\nrequired?"}
    WAIT_APPROVE["POST /approvals/{id}/decide\nblocking until approved"]

    START --> Step1
    Step1 --> Step2
    Step2 --> S2_DN
    Step2 --> Step3
    Step3 --> S3_DN
    Step3 --> COMPARE_STOP
    COMPARE_STOP -->|"POST /commit\nloads session"| ERP_GATE
    ERP -->|allowed| APPROVAL
    ERP -->|denied| ERP_FAIL
    APPROVAL -->|auto| Step4
    APPROVAL -->|manager/cfo| WAIT_APPROVE
    WAIT_APPROVE --> Step4
    Step4 --> S4A
    S4A --> S4B
    S4B --> S4C
    S4C --> Persist
```

**Approval routing logic** (Source: KnowledgeBase/project_scaffold -- Confidence: High):

- `amount <= requester.approval_threshold` → auto-approved
- `amount > requester.threshold AND <= approver.threshold` → manager approval
- `amount > approver.threshold` → CFO approval
- `is_emergency = TRUE` → CFO + deadline in 60 minutes

**Autonomous negotiation path.** When `decision.requires_negotiation` is true on `/run`, the orchestrator calls `DEMO_GATEWAY_URL/api/demo/negotiate` (default `http://localhost:8015`) and polls `GET /api/demo/negotiate/{thread_id}`. The demo-gateway relays to `negotiation-engine:8004`. This path is only active on `/run`, not on the `/compare` + `/commit` two-phase flow. (Source: services/orchestrator/src/workflow.py code finding -- Confidence: High)

### 5.2 Negotiation Engine LangGraph

The negotiation engine is a LangGraph `StateGraph` with per-category discount profiles and three-layer guardrails. The absolute discount cap is 20% enforced at the Pydantic schema level. (Source: services/negotiation_engine/README.md -- Confidence: High)

```mermaid
flowchart TD
    START(["POST /negotiate\n{transaction_id, category,\nranked_offers[], policy,\nmax_rounds}"])

    AT["analyze_target\nselect best candidate\ncompute target price"]

    EAT["evaluate_ambiguous_terms\nqwen3:8b advisory\n(it_equipment, medical only)"]

    FINALIZE["finalize\nreturn final_outcome"]

    CCO["compute_counter_offer\ncategory profile:\ncommodity 10%\nspecialized 5%\nit_equipment 0%\nmedical 0%"]

    PGC["policy_guardrail_check\nL1: Pydantic [0.0, 0.20]\nL2: validate_counter_offer\n    G1 absolute cap\n    G2 category cap\n    G3 supplier cap\n    G5 lead time\n    G6 quantity\nL3: ONIX schema validation"]

    HE["human_escalation\nHITL interrupt\n(pause for human decision)"]

    WAIT["wait_for_async_callback\nRedis SUBSCRIBE\nbeckn_on_select_results\nOnSelectListener resumes\ngraph via Command(resume=...)"]

    TO["timeout_handler\nno response within limit"]

    ER["evaluate_response\ncheck supplier counter vs policy\ncompute gap_pct"]

    END_NODE(["END\nreturn {thread_id,\nfinal_outcome,\nround}"])

    START --> AT
    AT -->|advisory_only category| EAT
    EAT --> FINALIZE
    AT -->|no valid candidates| FINALIZE
    AT --> CCO
    CCO --> PGC
    PGC -->|policy violation| HE
    PGC -->|pass| WAIT
    HE -->|human override| WAIT
    HE -->|human reject/accept| FINALIZE
    WAIT -->|timeout| TO
    TO --> FINALIZE
    WAIT -->|on_select received| ER
    ER -->|supplier accepted| FINALIZE
    ER -->|gap_pct > HITL threshold\nor max_rounds reached| HE
    ER -->|continue| AT
    FINALIZE --> END_NODE
```

**Checkpointing.** When `NEGOTIATION_POSTGRES_DSN` is set, `AsyncPostgresSaver` provides durable checkpointing; otherwise `MemorySaver` is used (state lost on restart). The negotiation Postgres database (container `postgres` on port 55432) is separate from the main `procurement_agent` database. (Source: services/negotiation_engine/README.md, docker-compose.yml -- Confidence: High)

**Async resume.** `OnSelectListener` subscribes to `Redis` channel `beckn_on_select_results` and calls `graph.ainvoke(Command(resume=payload))` to unpark the buyer graph. The supplier respond step is driven by `SupplierAgent` (Claude via `claude_openai_proxy :8012`) through `demo-gateway`. (Source: services/negotiation_engine/README.md -- Confidence: High)

---

## 6. Main Happy-Path Sequence

Full end-to-end flow for a natural-language procurement request terminating in a confirmed purchase order.

```mermaid
sequenceDiagram
    actor User
    participant FE as frontend :3000
    participant ORCH as orchestrator :8004
    participant DN as data-normalizer :8006
    participant IP as intention-parser :8001
    participant BAP as beckn-bap-client :8002
    participant CN as catalog-normalizer :8005
    participant CS as comparative-scoring :8003
    participant ERP as erp-adapter :8007
    participant ONIX as onix-bap :8081
    participant BPP as sim-bpp :3002
    participant REDIS as Redis :6379
    participant PG as PostgreSQL :5432

    User->>FE: "300m Cat6 UTP cable Mumbai 5 days"
    FE->>ORCH: POST /compare {query}

    Note over ORCH,DN: Step 0 — persist request
    ORCH-->>DN: POST /normalize/request → {request_id}

    Note over ORCH,IP: Step 1 — parse intent
    ORCH->>IP: POST /parse {query}
    IP-->>ORCH: BecknIntent{item, qty, location, timeline, budget}
    ORCH-->>DN: POST /normalize/intent (fire-and-forget)

    Note over ORCH,REDIS: Step 2 — discover
    ORCH->>BAP: POST /discover {BecknIntent}
    BAP->>REDIS: SUBSCRIBE beckn_results:{txn_id}
    BAP-->>ONIX: POST /bap/caller/discover [asyncio.create_task]
    ONIX->>BPP: POST /api/webhook/discover
    BPP-->>ONIX: ACK
    BPP->>ONIX: POST on_discover (async)
    ONIX->>BAP: POST /on_discover
    BAP->>CN: POST /normalize (format detection)
    CN-->>BAP: offerings[]
    BAP->>REDIS: PUBLISH beckn_results:{txn_id} offerings
    BAP-->>ORCH: {transaction_id, offerings[]}
    ORCH-->>DN: POST /normalize/discovery (fire-and-forget)

    Note over ORCH,CS: Step 3 — score
    ORCH->>CS: POST /score {offerings[]}
    CS-->>ORCH: {selected: DiscoverOffering, scoring}
    ORCH-->>DN: POST /normalize/scoring (fire-and-forget)

    Note over FE: compare returns here — user reviews & POSTs /commit

    FE->>ORCH: POST /commit {transaction_id, chosen_item_id}

    Note over ORCH,ERP: ERP budget gate (if enabled)
    ORCH->>ERP: POST /api/v1/budget/check {amount, cost_center}
    ERP-->>ORCH: {allowed: true, hold_id}

    Note over ORCH,BAP: Steps 4a–4c — transactional lifecycle
    ORCH->>BAP: POST /select {item, transaction_id}
    BAP->>ONIX: POST /bap/caller/select
    ONIX-->>BAP: on_select callback
    BAP-->>ORCH: ACK

    ORCH->>BAP: POST /init {buyer_billing, fulfillment}
    BAP->>ONIX: POST /bap/caller/init
    ONIX-->>BAP: on_init callback {payment_terms}
    BAP-->>ORCH: {payment_terms}

    ORCH->>BAP: POST /confirm {payment}
    BAP->>ONIX: POST /bap/caller/confirm
    ONIX-->>BAP: on_confirm callback {order_id, ACTIVE}
    BAP-->>ORCH: {order_id, order_state: ACTIVE}

    Note over ORCH,PG: Persistence (fire-and-forget)
    ORCH-->>DN: POST /normalize/order → purchase_orders
    ORCH-->>DN: POST /normalize/memory/write
    ORCH-->>DN: POST /normalize/audit × N (event_type: confirm)
    DN->>PG: INSERT purchase_orders + audit_trail_events + agent_memory_vectors

    ORCH-->>FE: {transaction_id, order_id, order_state: ACTIVE}
    FE-->>User: Order confirmed
```

**Key invariants in this flow** (Source: CLAUDE.md -- Confidence: High):

- `transaction_id` is generated once and propagated through every layer. It must never be reused — Beckn channels are derived from it and reuse delivers one transaction's catalog to a stale subscriber.
- Beckn traffic always passes through `onix-bap:8081`. No service POSTs directly to `sim-bpp` or any external BPP.
- `data-normalizer` is the sole write path into PostgreSQL. All `_persist_*` calls in the orchestrator use fire-and-forget `asyncio.create_task` with a 5-second timeout and never raise on failure.
- `Contract.status.code` on `/confirm` must be `ACTIVE`, not `"CONFIRMED"`. Valid enum values are `DRAFT | ACTIVE | CANCELLED | COMPLETE`. ONIX rejects all others. (Source: Bap-1/CLAUDE.md -- Confidence: High)

---

## 7. Known Architectural Gaps

The following issues are documented in the codebase and affect system understanding:

| Issue | Location | Impact |
|---|---|---|
| `docs/ARCHITECTURE.md` (repo root) does not exist; 14 production blockers live in `Bap-1/docs/ARCHITECTURE.md §7` only | Bap-1/docs/ARCHITECTURE.md | Engineers searching repo root find nothing |
| `discovery_engine` service is fully implemented but has no `docker-compose.yml` entry and no callers | services/discovery_engine/ | Service is orphaned; port 8006 conflicts with data-normalizer |
| `claude_openai_proxy` (:8012) is absent from `docker-compose.yml` and CLAUDE.md; negotiation-engine and demo-gateway depend on it at runtime | services/claude_openai_proxy/ | Demo/negotiation flows fail silently if proxy not started manually |
| `embedding_model_type` ENUM in `00_extensions_and_types.sql` contains only `text-embedding-3-large` and `e5-large-v2`; actual models (`all-MiniLM-L6-v2`, `BAAI/bge-small-en-v1.5`) are absent; migration `22_agent_memory_vector_dim.sql` adds `all-MiniLM-L6-v2` but does not update the column DEFAULT | database/sql/00_extensions_and_types.sql, 15_agent_memory_vectors.sql | INSERT with actual model name fails without migration 22 applied |
| `COMPLEX_MODEL` default is `qwen3:8b` in `IntentParser/config.py` but `docker-compose.yml` overrides to `qwen3:1.7b`, silently disabling complexity routing in Docker | docker-compose.yml line 14 | Dockerized service always uses qwen3:1.7b regardless of query complexity |
| Orchestrator's autonomous negotiation defaults `DEMO_GATEWAY_URL` to `http://localhost:8015` but `frontend_demo_gateway` README states port 8005 | services/orchestrator/src/workflow.py line 55 | Autonomous negotiation fails unless env var is set correctly |
| Recovery flow stubs (`log_unmet_demand`, `notify_buyer_no_stock`, `trigger_open_rfq_flow`) are no-op logger calls with no owner or completion plan | IntentParser/recovery.py | `not_found` path silently drops procurement requests |

(Source: code_findings section -- Confidence: High)
