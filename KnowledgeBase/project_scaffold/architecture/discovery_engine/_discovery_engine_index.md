---
tags: [moc, discovery, multi-network, async, distributed-systems, beckn, phase-3]
created: 2026-06-01
updated: 2026-06-01
status: design
cssclasses: [procurement-doc, architecture-doc]
related:
  - "[[01_multi_network_fan_out]]"
  - "[[02_graceful_degradation]]"
  - "[[03_catalog_deduplication]]"
  - "[[_negotiation_engine_index]]"
  - "[[beckn_bap_client]]"
  - "[[catalog_normalizer]]"
  - "[[comparison_scoring_engine]]"
  - "[[microservices_architecture]]"
  - "[[phase3_advanced_intelligence_enterprise_features]]"
---

# Discovery Engine — Multi-Network Search Cluster (MOC)

This Map of Content is the canonical entry point for the **Multi-Network Search** architecture cluster. The engine fans a single `BecknIntent` out to two or more independent Beckn networks in parallel, enforces per-network timeouts plus circuit breakers, and aggregates returned catalogs into a single deduplicated result set. It is the *Multi-Network Search* deliverable from [[phase3_advanced_intelligence_enterprise_features|Phase 3, Weeks 9–12]] and runs upstream of the [[comparison_scoring_engine]] and [[_negotiation_engine_index|Negotiation Engine cluster]].

> [!architecture] Role in the System
> The Discovery Engine sits **upstream** of every downstream procurement decision. The [[nl_intent_parser]] parses natural language into a `BecknIntent`; this engine fans that intent out to N Beckn networks (default two: `network_a`, `network_b`) using [[01_multi_network_fan_out|`asyncio.gather`]] with [[02_graceful_degradation|per-network timeouts and a circuit breaker]]; the [[03_catalog_deduplication|aggregator]] normalises and merges the returned catalogs; downstream, the [[comparison_scoring_engine]] ranks the aggregated items; the orchestrator forwards the ranked list into the Negotiation Engine via the trigger contract documented in [[_negotiation_engine_index]]. The engine **never fails the whole search** on a single network outage — degraded responses with structured `failed_networks` lists are the contract.

## Notes in this design cluster

- [[01_multi_network_fan_out]] — **Coordinator / fan-out engine.** `asyncio.gather` with `return_exceptions=True` for defence-in-depth, per-network `asyncio.wait_for`, payload cloning by value, ordering-stable result coercion. Owns the *concurrency model*.
- [[02_graceful_degradation]] — **Resilience layer.** Three-state `CircuitBreaker` (CLOSED / OPEN / HALF_OPEN) with async-locked transitions, exhaustive aiohttp exception translation, `NetworkStatus` enum taxonomy, fail-open Kafka audit logging. Owns the *failure model*.
- [[03_catalog_deduplication]] — **Aggregator / fan-in synthesis.** Two-stage match: primary signature on normalised `(tax_id, name, currency)`, geographic refinement via Haversine when tax-ids are missing. Pure function over the per-network result list. Owns the *result merge contract*.

## Microservice boundaries

| Direction | Channel | Counterparty | Payload |
|---|---|---|---|
| **In (trigger)** | HTTP `POST /search/multi-network` | [[nl_intent_parser]] → orchestrator | `IntentPayload {item_name, quantity?, location_coordinates?, ...}` |
| **Out (network calls)** | HTTP `POST /search` to each gateway | Beckn networks (gateway-of-gateways) | Beckn `/search` request body |
| **Out (response)** | HTTP `200 OK` (always) | orchestrator | `MultiSearchResult {items, responded_networks, failed_networks, degraded}` |
| **Out (audit)** | structured logger (Phase-4 → [[event_streaming_kafka|Kafka]]) | [[observability_stack]] | per-network outcome events |

## No-go boundaries

The Discovery Engine **must not**:

- Call `/select`, `/init`, `/confirm`, or `/status` — those are owned by [[beckn_bap_client]] and only ever reached after [[comparison_scoring_engine]] picks a candidate and the [[_negotiation_engine_index|Negotiation Engine]] finalises it.
- Normalise individual catalog payloads beyond the lightweight `_parse_beckn_catalog` parser — full normalisation is owned by [[catalog_normalizer]].
- Apply per-supplier policy filtering — that's a downstream concern handled by [[03_hard_guardrails_policy]] inside the Negotiation Engine.
- Re-issue requests on its own — retry decisions are owned by the orchestrator; the engine only enforces *one* shot per network per call, then circuit-breaks.
- Block on the slowest network — wall-clock is bounded by `max(gateway.timeout_s)` per [[01_multi_network_fan_out|concurrency model]].

## Design decisions summary

| # | Decision | Rationale | Owning note |
|---|---|---|---|
| D1 | **`asyncio.gather` over `asyncio.as_completed`** | Simpler bounded fan-in; per-network timeouts inside `wait_for` give us the early-termination property without iterator state | [[01_multi_network_fan_out]] |
| D2 | **`return_exceptions=True` on gather** | Defence-in-depth — the resilience layer contractually never raises, but a future bug must not crash the search transaction | [[01_multi_network_fan_out]] |
| D3 | **Per-network timeout via `asyncio.wait_for` inside resilience** | Keeps the coordinator HTTP-agnostic; one slow network self-terminates without dragging the fan-out's wall-clock | [[02_graceful_degradation]] |
| D4 | **Three-state circuit breaker (CLOSED/OPEN/HALF_OPEN)** | Classical pattern; HALF_OPEN probe avoids thundering-herd on recovery | [[02_graceful_degradation]] |
| D5 | **Exception → typed `NetworkStatus` translation** | Structured failures parse uniformly downstream; orchestrator branches on `status` enum, not error string | [[02_graceful_degradation]] |
| D6 | **Always HTTP 200, even when every network fails** | Callers branch on `degraded` + `len(items)`; status-code overloading would force ad-hoc parsing in every consumer | [[01_multi_network_fan_out]] |
| D7 | **Two-stage dedup: tax-id signature + geographic proximity** | Tax-id is the confident match; Haversine handles the cold-supplier case where tax-id is missing on one network | [[03_catalog_deduplication]] |
| D8 | **Canonical item chosen by `(price, -qty, delivery)`** | Buyer wins on price; ties broken by richest record then fastest delivery | [[03_catalog_deduplication]] |
| D9 | **Aggregator is a pure function** | No I/O, no shared state → trivially testable, safe for arbitrary concurrency | [[03_catalog_deduplication]] |
| D10 | **`asyncio.CancelledError` is never swallowed** | Re-raised after recording the failure on the breaker — honours the task-cancellation contract | [[02_graceful_degradation]] |

## Phase 3 acceptance trace

| [[phase3_advanced_intelligence_enterprise_features\|Phase 3]] deliverable | Owning sibling note |
|---|---|
| Multi-network search resilient to individual network failures | [[01_multi_network_fan_out]] + [[02_graceful_degradation]] |
| Concurrent queries to 2+ Beckn networks | [[01_multi_network_fan_out]] |
| Graceful degradation when one network is down | [[02_graceful_degradation]] |
| Single unified catalog with intelligent deduplication | [[03_catalog_deduplication]] |
| `< 100ms` retrieval latency on cached path (post-Phase-4 integration) | All three (load-balanced across the cluster) |

## Open questions

The following items are *explicitly deferred* — they are not blocking the Phase 3 design but must be answered before GA hardening:

1. **Embedding-based dedup** — current dedup is structural (`tax_id` + name normalisation + GPS). A future step may add semantic dedup via [[embedding_models|sentence-transformer]] cosine similarity for cases where catalogs differ in formal item names but represent the same SKU. Out of scope for Phase 3.
2. **Per-network rate limiting** — circuit breakers handle hard failures, but soft throttling (e.g. `429 Too Many Requests`) needs explicit backoff. Phase-4 work, likely via `aiolimiter`.
3. **Cross-network identity reconciliation** — if `bpp_acme` on Network A is the same legal entity as `bpp_acme_v2` on Network B but they advertise different tax IDs, dedup misses. Resolution requires the trust-graph layer (Phase 4+).
4. **Result streaming via Server-Sent Events** — the current endpoint waits for all networks (or their timeouts) before returning. A streaming variant could surface fast-network items immediately and trickle the slow ones in. Trade-off: client-side complexity vs. perceived latency.
5. **Per-request gateway override** — the API currently uses statically configured gateways. Allowing the caller to specify a subset is straightforward but raises authorisation questions (should every client be able to query every network?).

## References

- Code: `services/discovery_engine/src/{coordinator,resilience,aggregator}.py`
- Test suite: `services/discovery_engine/tests/test_multi_search.py` (34 cases, ~8 s)
- `docs/architecture/decisions/0001-use-redis-pubsub-for-async-beckn-responses.md` — ADR-0001 (asynchrony posture this engine inherits)
- `CLAUDE.md` — repo conventions: async-first, no `time.sleep`, BAP-client-only Beckn perimeter
- [[microservices_architecture]] — service map showing this engine's position in the procurement pipeline
- [[_negotiation_engine_index]] — sibling cluster that consumes this engine's output through the orchestrator
