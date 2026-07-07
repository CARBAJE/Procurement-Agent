# Procurement Agent

The Procurement Agent is an event-driven agentic AI system built for corporate buyers. It accepts natural-language purchase requests — such as `"300 meters Cat6 UTP cable Mumbai 5 days"` — classifies intent, extracts structured procurement parameters via a three-stage LLM pipeline, discovers matching suppliers on a Beckn Protocol v2.0.0 network, scores and ranks their offers using an ML model with agent memory, optionally negotiates price autonomously via a LangGraph state machine, obtains ERP budget approval, and drives the full Beckn lifecycle (`discover → select → init → confirm → status`). Every decision is persisted to an auditable PostgreSQL database with 7-year retention. The buyer interacts through a Next.js 13 dashboard without writing code or issuing protocol calls directly.

---

## Quick Start

1. **Provision the database.** Install PostgreSQL 16 with the pgvector extension natively on the host, then run `cd database && python setup_database.py` to apply the 24 numbered SQL migrations. See [Installation Guide](INSTALLATION.md) for required environment variables and the exact Conda environment setup.

2. **Start the Docker stack.** Bring up all 18 containerised services:

   ```bash
   docker compose up -d
   ```

   Verify Beckn routing is live by checking `docker compose logs -f beckn-bap-client`.

3. **Start the three host-side processes.** These are not Dockerised and must be started manually in the `conda activate infosys_project` environment:

   ```bash
   # MCP sidecar — required for IntentParser Stage 3 validation
   cd services/mcp-sidecar
   BAP_API_KEY="any-value" uvicorn server:app --port 3000

   # Frontend
   cd frontend && npm run dev   # http://localhost:3000

   # Claude OpenAI proxy — required for negotiation demo flows
   export CLAUDE_PROXY_KEY=your-key
   uvicorn services.claude_openai_proxy.main:app --host 0.0.0.0 --port 8012
   ```

   Open `http://localhost:3000` and authenticate via the Phase Two Keycloak tenant. See [Installation Guide](INSTALLATION.md) for all required environment variables.

---

## Documentation Index

| Document | Purpose |
|---|---|
| [PROJECT_OVERVIEW.md](PROJECT_OVERVIEW.md) | Problem statement, solution summary, target users, project scope, design principles, tech-choice rationale, and known limitations |
| [ARCHITECTURE.md](ARCHITECTURE.md) | Detailed architecture: component map, ADR-0001 Redis Pub/Sub, IntentParser pipeline, LangGraph state machines, and full component reference (§9) |
| [SYSTEM_DESIGN.md](SYSTEM_DESIGN.md) | Service boundaries, design decisions, anti-corruption layer, error handling philosophy, and five full ADRs |
| [DATA_FLOW.md](DATA_FLOW.md) | Seven major data flows with Mermaid sequence diagrams: NL→Beckn, discovery, scoring, negotiation, ERP, audit, memory |
| [INSTALLATION.md](INSTALLATION.md) | Step-by-step setup: Conda environment, PostgreSQL native install, Docker Compose, host-side processes, required environment variables |
| [CONFIGURATION.md](CONFIGURATION.md) | Complete environment variable reference, ONIX routing YAMLs, LLM model selection, ERP vendor wiring, and Beckn network parameters |
| [DATABASE.md](DATABASE.md) | Database schema: ER diagrams, 24 SQL migrations, vector tables, Redis channels, known schema deviations |
| [DEPLOYMENT.md](DEPLOYMENT.md) | Docker Compose deployment guide: container reference, bind mounts, common operations, database migrations, observability |
| [SECURITY.md](SECURITY.md) | Authentication model, Beckn ED25519 signing, HMAC webhook rotation, input validation, secrets management, known security gaps |
| [TESTING.md](TESTING.md) | Test framework, test suites by scope, infrastructure requirements, coverage gaps |
| [DEVELOPMENT_GUIDE.md](DEVELOPMENT_GUIDE.md) | Coding conventions, async patterns, adding services and DB tables, IntentParser and LangGraph internals, known problems and workarounds |
| [CONTRIBUTING.md](CONTRIBUTING.md) | Git workflow, branch naming, pre-submission checklist, documentation standards, PR review criteria |
| [TROUBLESHOOTING.md](TROUBLESHOOTING.md) | Diagnostic runbooks: NL parsing, Beckn discovery, database, ERP integration, frontend, negotiation engine |
| [API_REFERENCE.md](API_REFERENCE.md) | HTTP API surface: all endpoints, request/response schemas, and error codes for every service |
| [GLOSSARY.md](GLOSSARY.md) | Alphabetical definitions of all domain terms, architectural concepts, and database identifiers |
| [COMPONENTS.md](COMPONENTS.md) | Service-by-service component reference including the supplier selection explanation feature (POST /explain-selection) |

---

## Phase 4 Highlights

The following capabilities were completed or fixed in Phase 4 (weeks 13–16):

- **LLM-powered supplier selection explanation.** After comparative scoring, the intention-parser Docker service exposes `POST /explain-selection`. It calls `qwen3:1.7b` via Ollama to generate a 2–3 sentence human-readable rationale for why the top-ranked supplier scored highest. The `SelectionExplanationCard` in the RunView renders the result with a loading skeleton and an error fallback; it fires non-blocking after the page renders so the buyer can review the comparison table while the explanation is still generating.

- **Navigation guard Cancel button fix.** The `useNavigationGuard` hook gained a `trigger(href)` method that allows non-anchor interactive elements (e.g. buttons) to participate in the in-app navigation interception modal. Previously the Cancel button bypassed the guard and navigated without confirmation.

- **Original request display on Order Confirmed page.** The OrderView now fetches and displays the buyer's original natural-language request (`raw_input_text`) from the database via `getOrderDetail()`, giving approvers and auditors the full procurement context alongside the confirmed PO.

- **Negotiation savings pipeline fix.** Two PostgreSQL enum mismatches (`"negotiated"` → `"accept_margin"/"skipped"` for `negotiation_strategy_type`; `"agreed"` → `"accepted"/"skipped"` for `acceptance_status_type`) caused the analytics savings query to return zero for all negotiated orders. Both enum values are corrected in `order_repo.py`. The `original_price` field is now propagated correctly through both autonomous and HITL orchestrator flows, so `SUM(initial_price - final_price)` returns accurate savings figures.
