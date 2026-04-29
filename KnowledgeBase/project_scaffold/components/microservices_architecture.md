---
tags: [component, architecture, microservices, aws, step-functions, lambda, docker, beckn, onix]
cssclasses: [procurement-doc, component-doc]
status: "#processed"
related: ["[[beckn_bap_client]]", "[[nl_intent_parser]]", "[[agent_react_framework]]", "[[comparison_scoring_engine]]", "[[catalog_normalizer]]"]
---

# Component: Microservices Architecture (AWS Step Functions)

> [!architecture] Why the Migration
> The original `Bap-1/` monolith runs all procurement logic in a single Python process. The target architecture (from `architecture/Architecture.md`) decomposes it into **AWS Lambda functions** orchestrated by **Step Functions**, enabling independent scaling, isolated deployment, and clear separation of concerns. Today, **6 services** are implemented under `services/`. The full ONIX stack (redis, onix-bap, onix-bpp, sandbox-bpp) is included in the root `docker-compose.yml` — a single `docker compose up --build` starts everything.

---

## Step Functions State Machine

| Step | Lambda | Status | Endpoint |
|------|--------|--------|----------|
| 1 | Intention Parser | ✅ Implemented | `POST /parse` |
| 2 | Beckn BAP Client (discover + select + init + confirm) | ✅ Implemented | `POST /discover`, `POST /select`, `POST /init`, `POST /confirm` |
| 3 | Comparative & Scoring | ✅ Implemented | `POST /score` |
| 4 | Catalog Normalizer | ✅ Implemented | `POST /normalize` |
| 5 | Data Normalizer (persistence bridge) | ✅ Implemented | `POST /normalize/*`, `PATCH /normalize/status` |
| 6 | Negotiation Engine | ⏳ Phase 3 | — |
| 7 | Approval Engine | ⏳ Phase 3 | — |

---

## Service Map

| Service | Port | HTTP Endpoints | Lambda Equivalent | Agent Embedded |
|---------|------|---------------|-------------------|----------------|
| `intention-parser` | 8001 | `POST /parse` | Lambda 1 | Parser Agent (qwen3:1.7b) |
| `beckn-bap-client` | 8002 | `POST /discover`, `POST /select`, `POST /init`, `POST /confirm`, `POST /status`, `POST /bpp/discover`, `POST /bap/receiver/{action}` | Lambda 2 | Normalizer Agent |
| `comparative-scoring` | 8003 | `POST /score` | Lambda 3 | — (deterministic) |
| `orchestrator` | 8004 | `POST /run`, `POST /parse`, `POST /discover`, `POST /compare`, `POST /commit`, `GET /status/{txn}/{order}` | Step Functions simulator | — |
| `catalog-normalizer` | 8005 | `POST /normalize`, `GET /health` | Lambda 4 | CatalogNormalizer (qwen3:1.7b LLM fallback) |
| `data-normalizer` | 8006 | `POST /normalize/request`, `POST /normalize/intent`, `POST /normalize/discovery`, `POST /normalize/scoring`, `POST /normalize/order`, `PATCH /normalize/status` | Lambda 5 | — (asyncpg → PostgreSQL) |

### ONIX Stack (included in docker-compose.yml)

| Container | Port | Role |
|-----------|------|------|
| `onix-bap` | 8081 | BAP Adapter — ED25519 signing, routes discover/select to BPP |
| `onix-bpp` | 8082 | BPP Adapter — receives on_select, on_init, on_confirm |
| `sandbox-bpp` | 3002 | Mock BPP — generates on_* callbacks for transactions |
| `redis` | 6379 | Shared cache for onix-bap and onix-bpp |

---

## Port Map — Local Implementation

```
HOST (macOS / Linux)                 DOCKER (beckn_network)
─────────────────────────────────────────────────────────────────────────────
localhost:8001  ────────────────► intention-parser      :8001  (Lambda 1)
localhost:8002  ────────────────► beckn-bap-client      :8002  (Lambda 2)
localhost:8003  ────────────────► comparative-scoring   :8003  (Lambda 3)
localhost:8004  ────────────────► orchestrator          :8004  (Step Functions)
localhost:8005  ────────────────► catalog-normalizer    :8005  (Lambda 4)
localhost:8006  ────────────────► data-normalizer       :8006  (Lambda 5)
localhost:8081  ────────────────► onix-bap              :8081  (BAP ONIX adapter)
localhost:8082  ────────────────► onix-bpp              :8082  (BPP ONIX adapter)
localhost:3002  ────────────────► sandbox-bpp           :3002  (BPP mock)
localhost:6379  ────────────────► redis                 :6379  (ONIX cache)
host.docker.internal:11434 ◄──── Ollama (host process)
host.docker.internal:5432  ◄──── PostgreSQL (host process)
```

> [!info] Docker Network
> All containers share the `beckn_network` (bridge) network. Docker DNS resolves
> container names directly, which is why `http://beckn-bap-client:8002` works
> from any other container. This is not a container — it is a virtual network
> created automatically by `docker compose up`.

---

## Full Communication Diagram

### Frontend Flow — two direct calls (Step 1 direct, Steps 2→3→4 via orchestrator)

```
Browser
  │
  ├─ UI Step 1 ──► intention-parser:8001/parse  { query }    ← DIRECT call
  │                  └─ Ollama (host:11434) → qwen3:1.7b
  │                  └─ returns intent preview to the user
  │
  └─ UI Step 2 ──► orchestrator:8004/discover  { BecknIntent }   ← user confirms
                     │  (orchestrator executes Steps 2→3→4 only)
                     │
                     ├─ Step 2 ──► beckn-bap-client:8002/discover
                     │               └─► onix-bap:8081 → beckn-bap-client:8002/bpp/discover
                     │                     └─► (async) on_discover → CallbackCollector
                     │
                     ├─ Step 3 ──► comparative-scoring:8003/score
                     │
                     └─ Step 4 ──► beckn-bap-client:8002/select
                                     └─► onix-bap:8081 → onix-bpp:8082 → sandbox-bpp:3002
```

> [!info] El frontend nunca llama a `orchestrator:8004/run`
> `POST /run` recibe la query en lenguaje natural e incluye Step 1 (parseo NL). El frontend
> ya completó Step 1 por su cuenta (llamada directa a `intention-parser:8001/parse`) antes de
> llamar a `POST /discover`, por eso el orquestador solo ejecuta Steps 2→3→4.

---
### Repository Layout

```
Procurement-Agent/
├── services/
│   ├── intention-parser/     Lambda 1 — POST /parse                       :8001
│   ├── beckn-bap-client/     Lambda 2 — POST /discover /select /init /confirm :8002
│   ├── comparative-scoring/  Lambda 3 — POST /score                       :8003
│   ├── orchestrator/         Step Functions — POST /run /compare /commit   :8004
│   ├── catalog-normalizer/   Lambda 4 — POST /normalize (catalog formats) :8005
│   └── data-normalizer/      Lambda 5 — POST /normalize/* (PostgreSQL)    :8006
├── IntentParser/             NL module (volume-mounted in intention-parser)
├── CatalogNormalizer/        Catalog format module (volume-mounted in catalog-normalizer)
├── ComparativeScoring/       Scoring module (volume-mounted in comparative-scoring)
├── DataNormalizer/           Persistence module (volume-mounted in data-normalizer)
│   ├── repositories/         request, intent, discovery, scoring, order repos
│   └── transformers/         offering, intent, score transformers
├── shared/models.py          Source of truth: BecknIntent, DiscoverOffering
├── database/sql/             16 SQL files — complete PostgreSQL schema
├── config/                   ONIX routing YAML (onix-bap, onix-bpp)
├── docker-compose.yml        10 containers: 6 services + ONIX stack + redis
├── frontend/                 Next.js — apunta a puertos 8001 y 8004
└── Bap-1/                    Monolito legacy — preservado como referencia, sin cambios
```
