# MCP Sidecar — Beckn ONIX Search Bridge

A stateless [Model Context Protocol (MCP)](https://modelcontextprotocol.io) server that bridges the **IntentParser**'s Stage 3 validation logic with the live **Beckn ONIX network** via the BAP Client. When the IntentParser's pgvector semantic cache misses (cosine similarity < 0.45), it calls this sidecar to probe the live network for matching BPP catalog entries.

---

## 🎯 Overview

The sidecar exposes a single MCP tool — `search_bpp_catalog` — over **SSE transport** on port `3000`. The IntentParser connects via its `mcp_client.py` using the standard MCP SSE protocol:

```
GET  /sse         → opens SSE stream; server sends "endpoint" event with POST URL
POST /messages/   → JSON-RPC 2.0 tools/call dispatcher
SSE stream        → "message" event carries the JSON-RPC response
```

### Key design properties

**Stateless.** The sidecar holds no cache and no session state between requests. Every `search_bpp_catalog` call results in a live `POST /discover` request to the BAP Client. Semantic caching is exclusively owned by the IntentParser's Stage 3 `pgvector` database — adding a second cache here would create a "Two Sources of Truth" anti-pattern.

**"Never Throw" contract.** The tool handler wraps its entire body in a `try/except`. No matter what fails — BAP Client timeout, connection refused, malformed ONIX response, or an unexpected runtime error — the sidecar always returns a clean JSON object to the caller. It never emits a JSON-RPC `error` response. Failures surface as `{"found": false, "items": [], "probe_latency_ms": <elapsed>}`.

**Local semantic ranking.** After a successful BAP response, results are ranked by cosine similarity between the buyer's `item_name` and each ONIX catalog descriptor name, using `all-MiniLM-L6-v2` (384-dimensional, the same model as IntentParser Stage 3). Items scoring below `RANKING_MIN_SIMILARITY` are filtered out. Business-logic ranking (price, rating, delivery SLA) is out of scope and belongs to the downstream Comparison Engine.

### Architecture position

```
IntentParser (Python :8001)
        │
        │  GET /sse + POST /messages/
        │  MCP SSE transport
        ▼
MCP Sidecar (Python :3000)   ← this service
        │
        │  POST /discover
        │  Authorization: Bearer <BAP_API_KEY>
        ▼
BAP Client (Python :8002)
        │
        │  Beckn /search broadcast
        ▼
ONIX Network (external Beckn P2P)
```

---

## 📋 Prerequisites

| Requirement | Version | Notes |
|---|---|---|
| Python | 3.11+ | Must match the project's conda environment |
| conda environment | `infosys_project` | Used for all package management in this project |
| BAP Client | running on `:8002` | Required for live ONIX probes; sidecar will time out gracefully if unavailable |

The sidecar downloads `all-MiniLM-L6-v2` from the Hugging Face Hub on first startup. Subsequent starts use the local model cache (`~/.cache/huggingface/`). Ensure outbound internet access or a pre-populated cache for air-gapped deployments.

---

## ⚙️ Environment Variables

All configuration is read from environment variables at startup. The sidecar also supports a `.env` file in the working directory (loaded via `pydantic-settings`). A `.env` file **must never be committed to version control** — use it only for local development.

| Variable | Default | Required | Description |
|---|---|---|---|
| `BAP_API_KEY` | *(none)* | **Mandatory** | API key or JWT for authenticating requests to the BAP Client. Passed as `Authorization: Bearer <value>` on every `POST /discover` call. **The service will raise a `ValidationError` and refuse to start if this variable is absent from the environment.** |
| `BAP_CLIENT_URL` | `http://localhost:8002` | Optional | Base URL of the BAP Client service. In Docker Compose, set to `http://beckn-bap-client:8002`. |
| `PORT` | `3000` | Optional | Port the SSE server listens on. Must match `MCP_SSE_URL` configured in the IntentParser. |
| `MCP_BAP_TIMEOUT` | `3.0` | Optional | Seconds the sidecar waits for a `POST /discover` response before cancelling the request and returning `found: false`. The IntentParser's outer `MCP_PROBE_TIMEOUT=8s` is a separate, wider safety net. |
| `RANKING_MIN_SIMILARITY` | `0.30` | Optional | Cosine similarity threshold (0–1) below which ONIX results are discarded before being returned to the IntentParser. Scores are computed with `all-MiniLM-L6-v2`; higher values produce more precise but potentially empty result sets. |

### Example `.env` file (local development only)

```dotenv
BAP_API_KEY=dev-secret-key-replace-in-production
BAP_CLIENT_URL=http://localhost:8002
PORT=3000
MCP_BAP_TIMEOUT=3.0
RANKING_MIN_SIMILARITY=0.30
```

> **Production note:** `BAP_API_KEY` must be injected from a Secrets Manager (AWS Secrets Manager, GCP Secret Manager, Vault, etc.) as an environment variable at container startup. It must never appear in Dockerfiles, image layers, or source control.

---

## 🚀 How to Run (Local Development)

### 1. Install dependencies

Run from inside the `services/mcp-sidecar/` directory:

```bash
conda activate infosys_project
pip install -r requirements.txt
```

The first install will download `all-MiniLM-L6-v2` (~90 MB) into the Hugging Face model cache.

### 2. Start the server

**Option A — uvicorn (recommended, matches production)**

```bash
BAP_API_KEY=dev-secret-key uvicorn server:app --host 0.0.0.0 --port 3000 --reload
```

**Option B — direct Python entry point**

```bash
BAP_API_KEY=dev-secret-key python server.py
```

Both options bind to `0.0.0.0:3000` and log to stdout. The `--reload` flag in Option A restarts the server on code changes.

### 3. Verify the server is ready

```bash
curl -N http://localhost:3000/sse
```

Expected output (an open SSE stream — press `Ctrl+C` to close):

```
event: endpoint
data: /messages/?session_id=<uuid>

```

If `BAP_API_KEY` was not set, the process will have exited before binding with:

```
pydantic_settings.errors.SettingsError: ... field required ... bap_api_key
```

### 4. IntentParser integration

The IntentParser's `mcp_client.py` connects to the sidecar using the `MCP_SSE_URL` environment variable. Ensure both services are running and the URL is correctly set:

```bash
# In the IntentParser environment
export MCP_SSE_URL=http://localhost:3000/sse
```

---

## 🛠️ Tool Schema & Contract

### `search_bpp_catalog`

The only tool this sidecar exposes. Called by the IntentParser's Stage 3 hybrid validation on every pgvector cache miss.

#### Input

| Argument | Type | Required | Description |
|---|---|---|---|
| `item_name` | `string` | Yes | Canonical item name extracted by the IntentParser (e.g. `"Stainless Steel Flanged Ball Valve"`). A blank or whitespace-only value returns `found: false` immediately without calling the BAP Client. |
| `descriptions` | `array[string]` | Yes | Specification tokens from the BecknIntent (e.g. `["PN16", "2 inch", "SS316"]`). An empty array `[]` is valid — it means no specification tokens were extracted. |
| `domain` | `string` | Yes | Beckn domain identifier (e.g. `"procurement"`). Mapped directly into the Beckn `context.domain` field. The sidecar imposes no allowlist; multi-domain support is achieved by updating this argument. |
| `version` | `string` | Yes | Beckn protocol version (e.g. `"1.1.0"`). Mapped into `context.version`. |
| `location` | `string` | No | Buyer location as `"lat,lon"` (e.g. `"12.9716,77.5946"`). If present, populates `fulfillment.end.location.gps` in the BAP payload. Omit if unknown. |

#### Output — successful probe

```json
{
  "found": true,
  "items": [
    {
      "item_name": "Stainless Steel Flanged Ball Valve PN16 2 inch",
      "bpp_id": "bpp-industrial-supplies-mumbai",
      "bpp_uri": "https://bpp.industrialsupplies.in/beckn"
    }
  ],
  "probe_latency_ms": 1420
}
```

`items` is sorted descending by cosine similarity to the input `item_name`. Items below the `RANKING_MIN_SIMILARITY` threshold are excluded before this response is returned.

#### Output — all failure paths

```json
{
  "found": false,
  "items": [],
  "probe_latency_ms": 3000
}
```

This shape is returned for: BAP Client timeout, BAP Client unreachable, zero ONIX matches, malformed ONIX response, blank required argument, or any unhandled internal exception. `probe_latency_ms` is the actual elapsed time; on a timeout it approximates `MCP_BAP_TIMEOUT × 1000`.

#### Field reference

| Field | Type | Description |
|---|---|---|
| `found` | `boolean` | `true` only when `items` is non-empty after ranking and filtering. |
| `items[].item_name` | `string` | Canonical BPP catalog descriptor name. May differ from the input `item_name` — this is the seller's name, not the buyer's. |
| `items[].bpp_id` | `string` | Beckn identifier of the BPP (seller platform). Used by the IntentParser to address subsequent `init`, `confirm`, and `status` actions. |
| `items[].bpp_uri` | `string` | Base URI of the BPP's Beckn endpoint. Allows the BAP Client to route directly to the BPP without a registry lookup on subsequent calls. |
| `probe_latency_ms` | `integer` | Wall-clock milliseconds from when the sidecar dispatched the `POST /discover` request to when it received (or timed out on) the response. Use for ONIX network health monitoring. |

---

## Module Structure

```
services/mcp-sidecar/
├── server.py         FastMCP server — tool registration, ASGI app, entry point
├── bap_client.py     Async HTTP client for POST /discover to the BAP Client
├── ranking.py        Semantic ranking with all-MiniLM-L6-v2 (ThreadPoolExecutor)
├── config.py         pydantic-settings environment configuration
└── requirements.txt  Python dependencies
```

Dependencies flow strictly downward: `server` → `bap_client`, `ranking`, `config`. No module imports from `server`.
