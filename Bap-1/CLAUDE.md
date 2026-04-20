# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Run all tests
pytest tests/ -v

# Run a single test file
pytest tests/test_discover.py -v

# Run a single test by name
pytest tests/test_discover.py::test_discover_returns_offerings -v

# Run unit tests for the NL parser facade (no Ollama needed — LLM is mocked)
pytest tests/test_intent_parser.py -v -k "not integration"

# Run integration tests (requires Ollama running with qwen3:8b)
pytest tests/test_intent_parser.py -v -m integration

# Start the Docker stack (onix-bap, onix-bpp, sandbox-bpp, redis)
cd starter-kit/generic-devkit/install
docker compose -f docker-compose-my-bap.yml up -d

# Run the end-to-end flow (Docker stack must be running)
python run.py                                    # hardcoded intent
python run.py "500 A4 paper Bangalore 3 days"   # NL query (requires Ollama)

# Run the server standalone
python -m src.server       # NOT python src/server.py (import resolution breaks)
```

## Architecture

This is a **Beckn Protocol v2 BAP (Buyer Application Platform)** — the buyer side of an open commerce network. The Python layer never talks directly to BPPs (sellers); all traffic routes through a **beckn-onix adapter** (Go service, port 8081) which handles ED25519 signing and network routing.

### Two-phase flow

**Discovery (async):** BAP sends `POST /bap/caller/discover` to ONIX adapter → adapter routes to the local catalog endpoint (`/bpp/discover` on `src/server.py`) → server ACKs immediately and fires an async `on_discover` callback back to `/bap/receiver/on_discover` → `CallbackCollector` wakes up `discover_async()`.

**Transactional actions (async):** `/select`, `/init`, `/confirm`, `/status` go to `POST /bap/caller/{action}` on the ONIX adapter. The adapter routes to `onix-bpp` → `sandbox-bpp`, which generates the `on_*` callback. The callback travels back through `onix-bpp` → `onix-bap` → `host:8000/bap/receiver/{action}` → `CallbackCollector`.

### Layer responsibilities

- **`src/beckn/models.py`** — Pydantic v2 protocol models. `BecknIntent` and `BudgetConstraints` are defined in `shared/models.py` (repo root) and re-exported here — all imports from `src.beckn.models` still work. Never put protocol-formatting logic outside the beckn/ layer.

- **`src/beckn/adapter.py`** — Builds protocol messages (UUID transaction IDs, RFC 3339 timestamps, context headers). Owns all URL construction — `discover_url`, `select_url`, `caller_action_url(action)`. Nothing else should construct Beckn URLs.

- **`src/beckn/client.py`** — Thin async HTTP layer (aiohttp). `discover_async()` sends to `onix-bap` and waits for the `on_discover` callback via `CallbackCollector`. `select()` returns the ACK dict. No protocol logic here.

- **`src/beckn/callbacks.py`** — `CallbackCollector` uses one `asyncio.Queue` per `(transaction_id, action)` tuple. This is how the async callbacks are correlated back to the code that sent the request. Always `register()` before sending the action, `cleanup()` after `collect()`.

- **`src/server.py`** — aiohttp server on port 8000. Two routes: `POST /bap/receiver/{action}` receives all inbound callbacks and dispatches to `CallbackCollector`; `POST /bpp/discover` acts as the local catalog service (receives discover from `onix-bap`, fires async `on_discover` back). A module-level `collector` singleton is shared between `server.py` and `run.py`.

- **`mock_onix.py`** — Legacy mock of the Go beckn-onix adapter. Used only by unit tests (via `aioresponses`). Not used for local dev — the real `onix-bap` Docker container replaces it.

### Test setup

All tests mock HTTP with `aioresponses`. The `conftest.py` fixtures (`adapter`, `collector`) point to `http://mock-onix.test` — a non-existent host that only works inside `aioresponses` context managers. `pytest-asyncio` runs all `async def test_*` automatically (`asyncio_mode = auto` in `pytest.ini`).

### NL Intent Parser (`src/nlp/`)

Implemented as a **Facade** over the standalone `IntentParser/` module (one level above `Bap-1/`).

- **`src/nlp/intent_parser_facade.py`** — single public function `parse_nl_to_intent(query) -> BecknIntent | None`. Returns `None` for non-procurement queries. No type conversion needed — both modules share `shared/models.BecknIntent`.
- **IntentParser** uses `instructor` + Ollama (`qwen3:8b` complex, `qwen3:1.7b` simple). Routing heuristic: query > 120 chars or ≥ 2 numbers or procurement keywords → complex model.
- **Path resolution**: `pytest.ini` has `pythonpath = ..` so tests find `IntentParser/`; `run.py` does `sys.path.insert` for runtime.
- **Unit tests** mock `parse_request` — no Ollama needed. Integration tests (`-m integration`) require Ollama running with `qwen3:8b`.

## Key constraints

- `BecknIntent.delivery_timeline` is **hours as int** (72 = 3 days), not ISO 8601 (`P3D`). The NL parser converts "3 days" → 72 before building the intent.
- The `select_url` must always contain `caller` in the path — tests enforce that `/select` never goes directly to a BPP.
- `BecknConfig` is constructed with field values directly in tests (not from `.env`) to keep tests hermetic.
- Beckn v2.0.0 `/select` uses `{ contract: { commitments, consideration } }` — **not** `{ order: ... }`. The ONIX adapter validates against the official spec and rejects `order`.
- `SelectedItem` carries optional `name`, `price_value`, `price_currency` fields used to build the `contract` wire payload. Always pass these from the `DiscoverOffering` when calling `client.select()`.
- The ONIX adapter appends the action name to the routing target URL — e.g. target `http://host:8000/bpp` + action `discover` → `http://host:8000/bpp/discover`. Never include the action name in the target URL inside routing config files.
