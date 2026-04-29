---
tags: [architecture, mcp, sidecar, transport, sse, beckn]
created: 2026-04-28
updated: 2026-04-29
status: approved
aliases: [MCP Transport Design]
cssclasses: [procurement-doc, ai-doc]
---

# Sidecar Architecture and Transport

This note documents the architectural rationale and transport layer design for the MCP Sidecar service. For the full design index see [[00_MCP_Sidecar_Design_MOC]].

## Why a Sidecar?

The MCP Sidecar is designed as a separate process — not a module inside IntentParser — for several compounding reasons.

**Process isolation.** A crash, memory leak, or unhandled exception in the sidecar cannot corrupt the IntentParser process. The IntentParser handles high-throughput intent classification; the sidecar handles slower, network-bound ONIX probes. Keeping them isolated means one failure domain cannot cascade into the other.

**Independent scaling.** If ONIX probe volume grows (e.g., because cache hit rates drop), the sidecar can be scaled horizontally without touching the IntentParser deployment. Conversely, if the IntentParser needs more replicas for classification throughput, those replicas can share a single sidecar instance.

**Language decoupling.** IntentParser is a Python FastAPI service. The MCP Sidecar can be implemented in Node.js / TypeScript, which has first-class support for the official `@modelcontextprotocol/sdk`. There is no shared memory, no shared GIL, and no import-time coupling between the two services. Language choice for the sidecar can be made on purely technical grounds (SDK quality, team familiarity, startup time) without affecting the IntentParser codebase.

**Fault containment.** The sidecar is the only component that holds an open HTTP connection to `beckn-bap-client:8002`. If the BAP Client becomes unavailable, the sidecar absorbs that failure and returns `{"found": false}` to the IntentParser. The IntentParser never sees a raw connection error from the BAP layer.

**No shared memory.** Because the two services communicate only over HTTP/SSE, there is no risk of shared-state bugs (race conditions, pointer aliasing, accidental mutation). The contract is the JSON wire format documented in [[02_search_bpp_catalog_Tool_Schema]].

## Transport: SSE over HTTP

The MCP protocol supports two transport mechanisms: `stdio` (subprocess-based) and SSE (HTTP-based). The sidecar uses SSE. The reasons are definitive.

**Why `stdio` is rejected.**

The IntentParser is an `asyncio`-based FastAPI service. Its MCP client logic (`mcp_client.py`) uses `aiohttp` for all HTTP I/O — it runs inside the same `asyncio` event loop that handles incoming FastAPI requests. Spawning a subprocess (as `stdio` transport requires) from inside an `aiohttp`/`asyncio` context introduces event loop conflicts: `asyncio.create_subprocess_exec` competes with the existing event loop, and process lifecycle management (startup, health check, graceful shutdown) becomes the IntentParser's responsibility. If the sidecar subprocess crashes, the IntentParser must detect and restart it. This couples two services at the OS process level, defeating the purpose of a sidecar.

Furthermore, `stdio` transport requires the MCP server to be a child process of the client. This is incompatible with any deployment model (Docker Compose, Kubernetes) where the two services are separate containers.

**Why SSE is chosen.**

SSE is HTTP-native. The IntentParser's `mcp_client.py` already implements the full SSE protocol:
1. `GET http://localhost:3000/sse` — opens the SSE stream and reads the `endpoint` event to obtain the POST URL.
2. `POST <endpoint>` with a JSON-RPC 2.0 body.
3. Reads the `message` event from the SSE stream for the result.

This is a clean, stateless-per-request pattern. Each Stage 3 validation call opens a fresh SSE connection, sends one tool call, and closes. `aiohttp` handles SSE streaming natively via `async for line in response.content`. SSE is firewall-friendly (it is plain HTTP/1.1 with chunked transfer encoding), works through load balancers, and requires no special infrastructure. Multiple concurrent IntentParser workers can connect to the same sidecar instance simultaneously without any session affinity requirement.

## Recommended Tech Stack

**Primary recommendation: Node.js 20 + TypeScript + `@modelcontextprotocol/sdk`.**

The official MCP SDK (`@modelcontextprotocol/sdk`) provides `SSEServerTransport` as a first-class primitive. The server setup is minimal: create an `McpServer`, register the `search_bpp_catalog` tool with its JSON Schema, attach an `SSEServerTransport` to an Express or `http.Server` instance, and serve. TypeScript enforces the tool input and output shapes at compile time, reducing contract drift between the sidecar and the IntentParser. Node.js 20 has a stable, built-in `fetch` API suitable for the BAP Client HTTP call. Startup time is under one second. The container image (node:20-alpine + compiled JS) is well under 200 MB.

**Alternative: Python `mcp` SDK.**

If the team strongly prefers a single-language stack, the Python `mcp` library supports SSE transport via Starlette/Uvicorn. The trade-off is heavier import time (Python interpreter startup + all transitive dependencies), and the SSE server implementation in the Python SDK is less battle-tested than the Node.js version as of April 2026. Python is also less natural for a purely I/O-bound proxy service with no ML workloads — the GIL offers no benefit here.

The choice between the two stacks should be documented as a resolved decision in [[00_MCP_Sidecar_Design_MOC]] before implementation begins.

## Deployment Topology

The sidecar runs as a co-located container or process on the same host or Kubernetes pod as the IntentParser. "Co-located" means the network hop from IntentParser to sidecar is loopback (127.0.0.1) or pod-internal, with sub-millisecond latency. The sidecar in turn calls the BAP Client over the internal service network.

```
┌──────────────────────────────────────────────────────────────────┐
│  Pod / VM                                                        │
│                                                                  │
│  ┌─────────────────┐    SSE :3000                               │
│  │  IntentParser   │ ──────────────────► MCP Sidecar            │
│  │   (Python 3.11) │                      (Node.js 20)          │
│  │   FastAPI :8001 │                           │                │
│  │                 │    env: MCP_SSE_URL        │ HTTP :8002     │
│  └─────────────────┘    env: MCP_PROBE_TIMEOUT  │ Authorization: │
│                                                 │  Bearer        │
│                         env: BAP_CLIENT_URL     │ <BAP_API_KEY>  │
│                         env: BAP_API_KEY ───────▼                │
│                                            BAP Client            │
│                                           (Python :8002)         │
│                                                │                 │
└────────────────────────────────────────────────│─────────────────┘
                                                 │ POST /discover
                                                 ▼
                                          ONIX Network
                                     (external Beckn P2P)
```

The IntentParser's `MCP_SSE_URL` environment variable defaults to `http://localhost:3000/sse`. In a Docker Compose setup, this would be `http://mcp-sidecar:3000/sse` using the service name. The sidecar's `BAP_CLIENT_URL` environment variable defaults to `http://beckn-bap-client:8002`. The sidecar's `BAP_API_KEY` environment variable must be injected at runtime from a Secrets Manager — it is passed in the `Authorization: Bearer` header on every POST /discover call and must never appear in source code or Docker images. All three values must be configurable via environment variables — no hardcoded hostnames or credentials in either service's source code.

## Stateless Design (Sidecar Caching Rejected)

The MCP Sidecar is explicitly and permanently stateless. It holds no in-process cache, no database connection, and no session state between requests.

**Why sidecar caching was rejected.**

A short-TTL in-process cache inside the sidecar would reduce redundant ONIX probes for repeated queries within a burst window. However, it would introduce a second source of truth for catalog data — alongside the `pgvector` semantic cache that IntentParser Stage 3 already owns. This "Two Sources of Truth" anti-pattern creates several failure modes:

- **Stale data divergence.** A BPP catalog item that is invalidated in the `pgvector` cache (e.g., because it went out of stock) might still be served as a hit from the sidecar cache, causing Stage 3 to believe a live BPP match exists when it does not.
- **Duplicated invalidation logic.** Any cache eviction or TTL policy would need to be reimplemented and kept in sync across two services. When the IntentParser team updates the pgvector TTL, they would also need to coordinate a matching change in the sidecar's cache — a cross-team, cross-language coordination cost.
- **Stateful sidecar scaling.** A cached sidecar requires session affinity or a shared external cache (Redis) to serve consistent results across multiple sidecar replicas. This negates the operational simplicity advantage of the sidecar pattern.

**The decision:** Semantic caching is exclusively owned by IntentParser Stage 3 via the `bpp_catalog_semantic_cache` pgvector table. The sidecar is a pure pass-through proxy — every `search_bpp_catalog` call results in a live BAP Client request (subject to the 3-second TTL). If a successful MCP result is returned, IntentParser writes it to `bpp_catalog_semantic_cache` via the Path B write (`MCPResultAdapter.write_path_b_row`), warming the cache for future queries. The sidecar's job ends when it returns the `{found, items, probe_latency_ms}` response.

## Related Notes

- [[02_search_bpp_catalog_Tool_Schema]] — the single tool the sidecar registers, its JSON Schema, and response contract.
- [[03_BAP_Client_and_ONIX_Integration]] — how the sidecar constructs and sends the POST /discover request to the BAP Client.
- [[04_Timeouts_and_Failure_Handling]] — the 3-second probe TTL, failure modes, and the "never throw" contract.
