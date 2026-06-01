---
tags: [moc, negotiation, architecture, beckn, langgraph, phase-3]
created: 2026-05-19
updated: 2026-05-19
status: design
cssclasses: [procurement-doc, architecture-doc]
related:
  - "[[negotiation_engine]]"
  - "[[negotiation_strategy_model]]"
  - "[[01_langgraph_state_machine]]"
  - "[[02_decision_intelligence_rl]]"
  - "[[03_hard_guardrails_policy]]"
  - "[[04_resilience_and_mlops]]"
  - "[[phase3_advanced_intelligence_enterprise_features]]"
---

# Negotiation Engine — Design Cluster (MOC)

This Map of Content is the canonical entry point for the **Negotiation Engine architecture design** cluster. It is *theoretical and pre-implementation*: it refines and replaces the prior monolithic design document, decomposing it into four atomic sibling notes that can be reviewed, versioned, and challenged independently. For high-level system context refer to the parent component note [[negotiation_engine]] and to the AI-model node [[negotiation_strategy_model]]; for milestone context see [[phase3_advanced_intelligence_enterprise_features]].

The cluster assumes familiarity with the platform's existing async-first conventions (see `CLAUDE.md`), the Beckn v2.0.0 callback model, and the Redis Pub/Sub broker introduced in ADR-0001.

> [!architecture] Role in the System
> The Negotiation Engine is a dedicated microservice positioned between [[comparison_scoring_engine]] (upstream — emits a ranked candidate list) and [[beckn_bap_client]] (downstream — the only sanctioned path to `onix-bap`). It owns the Beckn `/select` round-trip: it transmits counter-offers, consumes asynchronous `/on_select` callbacks via Redis Pub/Sub on the per-transaction channel `beckn_results:{transaction_id}` (per ADR-0001), and persists durable state via a LangGraph checkpointer. It never touches a BPP directly, never re-parses natural language ([[nl_intent_parser]] is upstream-only), and never reads from `comparative_scoring.*` SQL tables — all candidate ingestion happens via the orchestrator-emitted Pub/Sub trigger. Terminal outcomes are written to [[audit_trail_system]] through [[event_streaming_kafka|Kafka]] and to [[agent_memory_learning]] via [[vector_db_qdrant_pinecone|Qdrant]] for cross-transaction recall.

## Notes in this design cluster

- [[01_langgraph_state_machine]] — LangGraph StateGraph design, `TypedDict` schema with explicit reducers, async interrupt/resume mechanics, HITL escalation, bounded cyclical reasoning. Owns the topology.
- [[02_decision_intelligence_rl]] — Phase 1 rule-based per-category strategies (deterministic, auditable) and the Phase 2 evolution to a Contextual Bandit backed by a [[vector_db_qdrant_pinecone|Qdrant]] negotiation memory. Owns the *policy* of `compute_counter_offer`.
- [[03_hard_guardrails_policy]] — Architectural isolation of the 20% discount cap and the policy enforcement layer. Deterministic, [[llm_providers|LLM]]-independent, audit-replayable. Owns the *safety floor* enforced inside `policy_guardrail_check`.
- [[04_resilience_and_mlops]] — Service boundaries, async Beckn callback handling, dual-write durability (Pub/Sub + Redis Streams), [[event_streaming_kafka|Kafka]] audit trail, Kubernetes deployment shape, and observability via the [[observability_stack]]. Owns *operational survival*.

## Microservice boundaries

| Direction | Channel | Source / Sink | Schema | Notes |
|---|---|---|---|---|
| Input | Redis Pub/Sub trigger | [[microservices_architecture\|orchestrator]] | `NegotiationTrigger {transaction_id, ranked_candidates[], policy}` | Single fan-in; transaction-scoped |
| Input | Redis Pub/Sub `beckn_results:{txn}` | [[beckn_bap_client]] | `OnSelectPayload` | Per ADR-0001; dual-written to Redis Streams |
| Input | HTTP / webhook | [[approval_workflow]] | `HitlDecision {accept|reject|override}` | Resumes graph via `Command(resume=...)` |
| Output | HTTP POST `/select` | [[beckn_bap_client]] → `onix-bap:8081` | Beckn v2.0.0 `/select` body | Never bypasses BAP client |
| Output | Redis Pub/Sub `negotiation_results:{txn}` | [[microservices_architecture\|orchestrator]] | `NegotiationOutcome` | Terminal events only |
| Output | [[event_streaming_kafka\|Kafka]] topic `negotiation.audit` | [[audit_trail_system]] | Per-round structured event | Append-only, cryptographically chained |
| Output | [[vector_db_qdrant_pinecone\|Qdrant]] `NegotiationMemory` | [[agent_memory_learning]] | Embedded outcome + features | Only on terminal state |

## No-go boundaries

The Negotiation Engine **must not**:

- POST directly to any BPP — all Beckn traffic flows through [[beckn_bap_client]] and `onix-bap:8081` (`CLAUDE.md` "Don't POST directly to a BPP" rule).
- Invoke [[nl_intent_parser]] or any LLM-based intent classifier — by the time control reaches this service, intent is already a frozen `BecknIntent`.
- Read `comparative_scoring.*` SQL tables — ranked candidates arrive only via the orchestrator-emitted trigger payload.
- Hold in-process state across rounds — every round-boundary state mutation must round-trip through the checkpointer so that a pod evicted mid-negotiation can be resumed elsewhere.
- Reuse a `transaction_id` (already forbidden by `CLAUDE.md`); LangGraph's `thread_id == transaction_id` policy transitively forbids checkpoint collisions.
- Time-share a single Python event loop with a synchronous `time.sleep()` — only `await asyncio.sleep(...)`. See `CLAUDE.md` "Don't `time.sleep()` to flush `asyncio.create_task`".

## Design decisions summary

| # | Decision | Rationale | Owning note |
|---|---|---|---|
| D1 | **LangGraph over custom orchestration** | Built-in checkpointing, interrupt/resume, replay, Mermaid export, and ecosystem alignment with [[agent_framework_langchain_langgraph]] | [[01_langgraph_state_machine]] |
| D2 | **`AsyncPostgresSaver` over Redis-backed checkpointer** | Full async stack; horizontal scaling (sqlite is single-writer); Redis is already saturated as transport; Postgres allows FK relationships into procurement schema for queryable audit | [[01_langgraph_state_machine]], [[04_resilience_and_mlops]] |
| D3 | **Contextual Bandits over full RL** | Sample efficiency (small procurement category fan-out); explainable policy; converges within enterprise data volumes; aligns with [[model_governance_monitoring]] | [[02_decision_intelligence_rl]] |
| D4 | **Guardrails as graph nodes, not decorators / prompts** | Audit replay visibility; deterministic enforcement that survives any [[llm_providers\|LLM]] hallucination; testable in isolation | [[03_hard_guardrails_policy]] |
| D5 | **`thread_id == transaction_id`** | Eliminates correlation bugs between Beckn `transaction_id`, Redis channel name, and LangGraph checkpoint key; transitively forbids checkpoint collisions | [[01_langgraph_state_machine]] |
| D6 | **Dual-write Pub/Sub + Redis Streams for `/on_select`** | Pub/Sub is fire-and-forget; if the engine pod was evicted between `dispatch_select` and `await_on_select` checkpoint write, the Streams replay restores the payload | [[04_resilience_and_mlops]] |
| D7 | **Two distinct interrupt semantics** (machine vs human) | Payload shapes, timeout horizons (seconds vs hours), and recovery actions differ by orders of magnitude; unifying them would compromise both | [[01_langgraph_state_machine]] |
| D8 | **`Command(goto=...)` from `evaluate_response`** | Atomic state-and-routing update preferred over conditional edges when the routing decision is a function of newly-computed state | [[01_langgraph_state_machine]] |

## Phase 3 acceptance trace

| [[phase3_advanced_intelligence_enterprise_features\|Phase 3]] deliverable | Owning sibling note |
|---|---|
| Multi-round negotiation state machine with bounded reasoning | [[01_langgraph_state_machine]] |
| Per-category negotiation strategy + adaptive policy | [[02_decision_intelligence_rl]] |
| Hard policy guardrail (20% cap, never breached) | [[03_hard_guardrails_policy]] |
| HITL escalation tied to [[approval_workflow]] | [[01_langgraph_state_machine]], [[04_resilience_and_mlops]] |
| Audit trail with cryptographic chaining | [[04_resilience_and_mlops]] → [[audit_trail_system]] |
| Cross-transaction learning loop | [[02_decision_intelligence_rl]] → [[agent_memory_learning]] |
| Production SLOs (round-trip latency, recovery time) | [[04_resilience_and_mlops]] |
| [[business_impact_metrics]] tracking (savings %, escalation rate) | [[04_resilience_and_mlops]] |

## Open questions

The following questions are *explicitly deferred* — they are not blocking the Phase 3 design but must be answered before GA hardening:

1. **Bandit promotion threshold** — at what sample count per category does the [[02_decision_intelligence_rl|Contextual Bandit]] take over from the rule-based policy? Initial heuristic is 200 terminal negotiations / category but this needs calibration against win-rate variance.
2. **Fairness regulariser weighting** — Phase 2 should not converge to a degenerate "always squeeze cheapest supplier" policy; the regulariser term in the reward function (see [[02_decision_intelligence_rl]]) needs sensitivity analysis against [[business_impact_metrics|supplier diversity KPIs]].
3. **Multi-supplier parallel negotiation** — current design negotiates the top-ranked candidate first and falls back sequentially; a parallel branch-and-bound topology is a known future extension but is out of scope for Phase 3.
4. **Long-running HITL ceiling** — the `human_in_the_loop` interrupt currently has no upper bound; do we hard-cancel at 24h, 72h, or never? Tied to the long-tail of [[approval_workflow]] cycle times.
5. **Cross-network negotiation** — Beckn supports multi-network discovery; the current state machine assumes a single `bpp_id` per round. Generalisation to network-spanning negotiations is deferred to Phase 4.

## References

- [[negotiation_engine]] — high-level component overview (parent context)
- [[negotiation_strategy_model]] — AI-model node (strategy taxonomy + reward shape)
- `docs/architecture/decisions/0001-use-redis-pubsub-for-async-beckn-responses.md` — ADR-0001 (async callback rationale)
- `CLAUDE.md` — repository conventions (async-first, no-direct-BPP, no `time.sleep`, `transaction_id` uniqueness)
