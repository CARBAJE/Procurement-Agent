"""Unit tests for TransactionSessionStore + InMemoryBackend.

These cover the storage layer that /compare writes and /commit + /status read.
No HTTP, no asyncio loop except for the sweeper test.
"""
from __future__ import annotations

import asyncio

import pytest

from src.agent.session import (
    DEFAULT_TTL_SECONDS,
    InMemoryBackend,
    TransactionSessionStore,
)


# ── Backend (synchronous) ────────────────────────────────────────────────────


def test_put_and_get_roundtrips_state():
    backend = InMemoryBackend()
    state = {"transaction_id": "t-1", "messages": ["hello"]}
    backend.put("t-1", state)
    assert backend.get("t-1") == state


def test_get_returns_none_for_missing_txn():
    backend = InMemoryBackend()
    assert backend.get("nope") is None


def test_delete_removes_entry():
    backend = InMemoryBackend()
    backend.put("t-1", {"foo": "bar"})
    backend.delete("t-1")
    assert backend.get("t-1") is None


def test_sweep_removes_expired_and_keeps_fresh():
    backend = InMemoryBackend()
    backend.put("old", {"a": 1})
    backend.put("young", {"a": 2})
    # Fake an ancient entry.
    backend._store["old"].created_at = 0.0
    removed = backend.sweep(now=1000.0, ttl=60.0)
    assert removed == 1
    assert backend.get("old") is None
    assert backend.get("young") == {"a": 2}


# ── Facade: TransactionSessionStore ─────────────────────────────────────────


def test_store_default_ttl_matches_module_constant():
    store = TransactionSessionStore()
    assert store._ttl == DEFAULT_TTL_SECONDS


def test_store_update_merges_patch_into_existing_state():
    store = TransactionSessionStore()
    store.put("t-1", {"messages": ["first"], "transaction_id": "t-1"})
    merged = store.update("t-1", order_id="ORD-999", messages=["second"])
    # update() is shallow merge — later fields win (messages replaced, not appended).
    assert merged["order_id"] == "ORD-999"
    assert merged["messages"] == ["second"]
    assert merged["transaction_id"] == "t-1"
    assert store.get("t-1") == merged


def test_store_update_on_missing_txn_creates_new_entry():
    store = TransactionSessionStore()
    merged = store.update("fresh", order_id="ORD-1")
    assert merged == {"order_id": "ORD-1"}
    assert store.get("fresh") == {"order_id": "ORD-1"}


def test_store_delete():
    store = TransactionSessionStore()
    store.put("t-1", {"a": 1})
    store.delete("t-1")
    assert store.get("t-1") is None


# ── Sweeper (async) ──────────────────────────────────────────────────────────


async def test_sweeper_starts_and_stops_cleanly():
    store = TransactionSessionStore(sweep_interval=0.01)
    await store.start_sweeper()
    assert store._sweeper is not None
    assert not store._sweeper.done()
    # Let it tick a couple of times.
    await asyncio.sleep(0.05)
    await store.stop_sweeper()
    assert store._sweeper is None


async def test_sweep_now_removes_expired_entries():
    store = TransactionSessionStore(ttl_seconds=60.0)
    store.put("recent", {"x": 1})
    # Force an ancient entry by manipulating the backend directly.
    store._backend._store["ancient"] = store._backend._store["recent"].__class__(
        state={"x": 2}, created_at=0.0,
    )
    removed = store.sweep_now()
    assert removed == 1
    assert store.get("recent") == {"x": 1}
    assert store.get("ancient") is None
