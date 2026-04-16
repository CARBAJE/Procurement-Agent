"""Tests for the Beckn v2 async callback collector.

In Beckn v2, discovery is synchronous — no on_search callbacks.
Async callbacks still exist for transactional flows:
  on_select, on_init, on_confirm, on_status

These arrive at /bap/receiver/{action} from the ONIX adapter.
"""
import asyncio

import pytest

from src.beckn.callbacks import CallbackCollector
from src.beckn.models import CallbackPayload


def make_callback_payload(transaction_id: str, action: str, bpp_id: str = "bpp-1") -> dict:
    return {
        "context": {
            "domain": "nic2004:52110",
            "action": action,
            "country": "IND",
            "city": "std:080",
            "core_version": "2.0.0",
            "bap_id": "test-bap",
            "bap_uri": "http://localhost:8000/beckn",
            "bpp_id": bpp_id,
            "bpp_uri": f"http://{bpp_id}.test",
            "transaction_id": transaction_id,
            "message_id": f"msg-{bpp_id}",
            "timestamp": "2024-01-01T00:00:00.000Z",
        },
        "message": {"order": {"id": "order-001", "state": "ACCEPTED"}},
    }


# ── Parsing ───────────────────────────────────────────────────────────────────


def test_callback_payload_parses():
    payload = make_callback_payload("txn-1", "on_select")
    cb = CallbackPayload.model_validate(payload)
    assert cb.context.transaction_id == "txn-1"
    assert cb.context.action == "on_select"


# ── Collector: handle_callback ────────────────────────────────────────────────


async def test_handle_callback_returns_ack(collector):
    collector.register("txn-1", "on_select")
    ack = await collector.handle_callback("on_select", make_callback_payload("txn-1", "on_select"))
    assert ack == {"message": {"ack": {"status": "ACK"}}}


async def test_handle_callback_ignores_unregistered_transaction(collector):
    ack = await collector.handle_callback("on_select", make_callback_payload("txn-unknown", "on_select"))
    assert ack["message"]["ack"]["status"] == "ACK"


# ── Collector: collect ────────────────────────────────────────────────────────


async def test_collect_on_select_response(collector):
    collector.register("txn-sel", "on_select")
    await collector.handle_callback("on_select", make_callback_payload("txn-sel", "on_select"))

    results = await collector.collect("txn-sel", "on_select", timeout=0.1)
    assert len(results) == 1
    assert isinstance(results[0], CallbackPayload)


async def test_collect_returns_empty_for_unregistered(collector):
    results = await collector.collect("txn-nope", "on_select", timeout=0.05)
    assert results == []


async def test_collect_timeout_with_no_callback(collector):
    collector.register("txn-wait", "on_init")
    results = await collector.collect("txn-wait", "on_init", timeout=0.05)
    assert results == []


async def test_collect_routes_by_action(collector):
    """on_select and on_init callbacks for the same txn must not bleed."""
    collector.register("txn-A", "on_select")
    collector.register("txn-A", "on_init")

    await collector.handle_callback("on_select", make_callback_payload("txn-A", "on_select", "bpp-sel"))
    await collector.handle_callback("on_init", make_callback_payload("txn-A", "on_init", "bpp-init"))

    sel = await collector.collect("txn-A", "on_select", timeout=0.1)
    ini = await collector.collect("txn-A", "on_init", timeout=0.1)

    assert len(sel) == 1 and sel[0].context.bpp_id == "bpp-sel"
    assert len(ini) == 1 and ini[0].context.bpp_id == "bpp-init"


async def test_collect_routes_by_transaction_id(collector):
    """Callbacks for different txns must not bleed."""
    collector.register("txn-B", "on_select")
    collector.register("txn-C", "on_select")

    await collector.handle_callback("on_select", make_callback_payload("txn-B", "on_select", "bpp-b"))
    await collector.handle_callback("on_select", make_callback_payload("txn-C", "on_select", "bpp-c"))

    b = await collector.collect("txn-B", "on_select", timeout=0.1)
    c = await collector.collect("txn-C", "on_select", timeout=0.1)

    assert len(b) == 1 and b[0].context.bpp_id == "bpp-b"
    assert len(c) == 1 and c[0].context.bpp_id == "bpp-c"


async def test_cleanup_removes_queue(collector):
    collector.register("txn-clean", "on_select")
    collector.cleanup("txn-clean", "on_select")
    results = await collector.collect("txn-clean", "on_select", timeout=0.05)
    assert results == []


async def test_concurrent_callbacks_all_received(collector):
    collector.register("txn-conc", "on_confirm")

    async def post(bpp: str) -> None:
        await collector.handle_callback("on_confirm", make_callback_payload("txn-conc", "on_confirm", bpp))

    await asyncio.gather(*[post(f"bpp-{i}") for i in range(5)])
    results = await collector.collect("txn-conc", "on_confirm", timeout=0.2)
    assert len(results) == 5
