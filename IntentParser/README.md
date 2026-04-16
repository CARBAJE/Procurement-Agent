# IntentParser — Beckn Procurement Intent Microservice

Parses natural-language procurement queries into structured Beckn-compatible intents using a local LLM (Ollama) via `instructor`.

## Stack
- `instructor` — structured LLM extraction with automatic retries
- `pydantic` — schema validation
- `fastapi` + `uvicorn` — HTTP layer

## Setup

```bash
pip install -r requirements.txt
```

Requires [Ollama](https://ollama.com) running locally with the configured models:

```bash
ollama pull qwen3:8b
ollama pull qwen3:1.7b   # optional, used for simple queries
```

## Run

```bash
uvicorn IntentParser.api:app --reload
```

## Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/parse` | Parse a single query |
| `POST` | `/parse/batch` | Parse multiple queries in parallel |

### Example

```bash
curl -X POST http://localhost:8000/parse \
  -H "Content-Type: application/json" \
  -d '{"query": "I need 500 units of A4 paper 80gsm delivered to Bangalore in 5 days, budget under 2 INR per sheet"}'
```

## Configuration

Override defaults via environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `OLLAMA_URL` | `http://localhost:11434/v1` | Ollama base URL |
| `COMPLEX_MODEL` | `qwen3:8b` | Model for complex queries |
| `SIMPLE_MODEL` | `qwen3:1.7b` | Model for simple queries |

## Module layout

```
schemas.py   — Pydantic models + location resolver
core.py      — prompts, client, routing heuristic, pipeline
api.py       — FastAPI endpoints (thin wrapper over core)
```
