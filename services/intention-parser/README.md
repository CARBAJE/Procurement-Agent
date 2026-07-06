# intention-parser (Docker container)

Lightweight HTTP wrapper that exposes the `IntentParser/` package as a container service within the Docker Compose stack. Serves the intent parsing function via aiohttp on port 8001 — the same port as the local `IntentParser/api.py` FastAPI app, but with a simpler contract (Stage 1+2 only, no pgvector or MCP).

## Relationship to IntentParser/

This service is NOT a copy of `IntentParser/`. It is a thin adapter that imports and calls the `IntentParser` package at runtime.

| | `IntentParser/api.py` (local FastAPI) | `services/intention-parser` (Docker) |
|-|---------------------------------------|--------------------------------------|
| Framework | FastAPI | aiohttp |
| Stages | Stage 1 + 2 + 3 + recovery | Stage 1 + 2 only (`enable_stage3=False`) |
| pgvector | Yes — pool initialized at startup | No |
| MCP sidecar | Yes — called from Stage 3 | Never invoked |
| Endpoints | `/parse`, `/parse/batch`, `/parse/full` | `/health`, `/parse` |
| Intent field | Full granular type (`SearchProduct`, etc.) | Mapped to `"procurement"` or `"unknown"` |

## Bind-mount architecture

`IntentParser/` and `shared/` are **not** baked into the image. Docker Compose mounts the host directories into the container at `/app/`. This means:

- Hot-reload: code changes in `IntentParser/` take effect without rebuilding the image.
- The image alone is not runnable — it requires the volume mounts.
- LLM credentials (`ANTHROPIC_API_KEY`, Ollama URL) must be present in the container's environment.

## Endpoints

### `GET /health`

```json
{"status": "ok", "service": "intention-parser"}
```

### `POST /parse`

**Request:**
```json
{"query": "300 meters Cat6 UTP cable Mumbai 5 days"}
```

**Response:**
```json
{
  "intent": "procurement",
  "confidence": 0.97,
  "beckn_intent": {
    "item": "Cat6 UTP Cable",
    "descriptions": ["UTP"],
    "quantity": 300,
    "unit": "unit",
    "delivery_timeline": 120,
    "location_coordinates": "19.0760,72.8777",
    "budget_constraints": null
  },
  "routed_to": "qwen3:8b"
}
```

**Intent mapping:** The granular intent types from Stage 1 (`SearchProduct`, `RequestQuote`, `PurchaseOrder`, etc.) are all mapped to `"procurement"`. Anything that fails Stage 1's procurement gate returns `"unknown"` with `beckn_intent: null`.

**Note on `unit`:** The container appends a hardcoded `"unit": "unit"` to the `beckn_intent` dict regardless of the extracted unit value. Use `IntentParser/api.py` directly if you need the unmodified unit field.

## Configuration

| Var | Required | Description |
|-----|----------|-------------|
| `PORT` | No (default `8001`) | Listen port |
| `OLLAMA_URL` | Yes | Ollama base URL (e.g. `http://host.docker.internal:11434/v1`) |
| `COMPLEX_MODEL` | No | Model for Stage 1+2 complex queries |
| `SIMPLE_MODEL` | No | Model for simple queries |
| `ANTHROPIC_API_KEY` | No | Enables Claude broadening fallback in recovery |

The `IntentParser/` package requires `DB_*` env vars at import time even though Stage 3 is disabled. Set them to any valid Postgres connection or use `DB_USER=` (empty) to skip pool initialization.

## Run

```bash
docker compose up -d intention-parser

# Or standalone (requires IntentParser/ and shared/ on the host):
docker run -p 8001:8001 \
  -v ./IntentParser:/app/IntentParser \
  -v ./shared:/app/shared \
  -e OLLAMA_URL=http://host.docker.internal:11434/v1 \
  intention-parser

# Debug locally without Docker:
PYTHONPATH=. python services/intention-parser/src/handler.py
```
