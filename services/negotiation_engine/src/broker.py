"""Redis Pub/Sub listener + graph resumer.

Implements the *consumer side* of the async dance described in
``KnowledgeBase/project_scaffold/architecture/negotiation_engine/04_resilience_and_mlops.md``
§3 (park-and-resume sequence).

Architectural role:

1. The ``beckn_bap_client`` service receives ``/on_select`` webhooks
   from ``onix-bap`` and **publishes** the normalized payload to a
   per-transaction Redis channel (and dual-writes to a Redis Stream
   for durable replay — outside this module's scope).
2. This listener **subscribes** to that channel, extracts the
   ``transaction_id``, and **resumes the parked LangGraph thread**
   via ``graph.ainvoke(Command(resume=payload), config={"configurable":
   {"thread_id": transaction_id}})``.

The listener is intentionally framework-light — no FastAPI, no routes.
It is a single ``asyncio.Task`` that owns the Redis connection for its
lifetime and yields control to the graph when a message arrives.

Two channel patterns are supported:

* **Pattern subscription** on ``"beckn_results:*"`` — production
  default. Each session has its own channel (``beckn_results:{txn}``)
  written by the BAP client and matched here by glob.
* **Single-channel subscription** on
  :attr:`CONFIG.redis_on_select_channel` (default
  ``beckn_on_select_results``) — a multiplexed channel into which the
  BAP client writes ``{"transaction_id": ..., ...}`` envelopes. Useful
  for low-volume deployments and for the integration tests.

The listener accepts either; the message handler dispatches to the
right ``thread_id`` based on payload contents.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Awaitable, Callable, Optional

import redis.asyncio as redis
from langgraph.types import Command

from .audit import log_negotiation_event
from .config import CONFIG

logger = logging.getLogger(__name__)


# Default channel pattern. The BAP client publishes per-transaction
# results to ``beckn_results:{transaction_id}`` (matches the convention
# established by ADR-0001). The single-channel fallback handles
# multiplexed deployments.
DEFAULT_PATTERN: str = "beckn_results:*"


# ── Helpers ────────────────────────────────────────────────────────────────


def _extract_transaction_id(
    *, channel: str, payload: dict[str, Any]
) -> Optional[str]:
    """Recover the LangGraph ``thread_id`` from a Pub/Sub envelope.

    Prefers the payload's explicit ``transaction_id`` / ``correlation_id``
    fields. Falls back to parsing it out of the channel name
    (``beckn_results:{txn}``).
    """
    txn = (
        payload.get("transaction_id")
        or payload.get("correlation_id")
        or payload.get("txn_id")
    )
    if txn:
        return str(txn)

    if ":" in channel:
        return channel.split(":", 1)[1] or None

    return None


def _decode_message(raw: Any) -> Optional[dict[str, Any]]:
    """Decode a Pub/Sub payload to a dict. Returns ``None`` on parse error."""
    if raw is None:
        return None
    if isinstance(raw, bytes):
        try:
            raw = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            logger.warning("Pub/Sub payload not UTF-8: %s", exc)
            return None
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            logger.warning("Pub/Sub payload not JSON: %s", exc)
            return None
        return parsed if isinstance(parsed, dict) else {"raw": parsed}
    return None


# ── Resumer ────────────────────────────────────────────────────────────────


async def resume_graph(
    graph: Any,
    *,
    transaction_id: str,
    payload: dict[str, Any],
) -> dict[str, Any] | None:
    """Inject ``payload`` into the parked graph thread and continue execution.

    Implements the canonical resume pattern from
    ``01_langgraph_state_machine`` §async-interrupt-mechanics. Equivalent
    to::

        await graph.ainvoke(
            Command(resume=payload),
            config={"configurable": {"thread_id": transaction_id}},
        )

    Returns the post-resume snapshot from ``ainvoke`` or ``None`` on
    error.
    """
    config = {"configurable": {"thread_id": transaction_id}}
    try:
        result = await graph.ainvoke(Command(resume=payload), config=config)
    except Exception as exc:  # pragma: no cover - defensive
        logger.exception(
            "Failed to resume graph thread_id=%s: %s", transaction_id, exc
        )
        await log_negotiation_event(
            session_id=transaction_id,
            event_type="resume_failed",
            payload={"error": str(exc)},
            idempotency_key=f"{transaction_id}:resume_failed",
        )
        return None

    logger.info(
        "Graph resumed thread_id=%s next=%s",
        transaction_id,
        getattr(graph.get_state(config), "next", None),
    )
    return result


# ── Listener ───────────────────────────────────────────────────────────────


class OnSelectListener:
    """Long-lived Redis Pub/Sub listener that resumes parked LangGraph threads.

    Lifecycle::

        listener = OnSelectListener(graph)
        task = asyncio.create_task(listener.run())
        ...
        await listener.stop()
        await task

    The listener subscribes to *both* the per-transaction channel pattern
    (``beckn_results:*``) and the multiplexed channel
    (:attr:`CONFIG.redis_on_select_channel`). Either is sufficient; both
    means a deployment can migrate from one to the other without code
    changes.
    """

    def __init__(
        self,
        graph: Any,
        *,
        redis_url: Optional[str] = None,
        channel_pattern: str = DEFAULT_PATTERN,
        single_channel: Optional[str] = None,
        on_message: Optional[Callable[[str, dict], Awaitable[Any]]] = None,
    ) -> None:
        self._graph = graph
        self._redis_url = redis_url or CONFIG.redis_url
        self._channel_pattern = channel_pattern
        self._single_channel = single_channel or CONFIG.redis_on_select_channel
        self._on_message = on_message  # optional hook for tests
        self._client: Optional[redis.Redis] = None
        self._pubsub: Any = None
        self._stop_event = asyncio.Event()

    async def _ensure_client(self) -> redis.Redis:
        if self._client is None:
            self._client = redis.from_url(
                self._redis_url, decode_responses=True
            )
        return self._client

    async def start(self) -> None:
        """Open the Redis connection and subscribe to both channel patterns."""
        client = await self._ensure_client()
        self._pubsub = client.pubsub(ignore_subscribe_messages=True)
        await self._pubsub.psubscribe(self._channel_pattern)
        await self._pubsub.subscribe(self._single_channel)
        logger.info(
            "OnSelectListener subscribed pattern=%s single=%s",
            self._channel_pattern,
            self._single_channel,
        )

    async def stop(self) -> None:
        """Signal the listener loop to exit and close Redis cleanly."""
        self._stop_event.set()
        if self._pubsub is not None:
            try:
                await self._pubsub.punsubscribe(self._channel_pattern)
                await self._pubsub.unsubscribe(self._single_channel)
                await self._pubsub.close()
            except Exception:  # pragma: no cover - cleanup is best-effort
                logger.exception("Error closing pubsub")
            self._pubsub = None
        if self._client is not None:
            try:
                await self._client.aclose()
            except Exception:  # pragma: no cover
                logger.exception("Error closing redis client")
            self._client = None

    async def handle_message(self, channel: str, payload: dict[str, Any]) -> None:
        """Process a single Pub/Sub message — extract thread_id and resume."""
        txn = _extract_transaction_id(channel=channel, payload=payload)
        if not txn:
            logger.warning(
                "Pub/Sub message has no recoverable transaction_id "
                "(channel=%s payload_keys=%s)",
                channel,
                list(payload.keys()),
            )
            return

        if self._on_message is not None:
            # Test hook bypasses the resumer.
            await self._on_message(txn, payload)
            return

        await resume_graph(self._graph, transaction_id=txn, payload=payload)

    async def run(self) -> None:
        """Subscribe and pump messages until :meth:`stop` is called.

        Designed to be wrapped in an ``asyncio.create_task(...)`` by the
        service entrypoint. Reconnect-on-error is *not* handled here —
        the production wiring step adds an outer supervisor with
        exponential backoff (architecture ``04_resilience_and_mlops``
        §6 Redis-Pub/Sub-down row).
        """
        await self.start()
        try:
            while not self._stop_event.is_set():
                try:
                    msg = await asyncio.wait_for(
                        self._pubsub.get_message(
                            ignore_subscribe_messages=True, timeout=1.0
                        ),
                        timeout=1.5,
                    )
                except asyncio.TimeoutError:
                    continue
                if msg is None:
                    continue

                channel = msg.get("channel") or ""
                if isinstance(channel, bytes):
                    channel = channel.decode("utf-8", errors="replace")

                payload = _decode_message(msg.get("data"))
                if payload is None:
                    continue

                await self.handle_message(channel, payload)
        finally:
            await self.stop()


# ── Module-level convenience for one-shot scripts ──────────────────────────


async def run_listener(
    graph: Any,
    *,
    redis_url: Optional[str] = None,
    channel_pattern: str = DEFAULT_PATTERN,
    single_channel: Optional[str] = None,
) -> None:
    """Drop-in entrypoint that spins up a listener and blocks until cancelled."""
    listener = OnSelectListener(
        graph,
        redis_url=redis_url,
        channel_pattern=channel_pattern,
        single_channel=single_channel,
    )
    try:
        await listener.run()
    except asyncio.CancelledError:  # pragma: no cover
        logger.info("OnSelectListener cancelled — shutting down")
        await listener.stop()
        raise


__all__ = [
    "DEFAULT_PATTERN",
    "OnSelectListener",
    "resume_graph",
    "run_listener",
]
