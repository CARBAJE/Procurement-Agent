"""Async callback collector for Beckn v2 transaction flows.

In Beckn v2, discovery is synchronous (no callbacks needed). But the
transactional flows (select, init, confirm, status) still use async callbacks:

    BAP sends /bap/caller/select  →  ONIX routes to BPP
    BPP responds async            →  ONIX delivers to /bap/receiver/on_select

This collector handles those async callbacks by routing them to per-transaction
queues, allowing the agent to await results after sending a request.

Typical flow:
    collector.register(txn_id, "on_select")
    ack = await client.select(order, txn_id, bpp_id, bpp_uri)
    callback = await collector.collect(txn_id, "on_select", timeout=10.0)
"""
from __future__ import annotations

import asyncio

from .models import CallbackPayload


class CallbackCollector:
    """Routes async ONIX callbacks to per-transaction queues."""

    def __init__(self, default_timeout: float = 10.0) -> None:
        self.default_timeout = default_timeout
        # key: (transaction_id, action)  e.g. ("txn-123", "on_select")
        self._queues: dict[tuple[str, str], asyncio.Queue[CallbackPayload]] = {}

    def register(self, transaction_id: str, action: str) -> None:
        """Open a queue for an expected callback before sending the request."""
        self._queues[(transaction_id, action)] = asyncio.Queue()

    async def handle_callback(self, action: str, payload: dict) -> dict:
        """Process an inbound callback from the ONIX adapter.

        Called by your /bap/receiver/{action} route handler.
        Returns ACK immediately so ONIX isn't blocked.
        """
        cb = CallbackPayload.model_validate(payload)
        txn_id = cb.context.transaction_id
        queue = self._queues.get((txn_id, action))
        if queue is not None:
            await queue.put(cb)
        return {"message": {"ack": {"status": "ACK"}}}

    async def collect(
        self,
        transaction_id: str,
        action: str,
        timeout: float | None = None,
    ) -> list[CallbackPayload]:
        """Collect all callbacks for a (transaction_id, action) pair.

        Drains the queue until no new callback arrives within timeout.
        """
        wait = timeout if timeout is not None else self.default_timeout
        queue = self._queues.get((transaction_id, action))
        if queue is None:
            return []

        results: list[CallbackPayload] = []
        while True:
            try:
                item = await asyncio.wait_for(queue.get(), timeout=wait)
                results.append(item)
            except asyncio.TimeoutError:
                break
        return results

    def cleanup(self, transaction_id: str, action: str) -> None:
        self._queues.pop((transaction_id, action), None)
