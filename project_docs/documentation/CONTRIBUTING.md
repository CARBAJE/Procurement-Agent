# Contributing Guide

This guide covers everything a developer needs before opening a pull request: environment setup, Git conventions, the pre-submission checklist, documentation expectations, code style, known trouble spots, and PR review criteria.

Cross-references: [Architecture](ARCHITECTURE.md) · [Components](COMPONENTS.md) · [API Reference](API_REFERENCE.md) · [Environment Variables](ENVIRONMENT.md) · [Installation](INSTALLATION.md) · [Database](DATABASE.md)

---

## 1. Development Setup

Follow [INSTALLATION.md](INSTALLATION.md) for the complete first-time walkthrough. The checklist below is a quick state-check before you start coding.

### 1.1 Prerequisites Checklist

| Requirement | Command to verify | Notes |
|---|---|---|
| Docker Engine running | `docker info` | Required for the 18-service stack |
| `conda activate infosys_project` | `conda info --envs` | All local Python services need this env |
| Ollama serving `qwen3:8b` and `qwen3:1.7b` | `ollama list` | Used by IntentParser Stages 1–2 |
| Root `.env` present and populated | `cat .env \| head -5` | Copy from `.env.example`; never commit `.env` |
| Database initialised | `pytest database/test_database.py -v -q` | Must pass 67 tests before first run |

### 1.2 Services That Must Run Outside Docker

Three processes are **not** in `docker-compose.yml` and must be started manually on the host in addition to `docker compose up -d`.

```
┌─────────────────────────────────────────────────────────────────┐
│  Host processes (conda activate infosys_project)                │
│                                                                 │
│  IntentParser       FastAPI :8001   NL → BecknIntent pipeline   │
│  mcp-sidecar        FastAPI :3000   MCP SSE bridge (Stage 3)    │
│  claude_openai_proxy FastAPI :8012  Claude CLI → OpenAI compat. │
└─────────────────────────────────────────────────────────────────┘
```

**IntentParser** (Stage 3 requires direct access to the conda `sentence-transformers` model cache and a live Ollama instance):

```bash
conda activate infosys_project
cd IntentParser
uvicorn api:app --port 8001 --reload
```

**mcp-sidecar** (`BAP_API_KEY` must be a real shell variable — dotenv loading does not apply here):

```bash
conda activate infosys_project
cd services/mcp-sidecar
BAP_API_KEY="any-non-empty-string-in-dev" uvicorn server:app --port 3000
```

**claude_openai_proxy** (required for autonomous negotiation and the demo gateway; wraps the host-installed `claude` CLI):

```bash
export CLAUDE_PROXY_KEY=your-local-proxy-key
uvicorn services.claude_openai_proxy.main:app --host 0.0.0.0 --port 8012
```

For persistent operation on Linux, see the systemd unit at `services/claude_openai_proxy/claude-proxy.service`. Without this proxy, the `negotiation_engine` and `demo-gateway` containers cannot reach their LLM backend at `host.docker.internal:8012`.

### 1.3 Docker Stack Startup

```bash
# Full stack (18 services on the beckn_network bridge)
docker compose up -d

# Discovery infrastructure only (minimal footprint for Beckn protocol work)
docker compose up -d redis onix-bap onix-bpp

# Tail a specific service
docker compose logs -f orchestrator
```

See [COMPONENTS.md](COMPONENTS.md) for the full port map and service roles.

---

## 2. Git Workflow

### 2.1 Branch Naming

| Prefix | When to use | Example |
|---|---|---|
| `feature/` | New capability or service | `feature/erp-cancel-po-sap` |
| `fix/` | Bug correction | `fix/audit-trail-missing-negotiate-event` |
| `docs/` | Documentation only | `docs/update-contributing-setup` |
| `refactor/` | Internal restructuring, no behaviour change | `refactor/extract-bap-client-retry-logic` |

Branch from `main`. Submit PRs back to `main`. Long-running feature work should rebase onto `main` before opening the PR.

### 2.2 Commit Message Format

```
<type>(<scope>): <imperative summary, ≤72 characters>

Optional body: explain *why*, not *what*. The diff shows what changed;
the commit message explains the motivation and context.

Optional footer: Refs #123, Co-authored-by: Name <email>
```

- **Imperative, present tense**: "add audit event for negotiation round" not "added" or "adds".
- **Scope** is the service or module: `orchestrator`, `intent-parser`, `data-normalizer`, `frontend`, `database`, `mcp-sidecar`, etc.
- **Types**: `feat`, `fix`, `refactor`, `test`, `docs`, `chore`.

### 2.3 PR Process

1. Open the PR against `main` with a description that answers:
   - **What** changed (brief summary).
   - **Why** it was needed (motivation, linked issue if any).
   - **How to test** it manually (curl command, unit test path, or acceptance step).
2. Keep PRs focused. A PR that touches both a new feature and an unrelated refactor should be split.
3. Ensure the pre-submission checklist (Section 3) is complete before requesting review.
4. At least one approval is required before merging.

---

## 3. Pre-Submission Checklist

Work through this list before marking a PR ready for review.

### Async and Python conventions

- [ ] All new functions in IntentParser, services, and Bap-1 are `async def` coroutines. The sync wrapper in `IntentParser.core.parse_request` exists only for legacy callers and disables Stage 3 — do not extend it.
- [ ] No `@pytest.mark.asyncio` decorators anywhere. `asyncio_mode = auto` in `pytest.ini` handles coroutine collection globally; the decorator breaks pytest-asyncio 0.21+.
- [ ] No `time.sleep()` inside coroutines. Use `await asyncio.sleep(0)` or `await asyncio.sleep(n)` to yield the event loop so `asyncio.create_task` side effects (e.g. cache writes) can complete.
- [ ] No inline `os.getenv(...)` calls outside `config.py`. The exception is `services/mcp-sidecar/bap_client.py` which reads `REDIS_URL` and `REDIS_RESULT_TIMEOUT` via `os.getenv()` because these must be real shell variables — do not extend this pattern elsewhere.

### Configuration

- [ ] New environment variables are added in three places: the service's `config.py`, the root `.env.example`, and [ENVIRONMENT.md](ENVIRONMENT.md).
- [ ] Config values are read through Pydantic Settings v2 in the service's `config.py` — not accessed inline.

### Database

- [ ] New tables have an idempotent migration script at `database/sql/NN_description.sql`, using the next available two-digit prefix.
- [ ] Migration scripts use `IF NOT EXISTS` / `DO $$ BEGIN … EXCEPTION WHEN duplicate_* THEN NULL; END $$` so `setup_database.py` can re-run without errors.
- [ ] Existing `database/sql/` files have not been reordered or renumbered. The FK chain depends on lexicographic sort order.
- [ ] New ENUM values added to an existing type go in the base definition (`00_extensions_and_types.sql`) **and** in an `ALTER TYPE … ADD VALUE` migration at the next free prefix.

### Tests

- [ ] Unit tests added for all new business logic.
- [ ] Tests that require live infrastructure (PostgreSQL, Ollama, Redis, Docker stack) are marked `@pytest.mark.integration`.
- [ ] MCP sidecar changes manually verify the never-throw contract: test that a BAP Client timeout, an unreachable BAP Client, zero ONIX matches, a malformed response, a blank required argument, and an unhandled internal exception all return `{"found": false, "items": [], "probe_latency_ms": <elapsed>}` — not a JSON-RPC error.

### Beckn routing

- [ ] All Beckn protocol calls (discover/select/init/confirm/status) go through `onix-bap:8081`. No service POSTs directly to a BPP URL.
- [ ] ONIX routing target URLs in `config/generic-routing-*.yaml` do **not** include the action name. ONIX appends it: `http://host:8000/bpp` + action `discover` → `http://host:8000/bpp/discover`.

### Documentation

- [ ] If a service API changed, [API_REFERENCE.md](API_REFERENCE.md) is updated.
- [ ] If a service was added or removed, [COMPONENTS.md](COMPONENTS.md) and `docker-compose.yml` comments are updated.
- [ ] `CLAUDE.md` "What NOT to do" section was reviewed; no new code violates its constraints.

### Wire-shape

- [ ] `Contract.status.code` uses only `DRAFT | ACTIVE | CANCELLED | COMPLETE`. ONIX rejects other values.
- [ ] No billing or fulfillment data is placed inline in `Contract` (`additionalProperties: false`). Buyer info belongs in `participants[role=buyer]`, fulfillment in `performance[]`, payment in `settlements[]`.
- [ ] Read `Bap-1/CLAUDE.md` wire-shape gotchas before modifying any Beckn adapter, ONIX URL construction, or `Contract` shape.

---

## 4. Documentation Standards

### 4.1 New Service

Every new service directory must contain a `README.md` with these sections:

| Section | Contents |
|---|---|
| Role | One paragraph: what problem this service solves, which other services call it, which it calls. |
| Architecture diagram | Mermaid `flowchart TD` or `sequenceDiagram` showing inputs, outputs, and the main data path. |
| API endpoints | Table: method, path, request schema summary, response schema summary. |
| Configuration | Table: env var name, description, default, required/optional. |
| Run command | Exact command for local dev and for Docker. |
| Testing | How to run the service's tests; infra required. |

### 4.2 Shared Library Changes

`shared/`, `DataNormalizer/`, and `CatalogNormalizer/` are volume-mounted into multiple containers. Changes take effect immediately in running containers without a rebuild, but they affect all consumers simultaneously.

When modifying a shared model:

- Check all services that import from the changed module (use `grep -r "from shared"` / `from DataNormalizer` across `services/`).
- Update the Pydantic model and all consumers in the same PR.
- Run the unit tests for every consumer that has a test suite before opening the PR.

### 4.3 Significant Features

For substantial new features (a new pipeline stage, a new async flow, a new integration):

- Add a record to `docs/architecture/decisions/` following the ADR format in `0001-use-redis-pubsub-for-async-beckn-responses.md`.
- Update the relevant `KnowledgeBase/project_scaffold/` notes if they cover the changed area.
- Consider whether `ARCHITECTURE.md` or `COMPONENTS.md` needs a structural update.

---

## 5. Code Style

### 5.1 Python

- PEP 8. Line length 100 characters.
- **Type hints on all function signatures.** Return types included.
- **Pydantic v2 `field_validator` decorators**, not the deprecated `@validator`. Use `model_validator(mode='before')` for cross-field validation.
- `BecknIntent` is the canonical NL-derived intent model in `shared/models.py`. Its fields have strict types: `delivery_timeline` is `int` (hours, not ISO 8601 strings), `location_coordinates` is `"lat,lon"` decimal string (not a city name), `budget_constraints` is typed `{max: float, min: float}`.
- **Error handling in MCP tools**: return `{"found": False, ...}` on all failure paths. Never raise. See `services/mcp-sidecar/server.py::search_bpp_catalog`.
- Discovery POSTs from the MCP sidecar use `asyncio.create_task(...)`, not `await`. Awaiting the POST reintroduces the deadlock that [ADR-0001](../docs/architecture/decisions/0001-use-redis-pubsub-for-async-beckn-responses.md) was written to prevent.

### 5.2 TypeScript (Frontend)

- Strict mode (`"strict": true` in `tsconfig.json`).
- Component library: Radix UI primitives with Tailwind utility classes. Do not import a second component library.
- All backend calls go through the Axios wrappers in `frontend/src/lib/api.ts`. Do not add raw `fetch` calls in page components.
- The frontend uses NextAuth with Phase Two hosted Keycloak (`KeycloakProvider` only). There are no stub credentials for local dev — a live Phase Two tenant is required. See `frontend/.env.example` for the required variables (`KEYCLOAK_CLIENT_ID`, `KEYCLOAK_CLIENT_SECRET`, `KEYCLOAK_ISSUER`).

### 5.3 SQL Migrations

```
NN_description.sql     ← two-digit numeric prefix, lowercase, underscores
```

- `NN` is the next free number in `database/sql/`. Check the directory listing before picking a prefix.
- Keep migrations idempotent. A re-run of `setup_database.py` must be safe.
- One logical change per file.

---

## 6. Known Problem Areas

These are active issues that contributors should be aware of before touching the relevant code. They are not bugs to fix speculatively — but understanding them prevents introducing new breakage.

### 6.1 Silent Fire-and-Forget Write Failures

`services/orchestrator/src/workflow.py` has 13 call sites for `_persist_audit` and several for `_persist_memory`. These are fire-and-forget `asyncio.create_task` calls. If the data-normalizer is unreachable or returns a 4xx/5xx, the failure is logged but does not surface to the caller. After any change to the memory or audit write path, check the orchestrator logs explicitly:

```bash
docker compose logs -f orchestrator | grep -i "persist\|memory\|audit"
```

Note also: the `negotiate` audit event type is defined in the schema but is **not** written anywhere in the autonomous negotiation flow (`_run_autonomous_negotiation` in `workflow.py` has zero `_persist_audit` calls). This is a known compliance gap; do not assume the audit trail is complete for negotiated orders.

### 6.2 Port Confusion: demo-gateway vs catalog-normalizer

The demo-gateway (`services/frontend_demo_gateway/`) runs on port **:8015** in Docker (and its default in `workflow.py` is also 8015). Its own README documents `--port 8005`, which is **incorrect** — port 8005 belongs to catalog-normalizer. If you run demo-gateway standalone for local development, use `--port 8015`:

```bash
uvicorn services.frontend_demo_gateway.main:app --port 8015
```

Similarly, negotiation_engine binds container port 8004 but is mapped to host port **:18004** to avoid conflict with orchestrator's :8004. Use `http://localhost:18004` when calling it directly.

### 6.3 Bap-1/ Is Reference Code, Not Live

`Bap-1/` contains a runnable FastAPI server (port 8000), 129 tests, and a `CLAUDE.md`. It is **not** wired into `docker-compose.yml` and is not called by any service in `services/`. Changes to `Bap-1/` have no runtime effect on the live stack.

`Bap-1/` is valuable for two things only:

1. **Wire-shape reference**: `Bap-1/CLAUDE.md` contains 8 hard-won Beckn v2 wire-shape gotchas that apply to all Beckn traffic in the repo. Read it before touching the Beckn adapter.
2. **Protocol-layer tests**: 129 tests cover the Beckn adapter, callbacks, sessions, and LangGraph graph — the only documented end-to-end protocol coverage in the repo.

For new features, write code in `services/`, not `Bap-1/`.

### 6.4 discovery_engine Is Orphaned

`services/discovery_engine/` contains a complete `MultiNetworkCoordinator` (fan-out, deduplication, circuit breakers per network). It has its own `tests/` directory and passes them. However, it has **no entry in `docker-compose.yml`**, is never called by orchestrator or beckn-bap-client, and is not imported by any other service.

The operational discovery path is entirely inside `services/beckn-bap-client/`. Do not extend `discovery_engine` expecting it to affect runtime behaviour, and do not use it as a model for how discovery currently works in production.

### 6.5 catalog-normalizer: OLLAMA_URL, Not OPENAI_API_KEY

The `services/catalog-normalizer/README.md` incorrectly states that `OPENAI_API_KEY` is required for the LLM fallback on `UNKNOWN` catalog formats. The actual implementation in `CatalogNormalizer/llm_fallback.py` uses an Ollama shim — the relevant variables are `OLLAMA_URL` (default `http://localhost:11434/v1`) and `NORMALIZER_MODEL` (default `qwen3:1.7b`). Setting `OPENAI_API_KEY` has no effect. If the fallback is failing, check Ollama availability, not OpenAI credentials.

### 6.6 Dual 22_ Migration Prefix

Two files in `database/sql/` share the `22_` prefix:

- `22_agent_memory_vector_dim.sql`
- `22_pending_approval_columns.sql`

`setup_database.py` sorts files lexicographically; on most POSIX systems `_agent_` sorts before `_pending_`. The two migrations are currently independent, so either execution order is safe. However, if you add a migration that depends on columns from either of these files, pick a prefix of `23` or higher and verify the dependency chain manually.

### 6.7 recovery.py Stubs Log Only

`IntentParser/recovery.py` contains three functions — `log_unmet_demand`, `notify_buyer_no_stock`, `trigger_open_rfq_flow` — that are called when Stage 3 validation returns `not_found`. All three are async stubs that only write to the Python logger. No database write, no external notification, and no RFQ is triggered. Do not add logic to these functions under the assumption that they are being called in a meaningful flow — the recovery path is currently a silent no-op beyond the log line.

---

## 7. Reviewing Others' PRs

When reviewing a PR, check for the following categories of issue in addition to correctness and logic.

### Async patterns

```python
# BAD — blocks the event loop; create_task side effects never run
time.sleep(1)

# GOOD — yields control so tasks can run
await asyncio.sleep(0)
```

- Are new `asyncio.create_task` calls for fire-and-forget operations (not fire-and-await)?
- Is any new coroutine accidentally blocking on I/O with a sync call?
- Are there any new `@pytest.mark.asyncio` decorators? Flag them for removal.

### Error handling

- MCP tool handlers must return `{"found": False, ...}` on all failure paths, never raise.
- New service endpoints should return structured error bodies, not bare exception strings.

### Configuration discipline

- Every new `os.getenv()` outside `config.py` is a convention violation (except the documented carve-out in `mcp-sidecar/bap_client.py`).
- New env vars not in `config.py` will not be visible to services running in Docker (env injection goes through the config object).

### Database migrations

- Is the new migration idempotent? Run `setup_database.py` twice and confirm it does not error.
- Does the prefix follow the correct lexicographic order relative to existing files?

### Beckn traffic routing

Look for any line that constructs a URL ending in `/bpp`, `/seller`, or a port that is not `8081`. All Beckn protocol traffic must route through `onix-bap:8081`. The presence of `select_url` in tests is a good proxy — it must always contain `caller` (i.e. the ONIX caller path).

### Shared library consumers

If `shared/`, `DataNormalizer/`, or `CatalogNormalizer/` changed, confirm that all services importing from those packages are updated and tested in the same PR. A partial update breaks all containers on the next `docker compose up` without a rebuild.
