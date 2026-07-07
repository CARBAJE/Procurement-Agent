# Contributing Guide

This guide covers Git conventions, the pre-submission checklist, documentation expectations, code style, and PR review criteria. For environment setup and first-time configuration see [Installation](INSTALLATION.md).

Cross-references: [Architecture](ARCHITECTURE.md) · [API Reference](API_REFERENCE.md) · [Configuration](CONFIGURATION.md) · [Installation](INSTALLATION.md) · [Database](DATABASE.md)

---

## 1. Git Workflow

### 1.1 Branch Naming

| Prefix | When to use | Example |
|---|---|---|
| `feature/` | New capability or service | `feature/erp-cancel-po-sap` |
| `fix/` | Bug correction | `fix/audit-trail-missing-negotiate-event` |
| `docs/` | Documentation only | `docs/update-contributing-setup` |
| `refactor/` | Internal restructuring, no behaviour change | `refactor/extract-bap-client-retry-logic` |

Branch from `main`. Submit PRs back to `main`. Long-running feature work should rebase onto `main` before opening the PR.

### 1.2 Commit Message Format

```
<type>(<scope>): <imperative summary, ≤72 characters>

Optional body: explain *why*, not *what*. The diff shows what changed;
the commit message explains the motivation and context.

Optional footer: Refs #123, Co-authored-by: Name <email>
```

- **Imperative, present tense**: "add audit event for negotiation round" not "added" or "adds".
- **Scope** is the service or module: `orchestrator`, `intent-parser`, `data-normalizer`, `frontend`, `database`, `mcp-sidecar`, etc.
- **Types**: `feat`, `fix`, `refactor`, `test`, `docs`, `chore`.

### 1.3 PR Process

1. Open the PR against `main` with a description that answers:
   - **What** changed (brief summary).
   - **Why** it was needed (motivation, linked issue if any).
   - **How to test** it manually (curl command, unit test path, or acceptance step).
2. Keep PRs focused. A PR that touches both a new feature and an unrelated refactor should be split.
3. Ensure the pre-submission checklist (Section 2) is complete before requesting review.
4. At least one approval is required before merging.

---

## 2. Pre-Submission Checklist

Work through this list before marking a PR ready for review.

### Async and Python conventions

- [ ] All new functions in IntentParser, services, and Bap-1 are `async def` coroutines. The sync wrapper in `IntentParser.core.parse_request` exists only for legacy callers and disables Stage 3 — do not extend it.
- [ ] No `@pytest.mark.asyncio` decorators anywhere. `asyncio_mode = auto` in `pytest.ini` handles coroutine collection globally; the decorator breaks pytest-asyncio 0.21+.
- [ ] No `time.sleep()` inside coroutines. Use `await asyncio.sleep(0)` or `await asyncio.sleep(n)` to yield the event loop so `asyncio.create_task` side effects (e.g. cache writes) can complete.
- [ ] No inline `os.getenv(...)` calls outside `config.py`. The exception is `services/mcp-sidecar/bap_client.py` which reads `REDIS_URL` and `REDIS_RESULT_TIMEOUT` via `os.getenv()` because these must be real shell variables — do not extend this pattern elsewhere.

### Configuration

- [ ] New environment variables are added in three places: the service's `config.py`, the root `.env.example`, and [CONFIGURATION.md](CONFIGURATION.md).
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
- [ ] If a service was added or removed, the Component Reference section of [ARCHITECTURE.md](ARCHITECTURE.md) and `docker-compose.yml` comments are updated.
- [ ] `CLAUDE.md` "What NOT to do" section was reviewed; no new code violates its constraints.

### Wire-shape

- [ ] `Contract.status.code` uses only `DRAFT | ACTIVE | CANCELLED | COMPLETE`. ONIX rejects other values.
- [ ] No billing or fulfillment data is placed inline in `Contract` (`additionalProperties: false`). Buyer info belongs in `participants[role=buyer]`, fulfillment in `performance[]`, payment in `settlements[]`.
- [ ] Read `Bap-1/CLAUDE.md` wire-shape gotchas before modifying any Beckn adapter, ONIX URL construction, or `Contract` shape.

---

## 3. Documentation Standards

### 3.1 New Service

Every new service directory must contain a `README.md` with these sections:

| Section | Contents |
|---|---|
| Role | One paragraph: what problem this service solves, which other services call it, which it calls. |
| Architecture diagram | Mermaid `flowchart TD` or `sequenceDiagram` showing inputs, outputs, and the main data path. |
| API endpoints | Table: method, path, request schema summary, response schema summary. |
| Configuration | Table: env var name, description, default, required/optional. |
| Run command | Exact command for local dev and for Docker. |
| Testing | How to run the service's tests; infra required. |

### 3.2 Shared Library Changes

`shared/`, `DataNormalizer/`, and `CatalogNormalizer/` are volume-mounted into multiple containers. Changes take effect immediately in running containers without a rebuild, but they affect all consumers simultaneously.

When modifying a shared model:

- Check all services that import from the changed module (use `grep -r "from shared"` / `from DataNormalizer` across `services/`).
- Update the Pydantic model and all consumers in the same PR.
- Run the unit tests for every consumer that has a test suite before opening the PR.

### 3.3 Significant Features

For substantial new features (a new pipeline stage, a new async flow, a new integration):

- Add a record to `docs/architecture/decisions/` following the ADR format in `0001-use-redis-pubsub-for-async-beckn-responses.md`.
- Update the relevant `KnowledgeBase/project_scaffold/` notes if they cover the changed area.
- Consider whether `ARCHITECTURE.md` (including §9 Component Reference) needs a structural update.

---

## 4. Code Style

### 4.1 Python

- PEP 8. Line length 100 characters.
- **Type hints on all function signatures.** Return types included.
- **Pydantic v2 `field_validator` decorators**, not the deprecated `@validator`. Use `model_validator(mode='before')` for cross-field validation.
- `BecknIntent` is the canonical NL-derived intent model in `shared/models.py`. Its fields have strict types: `delivery_timeline` is `int` (hours, not ISO 8601 strings), `location_coordinates` is `"lat,lon"` decimal string (not a city name), `budget_constraints` is typed `{max: float, min: float}`.
- **Error handling in MCP tools**: return `{"found": False, ...}` on all failure paths. Never raise. See `services/mcp-sidecar/server.py::search_bpp_catalog`.
- Discovery POSTs from the MCP sidecar use `asyncio.create_task(...)`, not `await`. Awaiting the POST reintroduces the deadlock that [ADR-0001](../docs/architecture/decisions/0001-use-redis-pubsub-for-async-beckn-responses.md) was written to prevent.

### 4.2 TypeScript (Frontend)

- Strict mode (`"strict": true` in `tsconfig.json`).
- Component library: Radix UI primitives with Tailwind utility classes. Do not import a second component library.
- All backend calls go through the Axios wrappers in `frontend/src/lib/api.ts`. Do not add raw `fetch` calls in page components.
- The frontend uses NextAuth with Phase Two hosted Keycloak (`KeycloakProvider` only). There are no stub credentials for local dev — a live Phase Two tenant is required. See `frontend/.env.example` for the required variables (`KEYCLOAK_CLIENT_ID`, `KEYCLOAK_CLIENT_SECRET`, `KEYCLOAK_ISSUER`).

### 4.3 SQL Migrations

```
NN_description.sql     ← two-digit numeric prefix, lowercase, underscores
```

- `NN` is the next free number in `database/sql/`. Check the directory listing before picking a prefix.
- Keep migrations idempotent. A re-run of `setup_database.py` must be safe.
- One logical change per file.

---

## 5. Reviewing Others' PRs

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
