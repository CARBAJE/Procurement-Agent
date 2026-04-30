# beckn-bap-client

Beckn Protocol v2.0.0 BAP (Buyer Application Platform) client microservice. Receives procurement intents from the Orchestrator and MCP Sidecar, drives the full Beckn transaction lifecycle against the ONIX adapter, and delivers normalised results back to callers.

For a full architectural walkthrough including the Beckn v2.1 wire format, callback correlation, billing/fulfillment payload structure, and known production blockers, see [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

---

## Routes

### Orchestrator-facing

| Method | Path | Description |
|---|---|---|
| `GET` | `/health` | Liveness probe. Returns `{status: "ok", bap_id}`. |
| `POST` | `/discover` | Accepts a `BecknIntent` JSON body. Drives `discover_async()` through ONIX and returns `{transaction_id, offerings[]}`. Accepts an optional `transaction_id` field from the MCP Sidecar (see [Async Discovery](#async-discovery--on_discover-webhook) below). |
| `POST` | `/select` | Sends a `/select` action to ONIX for a chosen offering. |
| `POST` | `/init` | Sends `/init` with buyer billing and fulfillment details. Awaits `on_init` callback. |
| `POST` | `/confirm` | Sends `/confirm` with payment terms. Awaits `on_confirm` callback. |
| `POST` | `/status` | Sends `/status` for an order. Awaits `on_status` callback. |

### ONIX callback receiver

| Method | Path | Description |
|---|---|---|
| `POST` | `/on_discover` | **Primary async webhook for discovery results.** See [Async Discovery](#async-discovery--on_discover-webhook). |
| `POST` | `/bap/receiver/{action}` | Generic callback receiver for `on_select`, `on_init`, `on_confirm`, `on_status`, etc. Routes through `CallbackCollector`. |
| `POST` | `/{action}` | Wildcard — real Beckn network callbacks that arrive directly (bypassing the receiver path). |

### Local BPP catalog (development only)

| Method | Path | Description |
|---|---|---|
| `POST` | `/bpp/discover` | Acts as a local BPP for the `generic-routing-BAPCaller.yaml` discover route. Returns an ACK immediately and fires an async self-callback to `/on_discover`. In production this is replaced by a real Discovery Service. |

---

## Async Discovery — `/on_discover` webhook

### Why this endpoint exists

Beckn v2.0.0 separates the discovery request from its response. `POST /bap/caller/discover` to the ONIX adapter returns only an ACK; catalog results arrive later as a callback to the BAP's `bap_uri`. If the caller (MCP Sidecar) blocks waiting for the `POST /discover` HTTP response, it deadlocks with the BAP Client which itself is waiting on a callback.

The `/on_discover` route breaks this deadlock by publishing the callback payload to **Redis Pub/Sub**. The MCP Sidecar subscribes to the channel before firing the request and receives the payload asynchronously, without holding an HTTP connection open across the Beckn callback boundary.

See [ADR-0001](../../docs/architecture/decisions/0001-use-redis-pubsub-for-async-beckn-responses.md) for the full decision record.

### Handler behaviour (`handler.py::on_discover`)

```
POST /on_discover
      │
      ├─ extract context.transactionId from payload
      │
      ├─ if transactionId present:
      │     PUBLISH beckn_results:{transactionId}  ← Redis (aioredis)
      │     [logs warning if Redis unavailable; continues]
      │
      ├─ CallbackCollector.handle_callback("on_discover", payload)
      │   [backward compat — unblocks discover_async() in the orchestrator flow]
      │
      └─ return {"message": {"ack": {"status": "ACK"}}}  ← HTTP 200
```

The dual publish-and-collect ensures both callers are served:

| Caller | How it receives the result |
|---|---|
| **MCP Sidecar** | Redis `SUBSCRIBE beckn_results:{txn_id}` → `PUBLISH` from this handler |
| **Orchestrator** | `CallbackCollector.collect()` unblocked by `handle_callback()` |

### ONIX routing for on_discover

`config/generic-routing-BAPReceiver.yaml` routes `on_discover` to the root URL `http://beckn-bap-client:8002` — the ONIX adapter appends `/on_discover`, reaching this handler. All other `on_*` callbacks continue to `/bap/receiver/{action}`.

### transaction_id propagation

When the MCP Sidecar calls `POST /discover`, it includes its pre-generated `transaction_id` in the request body alongside the `BecknIntent` fields. The `discover` handler extracts and removes it before constructing `BecknIntent(**body)`, then passes it to `discover_async()` → `build_discover_wire_payload()`, which embeds it in the Beckn `context.transactionId`. This ensures the ONIX log entry and the Redis channel name carry the **same UUID**, making the end-to-end flow observable with a single `redis-cli subscribe` command.

---

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `ONIX_URL` | `http://localhost:8081` | ONIX BAP adapter base URL. In Docker: `http://onix-bap:8081`. |
| `BAP_URI` | `http://localhost:8002` | Public URI of this service. Embedded in every Beckn `context.bapUri`. |
| `BAP_ID` | `bap.example.com` | Beckn subscriber ID. Used for ONIX signing and DeDi registry lookup. |
| `DOMAIN` | `nic2004:52110` | Beckn network domain. Set to `beckn.one/testnet` in Docker Compose. |
| `CALLBACK_TIMEOUT` | `10.0` | Seconds to wait for `on_*` callbacks via `CallbackCollector`. |
| `CATALOG_NORMALIZER_URL` | `http://localhost:8005` | Catalog normalizer endpoint used in `_build_discover_response`. |
| **`REDIS_URL`** | `redis://localhost:6379` | **Redis connection for the `/on_discover` publisher.** Inside Docker, must be `redis://redis:6379`. Set in `docker-compose.yml`. |

> The `redis` Docker service is required at runtime. If Redis is unavailable, `/on_discover` logs a warning and falls through to `CallbackCollector` — the MCP Sidecar will time out after `REDIS_RESULT_TIMEOUT` seconds and return `found=false`.

---

## Running locally (outside Docker)

```bash
# From the repo root
cd services/beckn-bap-client
pip install -r requirements.txt

# Run with Python entry point
ONIX_URL=http://localhost:8081 \
BAP_URI=http://localhost:8002 \
BAP_ID=bap.example.com \
REDIS_URL=redis://localhost:6379 \
python -m src.handler
```

Redis must be reachable at `localhost:6379` (start with `docker compose up -d redis`).
