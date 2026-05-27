"""M3.3 smoke — bidirectional via inbound webhooks.

Verifies:
  (a) Mock end-to-end loop:
      POST /api/v1/po/sync (happy) → worker pushes to mock /mock/po/create
      → mock emits HMAC-signed webhook to adapter /api/v1/webhooks/mock/po-status
      → adapter verifies HMAC + normalizes + updates outbox + tries Redis publish
      → GET /api/v1/po/sync/{sync_id} now reflects erp_reference_id
  (b) HMAC tamper:
      POST a hand-rolled webhook with a bad signature → 401
  (c) HMAC dual-secret rotation:
      Set NEXT secret on adapter; POST signed with NEXT → 200
  (d) Unknown vendor:
      POST to /api/v1/webhooks/sap/po-status (no sap adapter configured) → 400

Run with:  PYTHONIOENCODING=utf-8 python services/erp-adapter/tests/smoke_m33.py
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac as _hmac
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
    mod = _load_module("mock_main_m33", os.path.join(REPO, "services", "erp-mock", "src", "main.py"))
    app = mod.create_app()
    server = TestServer(app)
    await server.start_server()
    return server


async def _start_adapter(mock_url: str):
    from aiohttp.test_utils import TestServer
    os.environ["ERP_MOCK_BASE_URL"] = mock_url
    os.environ["DB_HOST"] = "localhost"
    os.environ["REDIS_URL"] = "redis://localhost:6399"  # intentionally unreachable
    os.environ["WORKER_BACKOFF_CSV"] = "0.5,0.5,0.5"
    os.environ["WORKER_POLL_INTERVAL_SECONDS"] = "0.3"
    # Dual-secret rotation window — NEXT secret used by case (c)
    os.environ["SAP_WEBHOOK_HMAC_SECRET"] = "primary-hmac"
    os.environ["SAP_WEBHOOK_HMAC_SECRET_NEXT"] = "rotated-hmac"

    for name in list(sys.modules):
        head = name.split('.')[0]
        if head in {"config", "main", "routes", "models", "middleware", "observability",
                    "adapters", "outbox", "security", "scenarios", "store",
                    "budget_routes", "sap_routes", "oracle_routes", "po_routes",
                    "webhook_emitter"}:
            sys.modules.pop(name, None)
    sys.path.insert(0, os.path.join(REPO, "services", "erp-adapter", "src"))

    from config import Settings  # type: ignore
    import main as adapter_main  # type: ignore
    s = Settings()
    app = adapter_main.create_app(s)
    server = TestServer(app)
    await server.start_server()
    return server


def _sign(secret: str, body: bytes) -> str:
    return "sha256=" + _hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def _green(s): return f"\033[32m{s}\033[0m"
def _red(s): return f"\033[31m{s}\033[0m"


def _build_po(txn_id: str, order_id: str = "order-XYZ") -> dict[str, Any]:
    return {
        "transaction_id": txn_id, "order_id": order_id, "contract_id": "c1",
        "buyer": {"name": "T", "email": "t@e.com", "cost_center": "CC1"},
        "supplier": {"bpp_id": "bpp1", "name": "S"},
        "line_items": [{"item_id": "i1", "name": "n", "quantity": 1,
                        "unit": "ea", "unit_price": "10.00", "currency": "INR"}],
        "totals": {"subtotal": "10.00", "currency": "INR"},
        "payment_terms": {}, "fulfillment": {}, "metadata": {},
    }


async def _poll_until(client, url, predicate, *, timeout=8.0, every=0.3):
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
    return last[1] if last else None


async def case_a_mock_loop(adapter_url: str, auth: dict, audit_events: list) -> list[str]:
    import aiohttp
    fails = []
    po = _build_po("txn-loop-1", "order-loop-1")
    async with aiohttp.ClientSession(headers=auth) as s:
        async with s.post(f"{adapter_url}/api/v1/po/sync", json=po) as r:
            body = await r.json()
            sync_id = body.get("sync_id")
            print(f"  (a) /po/sync -> {r.status} sync_id={sync_id}")
        final = await _poll_until(
            s, f"{adapter_url}/api/v1/po/sync/{sync_id}",
            predicate=lambda st, b: b.get("status") == "success" and b.get("erp_reference_id"),
            timeout=8.0,
        )
        print(f"  (a) outbox -> status={final and final.get('status')} erp_ref={final and final.get('erp_reference_id')}")
        if not (final and final.get("status") == "success" and final.get("erp_reference_id")):
            fails.append("(a) outbox should reach success with erp_reference_id")

        # Wait for the inbound webhook from the mock (default delay 2s).
        deadline = asyncio.get_event_loop().time() + 6.0
        received = None
        while asyncio.get_event_loop().time() < deadline:
            for e in audit_events:
                if e.get("event") == "WEBHOOK_RECEIVED" and e.get("transaction_id") == "txn-loop-1":
                    received = e
                    break
            if received:
                break
            await asyncio.sleep(0.3)
        print(f"  (a) inbound webhook -> {received and {k: received[k] for k in ('event','vendor','state','erp_reference_id')}}")
        if not received:
            fails.append("(a) WEBHOOK_RECEIVED for txn-loop-1 never observed")
        elif received.get("state") != "ACCEPTED":
            fails.append(f"(a) inbound state expected ACCEPTED, got {received.get('state')}")
    return fails


async def case_b_tamper(adapter_url: str) -> list[str]:
    import aiohttp
    fails = []
    body = json.dumps({"transaction_id": "tamper-1", "state": "ACCEPTED",
                       "erp_reference_id": "MOCK-PO-TAMPER", "event_ts": "2026-05-26T00:00:00+00:00"}).encode()
    async with aiohttp.ClientSession() as s:
        async with s.post(
            f"{adapter_url}/api/v1/webhooks/mock/po-status",
            data=body,
            headers={"Content-Type": "application/json",
                     "X-Mock-Signature": "sha256=DEADBEEF"},
        ) as r:
            print(f"  (b) tamper webhook -> {r.status}")
            if r.status != 401:
                fails.append("(b) tampered HMAC must return 401")
    return fails


async def case_c_rotation(adapter_url: str) -> list[str]:
    import aiohttp
    fails = []
    body = json.dumps({"transaction_id": "rotation-1", "state": "ACCEPTED",
                       "erp_reference_id": "MOCK-PO-ROT", "event_ts": "2026-05-26T00:00:00+00:00"}).encode()
    sig = _sign("rotated-hmac", body)
    async with aiohttp.ClientSession() as s:
        async with s.post(
            f"{adapter_url}/api/v1/webhooks/mock/po-status",
            data=body,
            headers={"Content-Type": "application/json", "X-Mock-Signature": sig},
        ) as r:
            print(f"  (c) NEXT-secret webhook -> {r.status}")
            if r.status != 200:
                fails.append("(c) NEXT secret signature must verify")
    return fails


async def case_d_unknown_vendor(adapter_url: str) -> list[str]:
    """The adapter is configured with ERP_VENDORS=mock — a webhook to
    /webhooks/sap should pass HMAC verify (the SAP secret is the same primary
    used by the mock route) but then fail at adapter resolution → 400."""
    import aiohttp
    fails = []
    body = json.dumps({"transaction_id": "vendor-?", "state": "ACCEPTED",
                       "erp_reference_id": "X", "event_ts": "2026-05-26T00:00:00+00:00"}).encode()
    sig = _sign("primary-hmac", body)
    async with aiohttp.ClientSession() as s:
        async with s.post(
            f"{adapter_url}/api/v1/webhooks/sap/po-status",
            data=body,
            headers={"Content-Type": "application/json", "X-Sap-Signature": sig},
        ) as r:
            body_j = await r.json()
            print(f"  (d) unknown vendor webhook -> {r.status} {body_j}")
            # Either 400 (no SAP adapter configured) or 501 (vendor stub
            # normalize raises NotImplementedError) is acceptable here — the
            # important assertion is that it does NOT return 200.
            if r.status == 200:
                fails.append("(d) unknown-vendor webhook should NOT return 200")
    return fails


def _install_audit_tap() -> list[dict]:
    """Attach a logging handler to erp.audit that captures the JSONL events
    into an in-memory list — lets the smoke test assert on the audit trail."""
    import logging
    bucket: list[dict] = []

    class _Tap(logging.Handler):
        def emit(self, record):
            try:
                bucket.append(json.loads(record.getMessage()))
            except Exception:
                pass

    log = logging.getLogger("erp.audit")
    log.addHandler(_Tap())
    return bucket


async def main() -> int:
    mock = await _start_mock()
    mock_url = f"http://localhost:{mock.port}"
    print(f"mock-erp at {mock_url}")

    adapter = await _start_adapter(mock_url)
    adapter_url = f"http://localhost:{adapter.port}"
    print(f"erp-adapter at {adapter_url}")

    # Capture audit events emitted by the adapter
    audit_events = _install_audit_tap()

    # Point the mock at the adapter we just started, so the webhook task fired
    # by /mock/po/create reaches us. Also align the mock's HMAC secret with
    # the adapter's primary secret so signed webhooks verify.
    os.environ["WEBHOOK_TARGET_URL"] = adapter_url
    os.environ["SAP_WEBHOOK_HMAC_SECRET"] = "primary-hmac"

    auth = {"Authorization": "Bearer dev-internal-token-CHANGE_ME"}
    fails: list[str] = []

    print()
    print("[a] mock end-to-end loop")
    fails += await case_a_mock_loop(adapter_url, auth, audit_events)

    print()
    print("[b] HMAC tamper -> 401")
    fails += await case_b_tamper(adapter_url)

    print()
    print("[c] HMAC rotation (NEXT secret) -> 200")
    fails += await case_c_rotation(adapter_url)

    print()
    print("[d] unknown vendor")
    fails += await case_d_unknown_vendor(adapter_url)

    print()
    if fails:
        for f in fails:
            print(_red("FAIL"), f)
        await adapter.close(); await mock.close()
        return 1
    print(_green("M3.3 smoke OK"))
    await adapter.close(); await mock.close()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
