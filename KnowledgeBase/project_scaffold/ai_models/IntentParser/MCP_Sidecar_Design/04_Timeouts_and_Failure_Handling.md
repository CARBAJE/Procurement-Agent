---
tags: [reliability, timeouts, error-handling, mcp, sidecar, beckn]
created: 2026-04-28
updated: 2026-04-29
status: approved
aliases: [MCP Probe TTL, Failure Modes]
cssclasses: [procurement-doc, ai-doc]
---

# Timeouts and Failure Handling

This note documents the timeout architecture and all failure modes for the MCP Sidecar's `search_bpp_catalog` tool. For the full design index see [[00_MCP_Sidecar_Design_MOC]].

## The 3-Second Probe TTL

The MCP Sidecar enforces a hard 3-second timeout on its own internal HTTP call to the BAP Client (`http://beckn-bap-client:8002/discover`). This is the "probe TTL" — the maximum time the sidecar will wait for the ONIX network to respond before giving up and returning `{"found": false}`.

This timeout is deliberately distinct from, and much shorter than, the `MCP_PROBE_TIMEOUT=8s` environment variable configured on the IntentParser side. The two timeouts serve different purposes and must not be conflated:

- **3-second sidecar TTL** — enforced by the sidecar, measured from the moment it dispatches the POST /discover request. This governs how long the sidecar is willing to hold an outbound connection to the BAP Client open. It is the primary latency budget for the live ONIX probe.
- **8-second IntentParser outer timeout** — enforced by `mcp_client.py` on the entire SSE session lifecycle (SSE connection + tool call + SSE message receipt). This is a safety net for pathological cases: if the sidecar itself hangs (e.g., due to a deadlock, OOM, or a blocking operation that bypasses the probe TTL), the IntentParser will still eventually time out and surface a `ValidationResult` without a live BPP match.

The headroom between 3s and 8s (5 seconds) accounts for SSE protocol overhead (the `GET /sse` handshake and endpoint event), the sidecar's input validation and payload construction time, and any response serialisation delay. Under normal operating conditions, the round-trip overhead outside the BAP call is under 50ms. The 5-second buffer is conservative by design.

**Design principle:** Never let a slow ONIX network hold up the procurement pipeline. The IntentParser's Stage 3 validation has a bounded latency budget. A live ONIX probe is a best-effort enhancement — if the network is slow or the BAP Client is under load, the system should degrade gracefully (returning `found: false` and falling back to heuristic validation) rather than stalling the entire request.

## Failure Mode Table

| Failure Scenario | MCP Sidecar Behaviour | IntentParser Receives |
|---|---|---|
| BAP Client unreachable (connection refused) | Catch connection error immediately; record elapsed time (typically < 50ms); return tool result | `{"found": false, "items": [], "probe_latency_ms": <elapsed>}` — Stage 3 proceeds with heuristic fallback |
| BAP Client timeout (> 3 s) | `Promise.race` / `asyncio.wait_for` fires; cancel the pending request; record elapsed time (~3000ms); return tool result | `{"found": false, "items": [], "probe_latency_ms": 3000}` — Stage 3 proceeds with heuristic fallback |
| ONIX returns zero catalog matches | BAP Client returns HTTP 200 with empty items list; sidecar parses response; `items.length === 0` → set `found: false`; return tool result | `{"found": false, "items": [], "probe_latency_ms": <elapsed>}` — cache miss confirmed, no live BPP available |
| ONIX returns malformed / unparseable JSON | BAP Client returns HTTP 200 but body fails JSON parse or schema extraction; sidecar catches parse error; return tool result with `found: false` | `{"found": false, "items": [], "probe_latency_ms": <elapsed>}` — treated identically to empty result; no exception propagated |
| `item_name` argument is empty string (input validation failure) | Sidecar detects validation failure before constructing the BAP payload; returns tool result immediately without any outbound call | `{"found": false, "items": [], "probe_latency_ms": 0}` — IntentParser treats as a non-fatal Stage 3 miss; logs the malformed intent |
| MCP Sidecar itself crashes mid-request | SSE stream closes unexpectedly; `mcp_client.py` receives an incomplete or EOF response; `aiohttp` raises a connection error; the IntentParser's outer 8s timeout catches it | `IntentParser` catches the `aiohttp` exception in `mcp_client.py`, logs the sidecar crash, and returns `ValidationResult(found=False)` — the pipeline continues without a live BPP match |

## The "Never Throw" Contract

The `search_bpp_catalog` tool must **never** cause the sidecar to return a JSON-RPC `error` object in the MCP response. The distinction is critical:

- A **JSON-RPC error response** looks like: `{"jsonrpc":"2.0","id":1,"error":{"code":-32000,"message":"BAP timeout"}}`
- A **JSON-RPC success response with a failure result** looks like: `{"jsonrpc":"2.0","id":1,"result":{"content":[{"type":"text","text":"{\"found\":false,\"items\":[],\"probe_latency_ms\":3000}"}]}}`

Only the second form is acceptable. The reason is structural: `IntentParser/mcp_client.py` parses the `message` SSE event and directly calls `.get("found")` on the parsed JSON. It does not check for a top-level `"error"` key before attempting to extract `"found"`. If the sidecar ever returns a JSON-RPC error, `mcp_client.py` will parse a dict without a `"found"` key, and `.get("found")` will return `None`, causing downstream logic that checks `if result["found"]` to raise a `KeyError` — crashing Stage 3 for the affected request.

The "never throw" contract means: the sidecar's tool handler function must wrap its entire body in a try/catch (or try/except). Any exception — network error, parse error, unexpected runtime error, invalid argument — must be caught and converted into a `{"found": false, "items": [], "probe_latency_ms": <elapsed>}` tool result. The exception should be logged internally for observability, but it must not propagate to the MCP protocol layer.

This is a deliberate design choice that prioritises pipeline continuity over strict error visibility. Failures are surfaced through logs and `probe_latency_ms` monitoring, not through protocol-level errors.

## Timeout Implementation Note

The 3-second probe TTL must be implemented as a racing pattern: the HTTP fetch to the BAP Client races against a 3-second timer. Whichever resolves (or rejects) first wins.

```pseudocode
function callBAPWithTimeout(payload, timeoutMs = 3000):
    startTime = now()

    fetchPromise = httpClient.post(BAP_DISCOVER_URL, body=payload)
    timeoutPromise = sleep(timeoutMs).then(() => raise TimeoutError("probe TTL exceeded"))

    try:
        response = await race([fetchPromise, timeoutPromise])
        items = parseONIXResponse(response)
        return {
            found: items.length > 0,
            items: items,
            probe_latency_ms: now() - startTime
        }
    catch TimeoutError:
        return { found: false, items: [], probe_latency_ms: now() - startTime }
    catch NetworkError as e:
        log.warn("BAP Client unreachable", error=e)
        return { found: false, items: [], probe_latency_ms: now() - startTime }
    catch ParseError as e:
        log.warn("ONIX response unparseable", error=e)
        return { found: false, items: [], probe_latency_ms: now() - startTime }
```

**Node.js TypeScript implementation note:** Use `Promise.race([fetchPromise, timeoutPromise])` where `timeoutPromise` is created with `new Promise((_, reject) => setTimeout(() => reject(new Error('probe TTL')), 3000))`. Cancel the fetch using `AbortController` when the timeout fires to avoid a dangling connection holding BAP Client resources.

**Python SDK implementation note:** Use `asyncio.wait_for(fetch_coroutine(), timeout=3.0)` which raises `asyncio.TimeoutError` on expiry. Wrap in try/except to convert to the failure return shape.

In both cases, the `timeoutMs` value must be sourced from a `MCP_BAP_TIMEOUT` environment variable (defaulting to 3000) rather than hardcoded, to allow operational tuning without a code change.

## SSE Reconnect and Exponential Backoff (Python Client)

The `IntentParser/mcp_client.py` opens a fresh SSE connection per `search_bpp_catalog` call. A transient sidecar restart (rolling pod update, OOM kill, process crash) will cause the `GET /sse` handshake to fail with a connection-refused error. Without a retry policy, every concurrent Stage 3 validation request would fail immediately for the duration of the restart window.

The following **Exponential Backoff** policy is the resolved standard for `mcp_client.py`. It applies **only to the SSE handshake** (`GET /sse`). It does NOT retry a timed-out or failed tool call — those failures are surfaced immediately as `{"found": false}` to preserve the 3-second probe TTL.

**Policy parameters:**

| Parameter | Value | Notes |
|---|---|---|
| Initial retry delay | 500 ms | First retry fires 500ms after the first failure |
| Backoff multiplier | 2× | Each subsequent delay doubles |
| Maximum delay cap | 8 s | Delay is capped to prevent excessive wait on sustained outages |
| Maximum attempts | 3 | After 3 failed handshakes, give up and return `ValidationResult(found=False)` |
| Jitter | ±10% of computed delay | Prevents thundering-herd reconnects when multiple workers restart simultaneously |

**Delay sequence (illustrative, without jitter):** 500ms → 1000ms → 2000ms. Total maximum wait before giving up: ~3.5 seconds — well within the IntentParser's outer `MCP_PROBE_TIMEOUT=8s` safety net.

**What is retried vs. what is not:**

- ✅ **Retried:** `GET /sse` connection refused or connection reset (transient sidecar unavailability).
- ✅ **Retried:** `GET /sse` returns HTTP 5xx (sidecar is up but not yet ready).
- ❌ **Not retried:** A successfully opened SSE session that then produces a `message` event with `{"found": false}` — that is a valid tool result, not a transport error.
- ❌ **Not retried:** The outer `MCP_PROBE_TIMEOUT=8s` fires — if the entire SSE lifecycle (including all retry delays) exceeds 8 seconds, `mcp_client.py` raises a timeout exception and Stage 3 returns `ValidationResult(found=False)`.

**Pseudocode for the retry loop:**

```pseudocode
function connect_with_backoff(sse_url, max_attempts=3, base_delay_ms=500, max_delay_ms=8000):
    delay_ms = base_delay_ms

    for attempt in range(1, max_attempts + 1):
        try:
            sse_response = await aiohttp_session.get(sse_url, timeout=MCP_PROBE_TIMEOUT)
            endpoint_url = await read_endpoint_event(sse_response)
            return sse_response, endpoint_url   # success — proceed with tool call
        catch (ConnectionRefusedError, ServerError) as e:
            if attempt == max_attempts:
                log.warn("MCP SSE handshake failed after %d attempts: %s", attempt, e)
                return None, None   # caller returns ValidationResult(found=False)
            jitter = delay_ms * random.uniform(-0.1, 0.1)
            actual_delay = min(delay_ms + jitter, max_delay_ms)
            log.debug("MCP SSE handshake attempt %d failed; retrying in %.0fms", attempt, actual_delay)
            await asyncio.sleep(actual_delay / 1000)
            delay_ms = min(delay_ms * 2, max_delay_ms)
```

The `INTENT_PARSER_TEST_MODE=live` test suite should NOT exercise the backoff loop — retries would push `test_3_mcp_success_returns_mcp_validated` past its expected latency budget. The backoff is an operational resilience mechanism for production, not a behaviour that needs live-test coverage.

## Related Notes

- [[01_Sidecar_Architecture_and_Transport]] — process isolation and deployment context that determine how sidecar crashes are observed by the IntentParser.
- [[02_search_bpp_catalog_Tool_Schema]] — the validation rules for input arguments that feed into the input-validation failure scenario above.
- [[03_BAP_Client_and_ONIX_Integration]] — the full execution flow inside the sidecar where all of these failure modes can occur.
