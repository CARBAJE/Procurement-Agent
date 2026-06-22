"""Unit tests for sim-bpp's auto-advance lifecycle (real_time_tracking demo).

Mocks the Kafka producer and the data-normalizer HTTP call so tests run in
~1s without docker / Kafka / Postgres. Covers:
  • Full lifecycle emits 5 states in order
  • Every emission persists AND publishes
  • Cancel mid-flow aborts the task
  • SIM_BPP_AUTO_ADVANCE=false → no task scheduled
  • Scheduling the same order twice is idempotent
"""
from __future__ import annotations

import asyncio
import os
import sys
from unittest.mock import AsyncMock

import pytest

sys.path.insert(
    0,
    os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")),
)

import handler  # noqa: E402


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def reset_state():
    """Clear the in-memory registry between tests so they don't interfere."""
    handler._advancing_orders.clear()
    handler._kafka_producer = None
    yield
    # Best-effort cancel of any task left running
    for task in list(handler._advancing_orders.values()):
        task.cancel()
    handler._advancing_orders.clear()
    handler._kafka_producer = None


# ── _auto_advance_lifecycle (the loop itself) ────────────────────────────────


@pytest.mark.asyncio
async def test_lifecycle_emits_all_5_states_in_order(monkeypatch):
    """All 5 states are emitted in order, with the expected po_status mapping."""
    monkeypatch.setattr(handler, "SIM_BPP_ADVANCE_INTERVAL_SECS", 0)

    publish_mock = AsyncMock()
    persist_mock = AsyncMock()
    monkeypatch.setattr(handler, "_publish_event", publish_mock)
    monkeypatch.setattr(handler, "_persist_po_status", persist_mock)

    await handler._auto_advance_lifecycle("order-123", "txn-456")

    assert publish_mock.await_count == 5
    states   = [call.args[0]["state"]     for call in publish_mock.await_args_list]
    statuses = [call.args[0]["po_status"] for call in publish_mock.await_args_list]
    assert states   == ["ACCEPTED", "PACKED", "SHIPPED", "OUT_FOR_DELIVERY", "DELIVERED"]
    assert statuses == ["confirmed", "confirmed", "shipped", "shipped", "delivered"]


@pytest.mark.asyncio
async def test_each_state_persists_and_publishes(monkeypatch):
    """Each lifecycle tick calls BOTH the DB persist and the Kafka publish."""
    monkeypatch.setattr(handler, "SIM_BPP_ADVANCE_INTERVAL_SECS", 0)

    publish_mock = AsyncMock()
    persist_mock = AsyncMock()
    monkeypatch.setattr(handler, "_publish_event", publish_mock)
    monkeypatch.setattr(handler, "_persist_po_status", persist_mock)

    await handler._auto_advance_lifecycle("order-X", "txn-Y")

    # Both helpers fire exactly once per state (5 each, ordered the same).
    assert persist_mock.await_count == 5
    assert publish_mock.await_count == 5

    expected_statuses = ["confirmed", "confirmed", "shipped", "shipped", "delivered"]
    for call, expected in zip(persist_mock.await_args_list, expected_statuses):
        assert call.args == ("order-X", expected)


# ── _cancel_auto_advance ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_cancel_aborts_lifecycle(monkeypatch):
    """Cancelling mid-flow stops further emissions and removes the registry entry."""
    monkeypatch.setattr(handler, "SIM_BPP_AUTO_ADVANCE", True)
    monkeypatch.setattr(handler, "SIM_BPP_ADVANCE_INTERVAL_SECS", 0.1)

    publish_mock = AsyncMock()
    persist_mock = AsyncMock()
    monkeypatch.setattr(handler, "_publish_event", publish_mock)
    monkeypatch.setattr(handler, "_persist_po_status", persist_mock)

    handler._schedule_auto_advance("order-cancel", "txn-cancel")
    assert "order-cancel" in handler._advancing_orders

    # Let it tick a couple of times then cancel.
    await asyncio.sleep(0.25)
    handler._cancel_auto_advance("order-cancel")

    # Give the cancellation a moment to propagate through the finally block.
    await asyncio.sleep(0.2)

    # Fewer than 5 states emitted (we cut it off mid-lifecycle).
    assert publish_mock.await_count < 5
    # And the registry entry is gone.
    assert "order-cancel" not in handler._advancing_orders


# ── _schedule_auto_advance (flag + idempotency) ──────────────────────────────


def test_default_off_does_nothing(monkeypatch):
    """With SIM_BPP_AUTO_ADVANCE=false, no task is scheduled."""
    monkeypatch.setattr(handler, "SIM_BPP_AUTO_ADVANCE", False)

    handler._schedule_auto_advance("order-A", "txn-A")

    assert handler._advancing_orders == {}


def test_missing_ids_skip_scheduling(monkeypatch):
    """Empty order_id or txn_id → don't schedule (avoids orphan tasks)."""
    monkeypatch.setattr(handler, "SIM_BPP_AUTO_ADVANCE", True)

    handler._schedule_auto_advance(None, "txn-A")
    handler._schedule_auto_advance("order-A", None)
    handler._schedule_auto_advance("", "")

    assert handler._advancing_orders == {}


@pytest.mark.asyncio
async def test_idempotent_schedule(monkeypatch):
    """Scheduling the same order_id twice creates only ONE task."""
    monkeypatch.setattr(handler, "SIM_BPP_AUTO_ADVANCE", True)
    # Long interval so the task is still pending when we re-schedule.
    monkeypatch.setattr(handler, "SIM_BPP_ADVANCE_INTERVAL_SECS", 60)

    publish_mock = AsyncMock()
    persist_mock = AsyncMock()
    monkeypatch.setattr(handler, "_publish_event", publish_mock)
    monkeypatch.setattr(handler, "_persist_po_status", persist_mock)

    handler._schedule_auto_advance("order-B", "txn-B")
    first_task = handler._advancing_orders["order-B"]

    handler._schedule_auto_advance("order-B", "txn-B")  # duplicate call
    second_task = handler._advancing_orders["order-B"]

    assert first_task is second_task  # same task object → not re-scheduled
    assert len(handler._advancing_orders) == 1
