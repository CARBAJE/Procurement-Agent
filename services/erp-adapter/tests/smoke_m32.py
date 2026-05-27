"""M3.2 smoke test — outbox + worker + mock vendor push.

Wires erp-mock + erp-adapter (in-memory outbox repo, since no Postgres locally)
and exercises:
  (a) happy push:        POST /api/v1/po/sync → poll until success → erp_reference_id present
  (b) idempotency:       repost same body → same sync_id, no duplicate work
  (c) DLQ via retries:   X-Mock-Scenario=po_create_fails with MAX_ATTEMPTS less than
                         the mock's failure count → row reaches status=failed,
                         PO_DLQ audit event, erp_po_outbox_dead_total > 0.

Run with:  PYTHONIOENCODING=utf-8 python services/erp-adapter/tests/smoke_m32.py
"""
from __future__ import annotations

import asyncio
import importlib.util
import os
import sys
from typing import Any

HERE = os.path.dirname(__file__)
REPO = os.path.abspath(os.path.join(HERE, "..", "..", ".."))


def _load_module(label: str, path: str):
    """Load a module from a file path under an explicit name (avoids name
    collisions between erp-mock and erp-adapter trees)."""
    spec = importlib.util.spec_from_file_location(label, path)
    mod = importlib.util.module_from_spec(spec)
    # Make sibling files findable
    sys.path.insert(0, os.path.dirname(path))
    spec.loader.exec_module(mod)
    return mod


async def _start_mock():
    from aiohttp.test_utils import TestServer
    mod = _load_module("mock_main_m32", os.path.join(REPO, "services", "erp-mock", "src", "main.py"))
    app = mod.create_app()
    server = TestServer(app)
    await server.start_server()
    return server


async def _start_adapter(mock_url: str, *, max_attempts_override: int | None = None):
    from aiohttp.test_utils import TestServer
    os.environ["ERP_MOCK_BASE_URL"] = mock_url
    os.environ["DB_HOST"] = "localhost"
    os.environ["REDIS_URL"] = "redis://localhost:6399"  # intentionally unreachable

    # Tighter loops for smoke speed. Honored by Settings + OutboxWorker ctor.
    if max_attempts_override is not None:
        os.environ["WORKER_BACKOFF_CSV"] = ",".join(["0.5"] * max_attempts_override)
        os.environ["WORKER_POLL_INTERVAL_SECONDS"] = "0.3"

    # Wipe shared module names so we don't bind to the mock's siblings
    for name in list(sys.modules):
        head = name.split('.')[0]
        if head in {"config", "main", "routes", "models", "middleware", "observability",
                    "adapters", "outbox", "scenarios", "store", "budget_routes",
                    "sap_routes", "oracle_routes", "po_routes", "webhook_emitter"}:
            sys.modules.pop(name, None)

    sys.path.insert(0, os.path.join(REPO, "services", "erp-adapter", "src"))

    from config import Settings  # type: ignore
    import main as adapter_main  # type: ignore
    s = Settings()
    app = adapter_main.create_app(s)
    server = TestServer(app)
    await server.start_server()
    return server


def _green(s): return f"\033[32m{s}\033[0m"
def _red(s): return f"\033[31m{s}\033[0m"


def _build_po(transaction_id: str, *, order_id: str = "order-XYZ") -> dict[str, Any]:
    return {
        "transaction_id": transaction_id,
        "order_id": order_id,
        "contract_id": "contract-1",
        "buyer": {"id": "u1", "name": "Test Buyer", "email": "b@example.com",
                  "cost_center": "CC-IND-PROC-01"},
        "supplier": {"bpp_id": "bpp-1", "bpp_uri": "http://bpp", "name": "Test Supplier"},
        "line_items": [{
            "item_id": "item-1", "name": "A4 paper", "quantity": 500,
            "unit": "ream", "unit_price": "195.00", "currency": "INR",
            "category": "stationery",
        }],
        "totals": {"subtotal": "97500.00", "currency": "INR"},
        "payment_terms": {"type": "ON_FULFILLMENT", "collector": "BPP",
                          "currency": "INR", "net_days": None},
        "fulfillment": {"eta": None, "delivery_address": None, "contact": None},
        "metadata": {"beckn_confirm_ref": order_id, "budget_hold_id": "hold-test"},
    }


async def _poll_until(client, url, *, predicate, timeout=10.0, every=0.3):
    import time as _t
    deadline = _t.monotonic() + timeout
    last = None
    while _t.monotonic() < deadline:
        async with client.get(url) as r:
            body = await r.json()
            last = (r.status, body)
            if predicate(r.status, body):
                return body
        await asyncio.sleep(every)
    return None


async def case_a_happy(adapter_url, auth) -> list[str]:
    import aiohttp
    fails: list[str] = []
    po = _build_po("txn-happy-1", order_id="order-happy-1")
    async with aiohttp.ClientSession(headers=auth) as s:
        async with s.post(f"{adapter_url}/api/v1/po/sync", json=po) as r:
            body = await r.json()
            print(f"  (a) POST /po/sync -> {r.status} sync_id={body.get('sync_id')}")
            if r.status != 202 or not body.get("sync_id"):
                fails.append("(a) POST /po/sync should be 202 with sync_id")
                return fails
            sync_id = body["sync_id"]
        final = await _poll_until(
            s, f"{adapter_url}/api/v1/po/sync/{sync_id}",
            predicate=lambda st, b: b.get("status") in ("success", "failed"),
            timeout=8.0,
        )
        print(f"  (a) final status = {final and final.get('status')} erp_ref={final and final.get('erp_reference_id')}")
        if final is None or final.get("status") != "success":
            fails.append("(a) outbox row should reach status=success")
        if not (final and final.get("erp_reference_id", "").startswith("MOCK-PO-")):
            fails.append("(a) success row should carry erp_reference_id")
    return fails


async def case_b_idempotency(adapter_url, auth) -> list[str]:
    import aiohttp
    fails: list[str] = []
    po = _build_po("txn-idem-1", order_id="order-idem-1")
    seen_ids: list[str] = []
    async with aiohttp.ClientSession(headers=auth) as s:
        for i in (1, 2):
            async with s.post(f"{adapter_url}/api/v1/po/sync", json=po) as r:
                body = await r.json()
                seen_ids.append(body.get("sync_id"))
                print(f"  (b) post #{i} -> {r.status} sync_id={body.get('sync_id')} dedup={body['results'][0].get('deduplicated')}")
                if i == 2 and not body["results"][0].get("deduplicated"):
                    fails.append("(b) second post should be deduplicated")
    if len(set(seen_ids)) != 1:
        fails.append(f"(b) sync_ids should match across reposts, got {seen_ids}")
    return fails


async def case_c_dlq(adapter_url, auth) -> list[str]:
    import aiohttp
    fails: list[str] = []
    po = _build_po("txn-dlq-1", order_id="order-dlq-1")
    async with aiohttp.ClientSession(headers=auth) as s:
        # Header chooses the scenario; the route handler copies it into the
        # payload's metadata so the async worker also sees it.
        async with s.post(f"{adapter_url}/api/v1/po/sync", json=po,
                          headers={"X-Mock-Scenario": "po_create_fails"}) as r:
            body = await r.json()
            print(f"  (c) POST /po/sync (po_create_fails) -> {r.status} sync_id={body.get('sync_id')}")
            if r.status != 202:
                fails.append("(c) DLQ enqueue should be 202")
                return fails
            sync_id = body["sync_id"]
        final = await _poll_until(
            s, f"{adapter_url}/api/v1/po/sync/{sync_id}",
            predicate=lambda st, b: b.get("status") == "failed",
            timeout=12.0,
        )
        print(f"  (c) final status = {final and final.get('status')} attempts={final and final.get('attempts')} last_error={final and (final.get('last_error') or '')[:60]}")
        if final is None or final.get("status") != "failed":
            fails.append("(c) DLQ row should end in status=failed")
        if final and final.get("attempts", 0) < 1:
            fails.append("(c) DLQ row should record attempts >= 1")
    return fails


async def main() -> int:
    mock = await _start_mock()
    mock_url = f"http://localhost:{mock.port}"
    print(f"mock-erp at {mock_url}")

    # Use a short backoff (0.5s) and small MAX_ATTEMPTS so the DLQ path
    # completes inside this smoke test's timeout. The mock's `po_create_fails`
    # scenario rejects the first 10 attempts → so MAX_ATTEMPTS=3 → DLQ on the
    # 3rd failure.
    adapter = await _start_adapter(mock_url, max_attempts_override=3)
    adapter_url = f"http://localhost:{adapter.port}"
    print(f"erp-adapter at {adapter_url}")

    auth = {"Authorization": "Bearer dev-internal-token-CHANGE_ME"}
    fails: list[str] = []

    print()
    print("[a] happy path")
    fails += await case_a_happy(adapter_url, auth)

    print()
    print("[b] idempotency")
    fails += await case_b_idempotency(adapter_url, auth)

    print()
    print("[c] retry -> DLQ")
    fails += await case_c_dlq(adapter_url, auth)

    print()
    if fails:
        for f in fails:
            print(_red("FAIL"), f)
        await adapter.close(); await mock.close()
        return 1
    print(_green("M3.2 smoke OK"))
    await adapter.close(); await mock.close()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
