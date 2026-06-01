---
name: async-test-patterns
description: pytest-asyncio + aioresponses + dual-mode (mock/live) test conventions used in IntentParser/, Bap-1/, and database/. Auto-invoke when writing or modifying any test that touches async coroutines, FastAPI/aiohttp endpoints, MCP, Redis Pub/Sub, or asyncio.create_task fire-and-forget side effects.
tools: Read, Grep, Glob, Edit, Bash
---

# Async test conventions for THIS project

Three test layouts coexist. Pick the one that matches the module you're touching.

## Layout 1 — `IntentParser/tests/`

- `IntentParser/pytest.ini` sets `asyncio_mode = auto` and `pythonpath = ..` so the package imports as `IntentParser.*`.
- Marker: `integration` — requires Ollama running (`qwen3:8b`). Default CI/dev should run `-m "not integration"`.

### Dual-mode pattern (`test_async_pipeline.py`)

The same suite runs against mocks (default, < 1 s, zero infra) or against real services (PostgreSQL + Ollama + MCP sidecar) controlled by `INTENT_PARSER_TEST_MODE`:

```python
_MODE = os.getenv("INTENT_PARSER_TEST_MODE", "mock").lower()
_LIVE = _MODE == "live"
```

Mock mode: an autouse `_patch_llm` fixture replaces Stage 1+2 LLM calls with `AsyncMock`; `query_semantic_cache` returns hardcoded `CacheMatch` objects; `MCPSidecarClient` is a `MagicMock`; `MCPResultAdapter.write_path_b_row` is patched to `AsyncMock` (no-op).

Live mode: `_live_seed` fixture inserts test rows with `bpp_id = "bpp_test_async_pipeline"` (tombstone key) before each relevant test, and DELETEs them at teardown. **Sleep before DELETE** — `await asyncio.sleep(2)` — so any in-flight Path B writes land before cleanup.

### Path B fire-and-forget writes

`MCPResultAdapter.write_path_b_row` runs as `asyncio.create_task` from `validation.py`. Tests that exercise the MCP path must flush it:

- Mock: `await asyncio.sleep(0)` after the `POST /parse/full` response — yields once so the patched `AsyncMock` records the call.
- Live: `await asyncio.sleep(3)` after the POST gives the real INSERT time to land.

### FastAPI under test

```python
from httpx import ASGITransport, AsyncClient
from IntentParser.api import app

# httpx.ASGITransport (0.28) does NOT trigger ASGI lifespan.
# IntentParser.db.get_pool() handles lazy init — no manual lifespan mock needed.
async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
    resp = await ac.post("/parse/full", json={"query": "..."})
```

### Markers and selection

```bash
pytest IntentParser/ -m "not integration" -v            # 15 unit tests, no infra
pytest IntentParser/ -v                                 # all 33 (Ollama needed)
pytest IntentParser/ -m integration -v -s               # 18 legacy milestone tests
INTENT_PARSER_TEST_MODE=live pytest IntentParser/tests/test_async_pipeline.py -v -s
```

## Layout 2 — `Bap-1/tests/`

- `Bap-1/pytest.ini` sets `asyncio_mode = auto` and `pythonpath = ..`.
- All HTTP is mocked with `aioresponses`. Fixtures point to `http://mock-onix.test` — a non-existent host that only resolves inside the `aioresponses` context manager.

```python
# Bap-1/tests/conftest.py
@pytest.fixture
def adapter(beckn_config):
    return BecknProtocolAdapter(beckn_config)

@pytest.fixture
def collector():
    return CallbackCollector(default_timeout=0.5)
```

`BecknConfig` is constructed with field values **directly in tests** (not from `.env`) to keep tests hermetic.

### `CallbackCollector` pattern

The async Beckn flow uses `register()` BEFORE the action send and `cleanup()` after `collect()`. Tests that simulate callbacks call `aioresponses.post(...)` to register the ACK, then `await collector.deliver(...)` to simulate the webhook arrival.

### Intent parser facade tests

`Bap-1/tests/test_intent_parser.py` mocks `IntentParser.parse_request` with `pytest-mock`. Run unit subset with `-k "not integration"`; integration subset (`-m integration`) needs Ollama + qwen3:8b.

## Layout 3 — `database/test_database.py`

Sync pytest with `psycopg2`. The `workflow_ids` session-scoped fixture inserts a full FK chain on session start and deletes in reverse order at teardown. New tables that join the chain → extend that fixture.

## What NOT to do

- **Don't mock the database** in IntentParser tests that touch Stage 3 ANN logic — use the live mode against a real PG/pgvector. ANN ranking is exactly the kind of thing that "passes against mocks but fails in prod".
- **Don't use `pytest.mark.asyncio` decorators** — `asyncio_mode = auto` is set in both `pytest.ini` files. Adding the decorator silently overrides and can cause confusion.
- **Don't `time.sleep()` to wait for `asyncio.create_task`** — use `await asyncio.sleep(...)`. Sync sleep blocks the event loop and the task never runs.
- **Don't share `aioresponses` contexts across tests.** Use a fresh `with aioresponses() as m:` per test.
- **Don't mix layouts.** A new test that imports both `IntentParser.*` and `src.*` (Bap-1 namespace) will fail because `pythonpath` is `..` from each module's pytest.ini, not the repo root.
