---
name: redis-pubsub-discovery
description: Async Beckn discovery via Redis Pub/Sub between MCP Sidecar and beckn-bap-client. Race-free subscribe-before-publish pattern, per-transaction channel naming, asyncio.wait_for timeouts. Auto-invoke when editing services/mcp-sidecar/, services/beckn-bap-client/src/handler.py, on_discover routing, or anything that publishes/subscribes on a beckn_results:* channel.
tools: Read, Grep, Glob, Edit, Bash
---

# Redis Pub/Sub for async Beckn discovery

Authoritative source: `docs/architecture/decisions/0001-use-redis-pubsub-for-async-beckn-responses.md`. Sequence diagram: `README.md` → "Architecture — Async Discovery Flow".

## Why this exists

Beckn v2.0.0 `POST /discover` returns only an ACK. The catalog arrives later as `POST /on_discover`. Blocking on the HTTP response caused deadlocks and timeouts in the MCP sidecar. We solved it by **decoupling** the MCP wait from the HTTP cycle via a one-shot Redis channel.

## Channel naming convention

`beckn_results:{transaction_id}` — `transaction_id` is a UUID4 generated in the **MCP sidecar** before the POST goes out. The same UUID is:

- inserted into the `POST /discover` body as `transaction_id`
- popped from the body by `services/beckn-bap-client/src/handler.py` and placed in the Beckn `context.transactionId`
- echoed back by the BPP in `on_discover.context.transactionId`
- used by the BAP client as the channel name when `PUBLISH`ing the catalog

The channel name is **directly correlatable with ONIX log field `transactionId`** — use this for debugging.

## The race-free pattern (DO NOT change the order)

```python
# services/mcp-sidecar/server.py (conceptual)
transaction_id = str(uuid.uuid4())
channel = f"beckn_results:{transaction_id}"

# 1. SUBSCRIBE FIRST
pubsub = redis.pubsub()
await pubsub.subscribe(channel)

# 2. THEN fire the HTTP POST as a non-blocking task
asyncio.create_task(
    bap_client.post("/discover", json={**body, "transaction_id": transaction_id}),
)

# 3. Wait on the channel with a hard ceiling
try:
    msg = await asyncio.wait_for(pubsub.listen_one(), timeout=15.0)
except asyncio.TimeoutError:
    return {"found": False, "items": [], "probe_latency_ms": 15000}
finally:
    await pubsub.unsubscribe(channel)
```

**Why subscribe BEFORE post**: Redis does NOT buffer messages for absent subscribers. If `PUBLISH` happens before `SUBSCRIBE`, the message is lost. Subscribing first guarantees the buffer is up by the time the BPP echoes back.

## The publish side

`services/beckn-bap-client/src/handler.py` `/on_discover` handler:

1. Extracts `transactionId` from the Beckn context.
2. `PUBLISH beckn_results:{transactionId} <payload>`.
3. **Also** calls `CallbackCollector.handle_callback(...)` for backward compatibility with the orchestrator's synchronous flow. Don't remove this until the orchestrator is fully migrated to Redis.

## Env vars (must be consistent across containers)

| Service | Var | Inside Docker | From host |
|---|---|---|---|
| `beckn-bap-client` | `REDIS_URL` | `redis://redis:6379` | n/a |
| `onix-bap`, `onix-bpp` | `REDIS_ADDR` | `redis:6379` | n/a |
| MCP sidecar (local) | `REDIS_URL` | n/a | `redis://localhost:6379` |
| MCP sidecar (local) | `REDIS_RESULT_TIMEOUT` | n/a | `15` (seconds) |
| MCP sidecar (local) | `MCP_BAP_TIMEOUT` | n/a | `3.0` (HTTP fire-and-forget) |

The healthcheck on the `redis` service (`docker-compose.yml` lines 103-107) gates `beckn-bap-client` and `onix-bap` (`condition: service_healthy`). Don't bypass it — the BAP client crashes on first publish if Redis isn't ready.

## What NOT to do

- **Don't replace Pub/Sub with Streams or BLPOP.** ADR-0001 evaluated both. Pub/Sub wins because the channel is single-use, the consumer always exists at publish time (we control both), and we don't need replay.
- **Don't reuse a `transaction_id`.** Channels are derived from it; a reused UUID would deliver one transaction's catalog to a stale subscriber.
- **Don't await the HTTP POST.** It's `asyncio.create_task(...)`. Awaiting it would re-introduce the deadlock the ADR was written to fix.
- **Don't drop the `CallbackCollector.handle_callback()` call** in `/on_discover`. The orchestrator (`services/orchestrator/src/workflow.py`) still uses the in-memory queue path.

## Debugging recipes

```bash
# Watch all Beckn result channels
docker exec -it redis redis-cli psubscribe 'beckn_results:*'

# Tail an ONIX request from start to finish (replace UUID)
docker logs onix-bap | grep '<UUID>'
docker logs beckn-bap-client | grep '<UUID>'

# Verify Redis is healthy
docker exec redis redis-cli ping        # → PONG
```

If `MCP Sidecar` returns `found=false` with `probe_latency_ms` close to 15000, you have a subscriber-but-no-publisher problem. Check `beckn-bap-client` logs for the on_discover handler.
