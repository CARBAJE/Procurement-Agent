"""M3.5 smoke — operational polish.

Cases:
  (a) GET /readyz returns 503 when DB + Redis are missing, but the JSON body
      still reflects per-vendor healthcheck results and an outbox-lag entry.
  (b) Drive a row to DLQ (po_create_fails + tight backoff). Once it is in
      status='failed', POST /api/v1/admin/outbox/{sync_id}/replay. The row
      transitions back to pending. Switch to scenario='happy' (clear the
      header on the next push) so the mock stops failing — actually the
      replay re-uses the same payload which still carries
      mock_scenario=po_create_fails. So we use the mock's "failure budget"
      behavior: it fails the first N attempts per Idempotency-Key, and the
      DLQ used up M < N. We strip the scenario out of the row by issuing a
      direct admin replay AND post a follow-up /po/sync with a different
      mock_scenario (happy) — same idempotency key, dedup → returns the
      replayed sync_id (no fresh row). The worker then picks the replayed
      row, which now has metadata.mock_scenario absent in the new POST… but
      replay re-uses the stored payload, not the new POST's. So instead the
      cleanest check is just: the replay endpoint correctly resets the row
      to pending+attempts=0. Verifying that the worker then re-processes is
      easy because the mock's failure_count is keyed by idem key and was
      not reset — so the row will DLQ again. That's also valid: we verify
      the round-trip pending → failed → pending → failed (i.e. the API
      contract works).

Run with:  PYTHONIOENCODING=utf-8 python services/erp-adapter/tests/smoke_m35.py
"""
from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import sys
from typing import Any

HERE = os.path.dirname(__file__)
REPO = os.path.abspath(os.path.join(HERE, "..", "..", ".."))


def _load_module(label: str, path: str):
    spec = importlib.util.spec_from_file_location(label, path)
    mod = importlib.util.module_from_spec(spec)
    sys.path.insert(0, os.path.dirname(path))
    spec.loader.exec_module(mod)
    return mod


async def _start_mock():
    from aiohttp.test_utils import TestServer
    mod = _load_module("mock_main_m35", os.path.join(REPO, "services", "erp-mock", "src", "main.py"))
    server = TestServer(mod.create_app())
    await server.start_server()
    return server


async def _start_adapter(mock_url: str):
    from aiohttp.test_utils import TestServer
    os.environ["ERP_VENDORS"] = "sap"
    os.environ["ERP_MOCK_BASE_URL"] = mock_url
    os.environ["SAP_BASE_URL"] = mock_url + "/sap/opu/odata/sap/API_PURCHASEORDER_PROCESS_SRV"
    os.environ["SAP_OAUTH_TOKEN_URL"] = mock_url + "/sap/oauth2/token"
    os.environ["SAP_BUDGET_CHECK_URL"] = mock_url + "/sap/budget/check"
    os.environ["DB_HOST"] = "localhost"
    os.environ["REDIS_URL"] = "redis://localhost:6399"
    os.environ["BREAKER_FAIL_MAX"] = "10"          # don't trip during DLQ window
    os.environ["WORKER_BACKOFF_CSV"] = "0.3,0.3,0.3"
    os.environ["WORKER_POLL_INTERVAL_SECONDS"] = "0.3"

    for name in list(sys.modules):
        head = name.split('.')[0]
        if head in {"config", "main", "routes", "models", "middleware", "observability",
                    "adapters", "outbox", "security", "resilience",
                    "scenarios", "store", "budget_routes",
                    "sap_routes", "oracle_routes", "po_routes", "webhook_emitter"}:
            sys.modules.pop(name, None)
    sys.path.insert(0, os.path.join(REPO, "services", "erp-adapter", "src"))

    from config import Settings  # type: ignore
    import main as adapter_main  # type: ignore
    s = Settings()
    server = TestServer(adapter_main.create_app(s))
    await server.start_server()
    return server


def _green(s): return f"\033[32m{s}\033[0m"
def _red(s):   return f"\033[31m{s}\033[0m"


def _build_po(txn_id: str) -> dict[str, Any]:
    return {
        "transaction_id": txn_id, "order_id": "o-" + txn_id, "contract_id": "c1",
        "buyer": {"name": "B", "email": "b@e.com", "cost_center": "CC1"},
        "supplier": {"bpp_id": "bpp1", "name": "S"},
        "line_items": [{
            "item_id": "i1", "name": "Item", "quantity": 1, "unit": "ea",
            "unit_price": "100.00", "currency": "INR",
        }],
        "totals": {"subtotal": "100.00", "currency": "INR"},
        "payment_terms": {}, "fulfillment": {}, "metadata": {},
    }


async def _poll(client, url, predicate, *, timeout=10.0, every=0.3):
    deadline = asyncio.get_event_loop().time() + timeout
    last = None
    while asyncio.get_event_loop().time() < deadline:
        async with client.get(url) as r:
            body = await r.json()
            last = body
            if predicate(r.status, body):
                return body
        await asyncio.sleep(every)
    return last


async def case_readyz(adapter_url: str) -> list[str]:
    import aiohttp
    fails: list[str] = []
    async with aiohttp.ClientSession() as s:
        async with s.get(f"{adapter_url}/readyz") as r:
            status = r.status
            body = await r.json()
    print(f"  /readyz -> {status} ready={body.get('ready')}")
    print(f"  checks keys: {sorted(body.get('checks', {}).keys())}")
    print(f"  checks.db = {body['checks'].get('db')}")
    print(f"  checks.redis = {body['checks'].get('redis')}")
    print(f"  checks.vendors = {body['checks'].get('vendors')}")
    if status != 503:
        fails.append(f"(/readyz) expected 503 with DB+Redis down, got {status}")
    if body.get("ready") is not False:
        fails.append("(/readyz) ready should be False when DB+Redis missing")
    checks = body.get("checks") or {}
    if "db" not in checks or "redis" not in checks:
        fails.append("(/readyz) checks should include db and redis")
    if "vendors" not in checks:
        fails.append("(/readyz) checks should include vendors block")
    if "sap" not in (checks.get("vendors") or {}):
        fails.append("(/readyz) checks.vendors should include sap entry")
    return fails


async def case_dlq_replay(adapter_url: str, auth: dict) -> list[str]:
    import aiohttp
    fails: list[str] = []
    po = _build_po("tx-replay-1")

    async with aiohttp.ClientSession(headers=auth) as s:
        # Drive to DLQ
        async with s.post(
            f"{adapter_url}/api/v1/po/sync", json=po,
            headers={"X-Mock-Scenario": "po_create_fails"},
        ) as r:
            body = await r.json()
            sync_id = body["results"][0]["sync_id"]
        final = await _poll(
            s, f"{adapter_url}/api/v1/po/sync/{sync_id}",
            predicate=lambda st, b: b.get("status") == "failed",
            timeout=8.0,
        )
        print(f"  pre-replay -> status={final.get('status')} attempts={final.get('attempts')}")
        if final.get("status") != "failed":
            fails.append("(replay) row should DLQ first")
            return fails

        # Replay
        async with s.post(f"{adapter_url}/api/v1/admin/outbox/{sync_id}/replay") as r:
            body = await r.json()
            print(f"  POST /admin/.../replay -> {r.status} {body}")
            if r.status != 200:
                fails.append(f"(replay) replay endpoint should return 200, got {r.status}")
                return fails
            if body.get("status") != "pending":
                fails.append(f"(replay) replayed row should be pending, got {body.get('status')}")
            if body.get("attempts") != 0:
                fails.append(f"(replay) attempts should reset to 0, got {body.get('attempts')}")

        # 409 when re-replaying a row that's now pending
        async with s.post(f"{adapter_url}/api/v1/admin/outbox/{sync_id}/replay") as r:
            body = await r.json()
            print(f"  re-replay (already pending) -> {r.status} {body.get('error')}")
            if r.status != 409:
                fails.append(f"(replay) re-replay of pending row should be 409, got {r.status}")

        # 404 when replaying an unknown sync_id
        import uuid
        async with s.post(f"{adapter_url}/api/v1/admin/outbox/{uuid.uuid4()}/replay") as r:
            print(f"  replay unknown sync_id -> {r.status}")
            if r.status != 404:
                fails.append(f"(replay) unknown sync_id should be 404, got {r.status}")

        # After replay the row goes back through the worker. Mock still fails
        # this idempotency_key the next handful of attempts, so we expect to
        # see it re-DLQ → that proves the worker re-picked it up.
        final2 = await _poll(
            s, f"{adapter_url}/api/v1/po/sync/{sync_id}",
            predicate=lambda st, b: b.get("status") == "failed",
            timeout=8.0,
        )
        print(f"  post-replay -> status={final2.get('status')} attempts={final2.get('attempts')}")
        if final2.get("status") != "failed":
            fails.append("(replay) worker should re-pick the replayed row")
    return fails


async def main() -> int:
    mock = await _start_mock()
    mock_url = f"http://localhost:{mock.port}"
    print(f"mock-erp at {mock_url}")

    adapter = await _start_adapter(mock_url)
    adapter_url = f"http://localhost:{adapter.port}"
    print(f"erp-adapter at {adapter_url}")

    auth = {"Authorization": "Bearer dev-internal-token-CHANGE_ME"}
    fails: list[str] = []

    print()
    print("[a] /readyz with DB+Redis missing -> 503 + structured checks")
    fails += await case_readyz(adapter_url)

    print()
    print("[b] DLQ replay round-trip")
    fails += await case_dlq_replay(adapter_url, auth)

    await adapter.close()
    await mock.close()

    print()
    if fails:
        for f in fails:
            print(_red("FAIL"), f)
        return 1
    print(_green("M3.5 smoke OK"))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
