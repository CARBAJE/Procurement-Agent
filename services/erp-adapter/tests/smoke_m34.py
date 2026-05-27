"""M3.4 smoke — real SAP + Oracle adapters + circuit breaker + fan-out.

Cases:
  (a) ERP_VENDORS=sap pointed at erp-mock:
      - happy /api/v1/budget/check (vendor-shaped /sap/budget/check) → allowed
      - happy /api/v1/po/sync → outbox row reaches success with a SAP PO number
        (format "45000XXXXXXX"); demonstrates OAuth + CSRF dance.
      - DLQ on po_create_fails: row ends in 'failed' after configured retries.
  (b) ERP_VENDORS=sap,oracle (fan-out):
      - /api/v1/po/sync produces TWO outbox rows (one per vendor)
      - both reach 'success', each with a vendor-shaped reference id.
  (c) Circuit breaker opens:
      - BREAKER_FAIL_MAX=2, po_create_fails scenario, MAX_ATTEMPTS=3
      - After 2 transient failures the breaker opens → next worker attempt
        short-circuits → DLQ reached with reason 'circuit_open'.
      - GET /metrics shows erp_circuit_state{vendor="sap"} == 2 (OPEN).

Run with:  PYTHONIOENCODING=utf-8 python services/erp-adapter/tests/smoke_m34.py
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
    mod = _load_module("mock_main_m34", os.path.join(REPO, "services", "erp-mock", "src", "main.py"))
    server = TestServer(mod.create_app())
    await server.start_server()
    return server


def _adapter_env(mock_url: str, vendors: str, *,
                 fail_max: int = 5, max_attempts: int = 3):
    """Mutate process env to control the adapter we're about to (re)start."""
    os.environ["ERP_VENDORS"] = vendors
    os.environ["ERP_MOCK_BASE_URL"] = mock_url
    os.environ["SAP_BASE_URL"] = mock_url + "/sap/opu/odata/sap/API_PURCHASEORDER_PROCESS_SRV"
    os.environ["SAP_OAUTH_TOKEN_URL"] = mock_url + "/sap/oauth2/token"
    os.environ["SAP_BUDGET_CHECK_URL"] = mock_url + "/sap/budget/check"
    os.environ["ORACLE_BASE_URL"] = mock_url + "/fscmRestApi/resources/11.13.18.05"
    os.environ["ORACLE_OAUTH_TOKEN_URL"] = mock_url + "/oauth2/v1/token"
    os.environ["ORACLE_BUDGET_CHECK_URL"] = mock_url + "/oracle/budget/check"
    os.environ["DB_HOST"] = "localhost"
    os.environ["REDIS_URL"] = "redis://localhost:6399"
    os.environ["BREAKER_FAIL_MAX"] = str(fail_max)
    os.environ["BREAKER_RESET_TIMEOUT_SECS"] = "60"
    os.environ["WORKER_BACKOFF_CSV"] = ",".join(["0.4"] * max_attempts)
    os.environ["WORKER_POLL_INTERVAL_SECONDS"] = "0.3"


async def _start_adapter() -> "Any":
    from aiohttp.test_utils import TestServer
    # Reset module cache so Settings picks up the new env
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


def _build_po(txn_id: str, order_id: str = "order-1") -> dict[str, Any]:
    return {
        "transaction_id": txn_id, "order_id": order_id, "contract_id": "c1",
        "buyer": {"name": "Buyer", "email": "b@e.com", "cost_center": "CC1"},
        "supplier": {"bpp_id": "bpp1", "name": "Supplier"},
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


# ── Cases ────────────────────────────────────────────────────────────────────

async def case_sap_happy(adapter_url: str, auth: dict) -> list[str]:
    import aiohttp
    fails: list[str] = []

    # Budget check via SAP-shaped endpoint
    async with aiohttp.ClientSession(headers=auth) as s:
        async with s.post(
            f"{adapter_url}/api/v1/budget/check",
            json={"transaction_id": "tx-sap-bud", "cost_center": "CC1",
                  "requested_amount": "100.00", "currency": "INR"},
        ) as r:
            body = await r.json()
            print(f"  [sap] budget -> {r.status} allowed={body.get('allowed')}")
            if r.status != 200 or not body.get("allowed"):
                fails.append("(sap) budget should be allowed")

    # PO sync via SAP push (OAuth + CSRF + OData POST)
    async with aiohttp.ClientSession(headers=auth) as s:
        po = _build_po("tx-sap-1", "order-sap-1")
        async with s.post(f"{adapter_url}/api/v1/po/sync", json=po) as r:
            body = await r.json()
            sync_id = body["results"][0]["sync_id"]
            print(f"  [sap] /po/sync -> {r.status} sync_id={sync_id}")
        final = await _poll(
            s, f"{adapter_url}/api/v1/po/sync/{sync_id}",
            predicate=lambda st, b: b.get("status") in ("success", "failed"),
            timeout=8.0,
        )
        print(f"  [sap] outbox final -> status={final.get('status')} erp_ref={final.get('erp_reference_id')}")
        if final.get("status") != "success":
            fails.append("(sap) push should reach success")
        elif not (final.get("erp_reference_id", "").startswith("4500")):
            fails.append(f"(sap) erp_reference_id should look like a SAP PO number, got {final.get('erp_reference_id')}")
    return fails


async def case_sap_dlq(adapter_url: str, auth: dict) -> list[str]:
    import aiohttp
    fails: list[str] = []
    async with aiohttp.ClientSession(headers=auth) as s:
        po = _build_po("tx-sap-dlq", "order-sap-dlq")
        async with s.post(
            f"{adapter_url}/api/v1/po/sync", json=po,
            headers={"X-Mock-Scenario": "po_create_fails"},
        ) as r:
            body = await r.json()
            sync_id = body["results"][0]["sync_id"]
            print(f"  [sap] DLQ enqueue -> {r.status} sync_id={sync_id}")
        final = await _poll(
            s, f"{adapter_url}/api/v1/po/sync/{sync_id}",
            predicate=lambda st, b: b.get("status") == "failed",
            timeout=10.0,
        )
        print(f"  [sap] DLQ final -> status={final.get('status')} attempts={final.get('attempts')} err={(final.get('last_error') or '')[:60]}")
        if final.get("status") != "failed":
            fails.append("(sap-dlq) row should end in failed")
    return fails


async def case_fanout(adapter_url: str, auth: dict) -> list[str]:
    import aiohttp
    fails: list[str] = []
    async with aiohttp.ClientSession(headers=auth) as s:
        po = _build_po("tx-fanout-1", "order-fanout-1")
        async with s.post(f"{adapter_url}/api/v1/po/sync", json=po) as r:
            body = await r.json()
            results = body.get("results", [])
            vendors = sorted(r["vendor"] for r in results)
            print(f"  [fanout] /po/sync -> {r.status} vendors={vendors}")
            if vendors != ["oracle", "sap"]:
                fails.append(f"(fanout) expected vendors=['oracle','sap'], got {vendors}")

        for entry in results:
            sync_id = entry["sync_id"]
            vendor = entry["vendor"]
            final = await _poll(
                s, f"{adapter_url}/api/v1/po/sync/{sync_id}",
                predicate=lambda st, b: b.get("status") in ("success", "failed"),
                timeout=8.0,
            )
            print(f"  [fanout] {vendor} -> status={final.get('status')} erp_ref={final.get('erp_reference_id')}")
            if final.get("status") != "success":
                fails.append(f"(fanout) {vendor} should reach success")
    return fails


async def case_circuit_open(adapter_url: str, auth: dict) -> list[str]:
    """With BREAKER_FAIL_MAX=2 and po_create_fails scenario, the 1st and 2nd
    push attempts fail transiently → breaker opens after the 2nd. The 3rd
    worker attempt short-circuits with CircuitOpenError → DLQ. /metrics
    shows the SAP circuit gauge transition to 2 (OPEN)."""
    import aiohttp
    fails: list[str] = []
    async with aiohttp.ClientSession(headers=auth) as s:
        po = _build_po("tx-sap-circuit", "order-sap-circuit")
        async with s.post(
            f"{adapter_url}/api/v1/po/sync", json=po,
            headers={"X-Mock-Scenario": "po_create_fails"},
        ) as r:
            body = await r.json()
            sync_id = body["results"][0]["sync_id"]
            print(f"  [circuit] enqueue -> {r.status} sync_id={sync_id}")

        final = await _poll(
            s, f"{adapter_url}/api/v1/po/sync/{sync_id}",
            predicate=lambda st, b: b.get("status") == "failed",
            timeout=10.0,
        )
        print(f"  [circuit] outbox final -> status={final.get('status')} err={(final.get('last_error') or '')[:80]}")
        if final.get("status") != "failed":
            fails.append("(circuit) row should DLQ")

        # Check the circuit gauge — should be OPEN (2.0) after the breaker tripped
        async with s.get(f"{adapter_url}/metrics") as r:
            text = await r.text()
        match = [ln for ln in text.splitlines() if ln.startswith("erp_circuit_state{") and 'vendor="sap"' in ln]
        gauge_value = float(match[0].split()[-1]) if match else -1
        print(f"  [circuit] erp_circuit_state{{vendor=sap}} -> {gauge_value}")
        if gauge_value != 2.0:
            fails.append(f"(circuit) gauge should be 2.0 (OPEN), got {gauge_value}")
    return fails


# ── Main ─────────────────────────────────────────────────────────────────────

async def main() -> int:
    mock = await _start_mock()
    mock_url = f"http://localhost:{mock.port}"
    print(f"mock-erp at {mock_url}")
    os.environ["WEBHOOK_TARGET_URL"] = "http://localhost:0"  # silence webhook noise

    fails: list[str] = []

    # ── (a) Single-vendor SAP happy + DLQ ────────────────────────────────────
    print()
    print("[a] ERP_VENDORS=sap: happy + DLQ")
    _adapter_env(mock_url, "sap", fail_max=5, max_attempts=3)
    adapter = await _start_adapter()
    adapter_url = f"http://localhost:{adapter.port}"
    auth = {"Authorization": "Bearer dev-internal-token-CHANGE_ME"}
    fails += await case_sap_happy(adapter_url, auth)
    fails += await case_sap_dlq(adapter_url, auth)
    await adapter.close()

    # ── (b) Multi-vendor fan-out ─────────────────────────────────────────────
    print()
    print("[b] ERP_VENDORS=sap,oracle: fan-out happy")
    _adapter_env(mock_url, "sap,oracle", fail_max=5, max_attempts=3)
    adapter = await _start_adapter()
    adapter_url = f"http://localhost:{adapter.port}"
    fails += await case_fanout(adapter_url, auth)
    await adapter.close()

    # ── (c) Circuit breaker opens ────────────────────────────────────────────
    print()
    print("[c] BREAKER_FAIL_MAX=2 + po_create_fails: circuit opens")
    _adapter_env(mock_url, "sap", fail_max=2, max_attempts=3)
    adapter = await _start_adapter()
    adapter_url = f"http://localhost:{adapter.port}"
    fails += await case_circuit_open(adapter_url, auth)
    await adapter.close()

    await mock.close()

    print()
    if fails:
        for f in fails:
            print(_red("FAIL"), f)
        return 1
    print(_green("M3.4 smoke OK"))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
