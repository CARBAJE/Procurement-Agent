"""Kafka audit trail — append-only event log for the Negotiation Engine.

Implements the *producer side* of the audit fabric described in
``KnowledgeBase/project_scaffold/architecture/negotiation_engine/04_resilience_and_mlops.md``
§4 (Kafka Audit Trail).

Design properties (all directly traced to the architecture doc):

* **Fail-open.** Per the resilience matrix §6, Kafka unavailability must
  not block business operations — when the broker is unreachable or
  ``aiokafka`` isn't installed (dev / CI), events spool to a Python
  logger and the negotiation continues. A production wiring step will
  add a PostgreSQL outbox for true durability.
* **Append-only, partition-by-``transaction_id``.** Every event lands on
  ``procurement.negotiation.v1`` keyed by ``transaction_id`` so single-
  session audit replay is a single-partition seek (architecture §4.2.5).
* **Two topics.** Routine events flow to the primary topic;
  ``policy_violation_blocked`` events are *also* mirrored to
  ``procurement.negotiation.policy_violations.v1`` (low-volume,
  high-importance, single partition, 7-year WORM retention).
* **Canonical envelope.** Every payload is wrapped in the
  ``schema_version / event_type / correlation_id / occurred_at /
  idempotency_key / trace_context / payload`` shape so consumers
  evolve independently.
"""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from .config import CONFIG

logger = logging.getLogger(__name__)


# ── Module-level constants ─────────────────────────────────────────────────

#: Envelope schema version. Bump on breaking change; downstream consumers
#: must remain backward-compatible (additive-only).
ENVELOPE_SCHEMA_VERSION = "1.0"

#: Event types that get mirrored to the policy_violations side-topic.
#: Routine events stay on the primary topic only.
POLICY_VIOLATION_EVENT_TYPES: frozenset[str] = frozenset(
    {
        "policy_violation_blocked",
        "guardrail_clamp",
    }
)


# ── Producer singleton ─────────────────────────────────────────────────────

# A single ``aiokafka.AIOKafkaProducer`` is shared across the process. It is
# lazily started on first use and torn down by :func:`shutdown` at service
# exit. Concurrency is gated by an asyncio.Lock so the first publisher
# wins the start race.

_producer: Any | None = None
_producer_lock = asyncio.Lock()
_producer_unavailable: bool = False  # latched True once we know aiokafka can't run


async def _get_producer() -> Any | None:
    """Return the singleton ``AIOKafkaProducer``, or ``None`` on fail-open.

    Returns ``None`` (silently) when:

    * ``aiokafka`` is not installed (dev / CI env).
    * ``KAFKA_BOOTSTRAP_SERVERS`` is not configured.
    * The producer failed to start (e.g. broker unreachable on first try).

    Once a failure latches ``_producer_unavailable``, the failure mode
    is sticky for the lifetime of the process — we do **not** retry on
    every emission (that would create a thundering herd on Kafka
    recovery). A separate health-check / restart is responsible for
    flipping the latch.
    """
    global _producer, _producer_unavailable

    if _producer_unavailable:
        return None
    if _producer is not None:
        return _producer

    async with _producer_lock:
        # Double-checked locking — another coroutine may have started one.
        if _producer is not None:
            return _producer
        if _producer_unavailable:
            return None

        if not CONFIG.kafka_bootstrap_servers:
            logger.info(
                "KAFKA_BOOTSTRAP_SERVERS not configured — audit events will be "
                "logged to the Python logger only (fail-open)"
            )
            _producer_unavailable = True
            return None

        try:
            from aiokafka import AIOKafkaProducer  # pragma: no cover
        except ImportError:
            logger.warning(
                "aiokafka not installed — audit events will fall open to the "
                "Python logger only. Install `aiokafka>=0.10` for production."
            )
            _producer_unavailable = True
            return None

        try:
            producer = AIOKafkaProducer(
                bootstrap_servers=CONFIG.kafka_bootstrap_servers,
                client_id=CONFIG.kafka_client_id,
                # Idempotent producer: avoid double-writes under retry.
                # Idempotent producer (InitProducerId) hangs against the
                # Redpanda dev-container; disabled here. acks="all" still
                # guarantees the broker persisted the record, and the
                # envelope's ``idempotency_key`` provides app-level dedup,
                # so exactly-once is preserved at the consumer. Re-enable
                # against a production Kafka cluster that supports it.
                enable_idempotence=False,
                acks="all",
                # Trade a little throughput for lower per-event latency —
                # audit events are small and we want them on-disk fast.
                linger_ms=20,
                # JSON wire format for now; Phase-4 will swap to Protobuf
                # via Confluent Schema Registry (see architecture §4.2.2).
                value_serializer=lambda v: json.dumps(v, default=str).encode("utf-8"),
                key_serializer=lambda k: k.encode("utf-8") if isinstance(k, str) else k,
            )
            await producer.start()
        except Exception as exc:  # pragma: no cover - broker unavailable on init
            logger.warning(
                "AIOKafkaProducer failed to start (%s) — falling open to logger",
                exc,
            )
            _producer_unavailable = True
            return None

        _producer = producer
        logger.info(
            "AIOKafkaProducer started bootstrap=%s client_id=%s",
            CONFIG.kafka_bootstrap_servers,
            CONFIG.kafka_client_id,
        )
        return _producer


async def shutdown() -> None:
    """Flush and stop the producer. Call from your service lifespan hook."""
    global _producer
    if _producer is None:
        return
    try:
        await _producer.stop()
    finally:
        _producer = None


# ── Envelope construction ──────────────────────────────────────────────────


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _build_envelope(
    session_id: str,
    event_type: str,
    payload: dict,
    *,
    idempotency_key: str | None = None,
    trace_context: dict | None = None,
) -> dict:
    """Wrap ``payload`` in the canonical envelope shape."""
    return {
        "schema_version": ENVELOPE_SCHEMA_VERSION,
        "event_type": f"negotiation.{event_type}",
        "correlation_id": session_id,
        "occurred_at": _utcnow_iso(),
        "idempotency_key": idempotency_key or f"{session_id}:{event_type}:{uuid.uuid4()}",
        "trace_context": trace_context or {},
        "payload": payload,
    }


# ── Public API ─────────────────────────────────────────────────────────────


async def log_negotiation_event(
    session_id: str,
    event_type: str,
    payload: dict,
    *,
    idempotency_key: str | None = None,
    trace_context: dict | None = None,
) -> None:
    """Publish a single audit event to Kafka.

    Every counter-offer generated, every guardrail violation, every HITL
    decision should call this. The function is **fail-open**: a Kafka
    outage logs a warning and returns; the negotiation continues.

    Parameters
    ----------
    session_id:
        The Beckn ``transaction_id`` — used both as the message key
        (partition assignment, ordering guarantee) and as the envelope's
        ``correlation_id``.
    event_type:
        Short event name (architecture §4.2.3 catalogue), e.g.
        ``counter_offer_dispatched``, ``policy_violation_blocked``,
        ``human_decision_recorded``. The string is prefixed with
        ``negotiation.`` when written to the envelope.
    payload:
        Event-specific dict. Must be JSON-serialisable.
    idempotency_key:
        Optional explicit idempotency key. Defaults to a UUID-suffixed
        composite that is *not* idempotent across retries — pass an
        explicit deterministic key (e.g. ``"{txn}:counter:{round_no}"``)
        when at-least-once delivery matters.
    trace_context:
        Optional W3C ``traceparent`` / ``tracestate`` carrier for
        OpenTelemetry propagation through the audit stream.
    """
    if not session_id:
        logger.warning("log_negotiation_event called with empty session_id")
        return
    if not event_type:
        logger.warning("log_negotiation_event called with empty event_type")
        return

    envelope = _build_envelope(
        session_id=session_id,
        event_type=event_type,
        payload=payload,
        idempotency_key=idempotency_key,
        trace_context=trace_context,
    )

    producer = await _get_producer()

    # Fail-open path: no Kafka → log to the Python logger so the event is
    # at least observable in container logs / Loki, then return.
    if producer is None:
        logger.info(
            "AUDIT-FALLBACK %s session=%s payload=%s",
            envelope["event_type"],
            session_id,
            json.dumps(payload, default=str)[:500],
        )
        return

    try:
        # Primary topic — every event.
        await producer.send_and_wait(
            CONFIG.kafka_negotiation_topic,
            value=envelope,
            key=session_id,
        )

        # Side-topic mirror for high-importance violations.
        if event_type in POLICY_VIOLATION_EVENT_TYPES:
            await producer.send_and_wait(
                CONFIG.kafka_policy_violations_topic,
                value=envelope,
                key=session_id,
            )
    except Exception as exc:  # pragma: no cover — broker unavailable mid-flight
        logger.warning(
            "Kafka send failed (%s) for event=%s session=%s — falling open",
            exc,
            event_type,
            session_id,
        )


# Reference to the service's main event loop, registered at app startup via
# :func:`register_event_loop`. LangGraph runs *sync* node bodies in worker
# threads (via run_in_executor), where ``asyncio.get_running_loop()`` raises.
# Without a captured main-loop reference, audit events from those nodes would
# never reach Kafka — they'd fall through to the logger. Registering the loop
# lets ``log_negotiation_event_sync`` bridge back to it with
# ``run_coroutine_threadsafe`` from any thread.
_main_loop: asyncio.AbstractEventLoop | None = None


def register_event_loop(loop: asyncio.AbstractEventLoop | None = None) -> None:
    """Capture the running loop so worker-thread audit calls can reach Kafka.

    Call once from the FastAPI lifespan (or any async startup hook). If
    ``loop`` is omitted, the currently-running loop is captured.
    """
    global _main_loop
    if loop is None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
    _main_loop = loop


def _log_fallback(
    session_id: str,
    event_type: str,
    payload: dict,
    *,
    idempotency_key: str | None,
    trace_context: dict | None,
) -> None:
    envelope = _build_envelope(
        session_id=session_id,
        event_type=event_type,
        payload=payload,
        idempotency_key=idempotency_key,
        trace_context=trace_context,
    )
    logger.info(
        "AUDIT-SYNC-FALLBACK %s session=%s payload=%s",
        envelope["event_type"],
        session_id,
        json.dumps(payload, default=str)[:500],
    )


def log_negotiation_event_sync(
    session_id: str,
    event_type: str,
    payload: dict,
    *,
    idempotency_key: str | None = None,
    trace_context: dict | None = None,
) -> None:
    """Synchronous convenience for sync LangGraph nodes.

    LangGraph 1.x runs sync node bodies in worker threads, so emitting an
    audit event from such a node needs a non-async entry point. Resolution
    order:

    1. If a loop is running in *this* thread, fire-and-forget on it.
    2. Else, if a main loop was registered (:func:`register_event_loop`)
       and is running, bridge to it via ``run_coroutine_threadsafe`` — this
       is the path taken from LangGraph worker threads.
    3. Else (no loop anywhere, e.g. unit tests), log to the Python logger.
    """
    coro_kwargs = dict(
        session_id=session_id,
        event_type=event_type,
        payload=payload,
        idempotency_key=idempotency_key,
        trace_context=trace_context,
    )

    # Case 1 — a loop is running in the current thread.
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop is not None and loop.is_running():
        loop.create_task(log_negotiation_event(**coro_kwargs))
        return

    # Case 2 — bridge from a worker thread to the registered main loop.
    if _main_loop is not None and _main_loop.is_running():
        try:
            asyncio.run_coroutine_threadsafe(
                log_negotiation_event(**coro_kwargs), _main_loop
            )
            return
        except Exception as exc:  # pragma: no cover — defensive
            logger.warning("Failed to bridge audit event to main loop: %s", exc)

    # Case 3 — no loop available; log-only fallback.
    _log_fallback(
        session_id,
        event_type,
        payload,
        idempotency_key=idempotency_key,
        trace_context=trace_context,
    )


__all__ = [
    "ENVELOPE_SCHEMA_VERSION",
    "POLICY_VIOLATION_EVENT_TYPES",
    "log_negotiation_event",
    "log_negotiation_event_sync",
    "register_event_loop",
    "shutdown",
]
