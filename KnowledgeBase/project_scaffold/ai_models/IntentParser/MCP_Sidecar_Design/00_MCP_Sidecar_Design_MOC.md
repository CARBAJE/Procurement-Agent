---
tags: [mcp, sidecar, architecture, beckn, design, moc]
created: 2026-04-28
updated: 2026-04-29
status: approved
cssclasses: [procurement-doc, ai-doc]
---

# MCP Sidecar Design — Map of Content

This MOC covers the design of the MCP Sidecar service. The sidecar is a lightweight, co-located service that bridges the IntentParser's Stage 3 validation logic with the live Beckn ONIX network via the BAP Client. All notes in this cluster are design-level documents: they describe intent, architecture decisions, contracts, and failure semantics — not working code. All open questions from the initial design phase have been resolved by the Principal Engineer (2026-04-29); this cluster is now marked `status: approved` and implementation may begin.

## Notes in this design cluster

- [[01_Sidecar_Architecture_and_Transport]] — Process isolation rationale, SSE transport choice, recommended tech stack, and deployment topology.
- [[02_search_bpp_catalog_Tool_Schema]] — Complete JSON Schema for the single MCP tool the sidecar exposes, response contracts, and validation rules.
- [[03_BAP_Client_and_ONIX_Integration]] — Internal execution flow, POST /discover payload shape, Mermaid sequence diagram, and response field mapping.
- [[04_Timeouts_and_Failure_Handling]] — 3-second probe TTL design, failure mode table, the "never throw" contract, and timeout implementation pattern.

## Design Decisions Summary

| Decision | Chosen Option | Rationale |
|---|---|---|
| Transport protocol | SSE over HTTP (port 3000) | Compatible with `aiohttp` streaming in async Python; HTTP-native and firewall-friendly; aligns with existing `mcp_client.py` implementation; supports multiple concurrent clients without subprocess lifecycle issues |
| SDK / runtime | Node.js 20 + TypeScript with `@modelcontextprotocol/sdk` | First-class `SSEServerTransport` support; strong typing reduces contract drift; fast startup; small footprint; Python `mcp` SDK is viable alternative if team prefers a single language |
| Tool name | `search_bpp_catalog` | Already hard-coded in `IntentParser/mcp_client.py`; changing it would require a coordinated dual-service change |
| Probe TTL (internal) | 3 seconds (enforced inside the sidecar on its BAP Client call) | Keeps the sidecar response well within the IntentParser's outer `MCP_PROBE_TIMEOUT=8s` safety net; prevents a slow ONIX network from stalling the procurement pipeline |
| Failure shape | Always return `{"found": false, "items": [], "probe_latency_ms": <elapsed>}` — never a JSON-RPC error object | `IntentParser/mcp_client.py` parses the `message` SSE event with `.get("found")`; an unexpected error shape would cause a `KeyError` and crash Stage 3 |

## Resolved Architectural Decisions

The following decisions were finalized by the Principal Engineer on 2026-04-29. They supersede the open questions from the initial design phase and must be treated as binding implementation constraints.

| # | Topic | Decision | Rationale |
|---|---|---|---|
| 1 | **Authentication (Sidecar → BAP Client)** | Sidecar MUST pass a secure token (API Key or JWT) in the `Authorization: Bearer <TOKEN>` HTTP header on every POST /discover call. The token is injected at runtime via the `BAP_API_KEY` environment variable, sourced from a Secrets Manager. No hardcoded secrets in source code or Docker images. | Eliminates unauthenticated internal service calls; secrets manager injection allows rotation without a code deployment; `Authorization` header is the HTTP-standard location that the BAP Client can validate without parsing the request body. |
| 2 | **Result Ranking (multiple ONIX matches)** | The sidecar MUST rank returned BPP catalog items strictly by semantic similarity to `item_name` before populating `items[]`. Items whose names are semantically irrelevant (similarity below a configurable `RANKING_MIN_SIMILARITY` threshold) must be filtered out before the response is returned. Business-logic ranking (price, rating, delivery SLA) is explicitly out of scope for the sidecar — that belongs to the downstream Comparison Engine. | Avoids returning noisy BPP results that would pollute the IntentParser's cache write (Path B) and confuse downstream scoring. Keeps the sidecar's ranking responsibility narrow: relevance only, not value judgement. |
| 3 | **Sidecar Caching** | **REJECTED.** The MCP Sidecar must be 100% stateless. It must not maintain any in-process or external cache of `search_bpp_catalog` calls. Semantic caching is exclusively owned by IntentParser's Stage 3 `pgvector` database. | Maintaining two caches (pgvector + sidecar) creates a "Two Sources of Truth" anti-pattern: cache invalidation logic would need to be duplicated, and inconsistencies between the two caches would produce non-deterministic Stage 3 validation results. Statelessness also simplifies horizontal scaling of the sidecar — any instance can handle any request without session affinity. |
| 4 | **SSE Reconnect and Retry Policy** | `IntentParser/mcp_client.py` MUST implement Exponential Backoff for dropped or failed SSE connections. The retry policy applies to the `GET /sse` handshake; it does NOT retry a timed-out tool call (that failure is surfaced immediately as `found: false`). Initial retry delay: 500ms. Backoff multiplier: 2×. Maximum delay: 8s. Maximum attempts: 3. See [[04_Timeouts_and_Failure_Handling]] for the full retry specification. | Without a retry policy, a transient sidecar restart (e.g., rolling pod update) causes every concurrent Stage 3 validation to fail immediately. Exponential backoff absorbs brief availability gaps without overwhelming the sidecar on restart. |
| 5 | **Multi-Domain / Multi-Version Beckn Support** | The `domain` and `version` fields in the POST /discover payload MUST NOT be hardcoded. They are added as required parameters to the `search_bpp_catalog` tool schema (see [[02_search_bpp_catalog_Tool_Schema]]) and passed as arguments by the IntentParser. The sidecar maps them directly into the Beckn `context` block. Default values (`"procurement"`, `"1.1.0"`) are set in the IntentParser's `config.py`, not in the sidecar. | Parameterising at the tool schema level means the sidecar requires no code change to support a new domain — only the IntentParser's configuration changes. Decouples domain semantics from transport semantics. |
