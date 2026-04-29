---
tags: [component, ai, nlp, intent-parsing, structured-output, ollama, instructor, qwen3, microservice, lambda]
cssclasses: [procurement-doc, component-doc]
status: "#implemented"
related: ["[[llm_providers]]", "[[beckn_bap_client]]", "[[microservices_architecture]]", "[[phase1_foundation_protocol_integration]]"]
---

# Component: Natural Language Intent Parser

> [!architecture] Role in the System
> `services/intention-parser/` is **Lambda 1** in the Step Functions state machine. It is a standalone aiohttp microservice on port 8001 that wraps the `IntentParser/` module. The Parser Agent (Ollama `qwen3:1.7b` locally, GPT-4o/Claude Sonnet 4.6 in production) lives embedded inside this service.

## HTTP Interface

```
POST /parse
Body:     { "query": "500 A4 paper Bangalore 3 days" }
Response: { "intent", "confidence", "beckn_intent", "routed_to" }
```

- `intent` = `"procurement"` for `SearchProduct / RequestQuote / PurchaseOrder`, `"unknown"` otherwise
- `beckn_intent` = `null` when `intent == "unknown"`
- `routed_to` = model name used (`"qwen3:1.7b"`, `"qwen3:8b"`, etc.)

```
GET /health
Response: { "status": "ok", "service": "intention-parser" }
```

## Internal Structure

```
services/intention-parser/
├── src/handler.py       aiohttp server — POST /parse wraps IntentParser.parse_request()
├── Dockerfile
└── requirements.txt

IntentParser/             mounted as Docker volume at /app/IntentParser
shared/                   mounted as Docker volume at /app/shared
```

`handler.py` does `sys.path.insert(0, "/app")` so both `IntentParser` and `shared` are importable.

## Parser Agent

The `IntentParser/` module contains the embedded Parser Agent:
- **Simple queries** (≤120 chars, <2 numbers): `SIMPLE_MODEL` (default `qwen3:1.7b`)
- **Complex queries** (longer, multiple numbers, keywords): `COMPLEX_MODEL` (default `qwen3:1.7b`)
- Model routing via env vars — no code changes needed to switch to production LLMs
- Uses `instructor` + OpenAI-compatible API (`OLLAMA_URL` env, default `http://localhost:11434/v1`)

## Shared Model: `BecknIntent`

`shared/models.py` is the **single source of truth** for `BecknIntent`. `IntentParser/schemas.py` imports it directly. The `/parse` response includes the serialized `BecknIntent` dict that the orchestrator passes to `beckn-bap-client`.

## Called By

The orchestrator calls this service as **Step 1**:
```python
parse_result = POST http://intention-parser:8001/parse  { "query": query }
```

If `intent != "procurement"`, the orchestrator aborts the pipeline and returns an error.

## LLM Configuration

| Env Var | Dev Default | Production |
|---------|------------|------------|
| `OLLAMA_URL` | `http://localhost:11434/v1` | Not used |
| `COMPLEX_MODEL` | `qwen3:1.7b` | `gpt-4o` or `claude-sonnet-4-6` |
| `SIMPLE_MODEL` | `qwen3:1.7b` | `gpt-4o` or `claude-sonnet-4-6` |
