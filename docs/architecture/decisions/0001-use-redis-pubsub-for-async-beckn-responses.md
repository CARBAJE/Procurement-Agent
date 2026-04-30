# ADR-0001: Use Redis Pub/Sub to decouple Beckn v2.0.0 async discovery responses

| Field | Value |
|---|---|
| **Status** | Accepted |
| **Date** | 2026-04-30 |
| **Deciders** | Lead Python Integrations Engineer, Lead DevOps Engineer |
| **Supersedes** | — (first architecture decision record) |

---

## Context

### The Beckn v2.0.0 async contract

Beckn Protocol v2.0.0 enforces a strict request-acknowledge-callback pattern for all network actions. When a BAP sends `POST /discover` to the ONIX adapter:

1. ONIX immediately returns an `{"message": {"ack": {"status": "ACK"}}}` — it does **not** return catalog results.
2. BPPs process the discovery request on their own schedules.
3. Catalog results arrive later as a separate `POST /on_discover` HTTP callback sent to the BAP's registered `bap_uri`.

This is correct and intentional behaviour defined by the protocol. The problem was in how our code expected to receive the results.

### The synchronous deadlock

The original `services/mcp-sidecar/bap_client.py` implementation called `POST /discover` on the BAP Client and then **blocked on the HTTP response** waiting for catalog items:

```
MCP Sidecar                 BAP Client
───────────                 ──────────
POST /discover ──────────►  discover_async()
                              │  waits for on_discover callback
await resp.json() ◄──────── return {offerings: [...]}
```

This created two interacting problems:

1. **Connection hold**: The sidecar's `httpx.AsyncClient` held the HTTP connection open for the entire round-trip — including the Beckn network's async callback leg. Under the default `mcp_bap_timeout = 3.0 s`, any ONIX routing delay caused a timeout before results arrived.

2. **Routing deadlock in ONIX**: `generic-routing-BAPCaller.yaml` correctly routes discover to `http://beckn-bap-client:8002/bpp/discover` (the local catalog endpoint). This endpoint fires a self-callback via `asyncio.create_task(_send_local_on_discover)`. Because the sidecar was blocking on the original HTTP connection, and the BAP Client was internally waiting on `CallbackCollector.collect()`, any additional load caused both services to deadlock waiting on each other.

3. **Redis connectivity gap**: `beckn-bap-client` had no `REDIS_URL` environment variable; the `on_discover` handler defaulted to `redis://localhost:6379`, which resolves to the container's own loopback — not the `redis` Docker service. Every Redis publish silently failed:

   ```
   WARNING: Redis publish failed: Connect call failed ('127.0.0.1', 6379)
   ```

   The sidecar's Redis subscription therefore never received a message, and every probe timed out after 15 seconds.

---

## Decision

We decouple the discover flow using **Redis Pub/Sub** as a one-shot message broker between the BAP Client and the MCP Sidecar.

### New flow

```
MCP Sidecar                   Redis               BAP Client         ONIX / BPP
───────────                   ─────               ──────────         ──────────
generate transaction_id
SUBSCRIBE beckn_results:{txn} ──────────────────►
POST /discover {txn_id} ─────────────────────────► discover_async()
                                                    POST /bap/caller/discover ─► ONIX
                                                                                 POST /bpp/discover
                                                    _send_local_on_discover
                                                    POST /on_discover ──────────►
                                                    PUBLISH beckn_results:{txn} ─► ◄─ message
◄─ message ◄─────────────────────────────────────
parse items
UNSUBSCRIBE (context manager)
```

### Implementation changes

| File | Change |
|---|---|
| `services/mcp-sidecar/bap_client.py` | Replaced synchronous HTTP-wait with: (1) generate UUID4 `transaction_id`, (2) subscribe to `beckn_results:{txn_id}` before firing the request, (3) run HTTP POST as `asyncio.create_task`, (4) `asyncio.wait_for(pubsub.listen(), timeout=15s)`, (5) parse `on_discover` callback payload from Redis message. |
| `services/mcp-sidecar/bap_client.py` | Added `_extract_items_from_callback` to parse the Beckn v2 `on_discover` payload shape (`message.catalogs[].resources[]`) instead of the old sync HTTP response shape (`catalog.items[]`). |
| `services/mcp-sidecar/bap_client.py` | Added `transaction_id` field to `_build_payload` return dict so BAP Client can embed the same ID into the Beckn context and ONIX routing preserves it end-to-end. |
| `services/beckn-bap-client/src/handler.py` | Added dedicated `POST /on_discover` route. Dual responsibility: publishes payload to `beckn_results:{txn_id}` on Redis, **and** feeds the existing `CallbackCollector` (backward compatibility with the orchestrator's synchronous discover flow). |
| `services/beckn-bap-client/src/handler.py` | Updated `_send_local_on_discover` to POST to `/on_discover` instead of `/bap/receiver/on_discover`, so local BPP callbacks flow through the Redis publish path. |
| `services/beckn-bap-client/src/handler.py` | Updated `discover` handler to `pop("transaction_id", None)` from the request body before `BecknIntent` parsing and pass it to `discover_async()`, ensuring ONIX embeds the sidecar's pre-generated ID into the Beckn context. |
| `config/generic-routing-BAPReceiver.yaml` | Split routing rules: `on_discover` now routes to `http://beckn-bap-client:8002` (ONIX appends `/on_discover` → the Redis-publishing handler). All other `on_*` callbacks continue to `/bap/receiver/{action}`. |
| `docker-compose.yml` | Added `REDIS_URL=redis://redis:6379` to `beckn-bap-client` environment. The container was defaulting to `redis://localhost:6379` (container loopback), causing every publish to fail silently. |
| `services/mcp-sidecar/requirements.txt` | Added `redis>=5.0.0`. |
| `services/beckn-bap-client/requirements.txt` | Added `redis>=5.0.0`. |

### Race-condition elimination

The subscription is established **before** the HTTP request is fired. This eliminates the subscribe/publish race: even if the ONIX adapter is extremely fast, the `SUBSCRIBE` command completes on the Redis server before the `PUBLISH` can arrive.

```python
# bap_client.py — correct ordering
await pubsub.subscribe(channel)          # Redis server-side subscription confirmed
http_task = asyncio.create_task(...)    # only now send the HTTP request
callback_payload = await asyncio.wait_for(
    _wait_for_redis_message(), timeout=REDIS_RESULT_TIMEOUT
)
```

### Backward compatibility

The `CallbackCollector` remains fully functional. The `/on_discover` handler calls `collector.handle_callback("on_discover", payload)` after every Redis publish, so the orchestrator's `discover_async()` still works correctly through the existing `asyncio.Queue`-based correlation mechanism.

---

## Consequences

### Positive

- **Deadlock eliminated.** The sidecar no longer holds an HTTP connection open across the Beckn async boundary.
- **Decoupled timeout domains.** The HTTP fire-and-forget (`mcp_bap_timeout = 3 s`) and the Redis wait (`REDIS_RESULT_TIMEOUT = 15 s`) are now independent. A slow Beckn network doesn't cancel the HTTP request prematurely.
- **Resilience.** If Redis is unavailable, the `on_discover` handler logs a warning and falls through to `CallbackCollector`; the sidecar times out cleanly after 15 seconds and returns `{"found": false}` — the "Never Throw" contract is preserved.
- **Observable.** The Redis channel name `beckn_results:{transaction_id}` carries the Beckn transaction ID, making pub/sub traffic directly correlatable with ONIX logs using `redis-cli subscribe`.

### Negative / trade-offs

- **Redis is now a hard runtime dependency.** Both `beckn-bap-client` and `mcp-sidecar` fail gracefully but degrade to "not found" if Redis is unavailable. The `docker-compose.yml` healthcheck on the `redis` service mitigates cold-start races.
- **Channels are ephemeral and single-consumer.** Redis Pub/Sub delivers messages only to currently-subscribed clients. If the sidecar crashes between `SUBSCRIBE` and `PUBLISH`, the message is lost. For the current probe pattern (fire-and-retry-on-miss), this is acceptable — the IntentParser's recovery flow retries with a broadened query.
- **No message persistence.** Unlike Redis Streams or a message queue, Pub/Sub does not buffer messages for late subscribers. The strict subscribe-before-publish ordering in the code must be maintained.
- **Adds per-request Redis connection overhead.** Each `probe_bap_network` call opens a Redis connection, subscribes, and closes. For the current low-frequency probe pattern (triggered only on pgvector cache miss), this is negligible.

### Explicit timeout handling required

Callers of `probe_bap_network` must handle the case where `REDIS_RESULT_TIMEOUT` elapses with no message. The function already returns `(False, [], elapsed_ms)` on timeout. The sidecar's `search_bpp_catalog` tool propagates this as `{"found": false, "items": [], "probe_latency_ms": <elapsed>}`.
