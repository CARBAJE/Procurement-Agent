---
tags: [component, architecture, microservices, aws, step-functions, lambda, docker, beckn, onix]
cssclasses: [procurement-doc, component-doc]
status: "#processed"
related: ["[[beckn_bap_client]]", "[[nl_intent_parser]]", "[[agent_react_framework]]", "[[comparison_scoring_engine]]", "[[catalog_normalizer]]"]
---

# Component: Microservices Architecture (AWS Step Functions)

> [!architecture] Why the Migration
> The original `Bap-1/` monolith runs all procurement logic in a single Python process. The target architecture (from `architecture/Architecture.md`) decomposes it into **5 AWS Lambda functions** orchestrated by **Step Functions**, enabling independent scaling, isolated deployment, and clear separation of concerns. Today, 3 of the 5 Lambdas are implemented under `services/`. The full ONIX stack (redis, onix-bap, onix-bpp, sandbox-bpp) is included in the root `docker-compose.yml` — a single `docker compose up --build` starts everything.

---

## Step Functions State Machine

| Step | Lambda | Status | Endpoint |
|------|--------|--------|----------|
| 1 | Intention Parser | ✅ Implemented | `POST /parse` |
| 2 | Beckn BAP Client (discover + select) | ✅ Implemented | `POST /discover`, `POST /select` |
| 3 | Comparative & Scoring | ✅ Implemented | `POST /score` |
| 4 | Negotiation Engine | ⏳ Not built yet | — |
| 5 | Approval Engine | ⏳ Not built yet | — |

---

## Service Map

| Service | Port | HTTP Endpoints | Lambda Equivalent | Agent Embedded |
|---------|------|---------------|-------------------|----------------|
| `intention-parser` | 8001 | `POST /parse` | Lambda 1 | Parser Agent (qwen3:1.7b) |
| `beckn-bap-client` | 8002 | `POST /discover`, `POST /select`, `POST /bpp/discover`, `POST /bap/receiver/{action}` | Lambda 2 | Normalizer Agent |
| `comparative-scoring` | 8003 | `POST /score` | Lambda 3 | — (deterministic) |
| `orchestrator` | 8004 | `POST /run`, `POST /discover` | Step Functions simulator | — |

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
localhost:8081  ────────────────► onix-bap              :8081  (BAP ONIX adapter)
localhost:8082  ────────────────► onix-bpp              :8082  (BPP ONIX adapter)
localhost:3002  ────────────────► sandbox-bpp           :3002  (BPP mock)
localhost:6379  ────────────────► redis                 :6379  (ONIX cache)
host.docker.internal:11434 ◄──── Ollama (host process)
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
│   ├── intention-parser/     Lambda 1 — POST /parse
│   ├── beckn-bap-client/     Lambda 2 — POST /discover, /select, /bpp/discover, /bap/receiver
│   ├── comparative-scoring/  Lambda 3 — POST /score
│   └── orchestrator/         Step Functions simulator — POST /run, /discover
├── config/                   Routing YAML para onix-bap y onix-bpp (beckn_network)
├── shared/models.py          Fuente única de verdad: BecknIntent, DiscoverOffering
├── docker-compose.yml        8 contenedores: 4 Lambdas + ONIX stack (redis, bap, bpp, sandbox)
├── frontend/                 Next.js — apunta a puertos 8001 y 8004
└── Bap-1/                    Monolito legacy — preservado como referencia, sin cambios
```
