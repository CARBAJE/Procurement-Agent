"""M3.1 smoke test — runs entirely in-process with aiohttp test servers.

Wires:
  erp-mock  ->  erp-adapter  ->  orchestrator ErpAdapterClient

Verifies four cases against the live wire:
  (a) happy:            adapter /api/v1/budget/check returns 200 allowed=True
  (b) budget_exhausted: returns 200 allowed=False with reasons[]
  (c) missing bearer:   returns 401
  (d) orchestrator client receives the same outcomes via its wrapper

Run with:  python services/erp-adapter/tests/smoke_m31.py
"""
from __future__ import annotations

import asyncio
import os
import sys
from decimal import Decimal

HERE = os.path.dirname(__file__)
REPO = os.path.abspath(os.path.join(HERE, "..", "..", ".."))

# Make adapter src importable
sys.path.insert(0, os.path.join(REPO, "services", "erp-adapter", "src"))
# Make mock src importable (needs to be importable BEFORE adapter to avoid name clash on 'main')
# So we'll import the mock factory lazily under a different module name.

from aiohttp import web
from aiohttp.test_utils import TestServer
import aiohttp


async def _start_mock_server() -> TestServer:
    """Build and start the erp-mock app on a random port."""
    import importlib.util
    mock_main_path = os.path.join(REPO, "services", "erp-mock", "src", "main.py")
    spec = importlib.util.spec_from_file_location("mock_main_module", mock_main_path)
    mock_mod = importlib.util.module_from_spec(spec)
    # Make sibling files findable from within mock_main_module
    sys.path.insert(0, os.path.dirname(mock_main_path))
    spec.loader.exec_module(mock_mod)
    app = mock_mod.create_app()
    server = TestServer(app)
    await server.start_server()
    return server


async def _start_adapter_server(mock_url: str, scenario: str = "happy") -> TestServer:
    """Build and start the erp-adapter pointed at the mock URL."""
    os.environ["ERP_MOCK_BASE_URL"] = mock_url
    os.environ["MOCK_SCENARIO"] = scenario  # passed through if adapter ever reads it
    os.environ["DB_HOST"] = "localhost"     # readyz will fail; we don't test that here
    os.environ["REDIS_URL"] = "redis://localhost:6399"  # intentionally bogus

    # Clear cached adapter modules from the mock import
    for m in list(sys.modules):
        if m.split('.')[0] in {"config", "main", "routes", "models", "middleware", "observability", "adapters"}:
            sys.modules.pop(m, None)

    from config import Settings  # type: ignore
    import main as adapter_main  # type: ignore

    settings = Settings()  # picks up ERP_MOCK_BASE_URL etc.
    app = adapter_main.create_app(settings)
    server = TestServer(app)
    await server.start_server()
    return server


def _green(s: str) -> str: return f"\033[32m{s}\033[0m"
def _red(s: str) -> str:   return f"\033[31m{s}\033[0m"


async def main() -> int:
    failures: list[str] = []

    # 1. Start the mock
    mock = await _start_mock_server()
    mock_url = f"http://localhost:{mock.port}"
    print(f"mock-erp listening on {mock_url}")

    # Probe /health
    async with aiohttp.ClientSession() as s:
        async with s.get(f"{mock_url}/health") as r:
            print("  GET /health ->", await r.json())

    # Probe /mock/budget/check (happy)
    payload = {
        "transaction_id": "tx-happy-1",
        "cost_center": "CC-IND-PROC-01",
        "requested_amount": "12500.00",
    }
    async with aiohttp.ClientSession() as s:
        async with s.post(f"{mock_url}/mock/budget/check", json=payload) as r:
            body = await r.json()
            print("  POST /mock/budget/check (happy) ->", r.status, body)
            if not (r.status == 200 and body["allowed"] is True):
                failures.append("(0) mock happy budget should be allowed")

    # Probe /mock/budget/check (budget_exhausted via header)
    async with aiohttp.ClientSession() as s:
        async with s.post(f"{mock_url}/mock/budget/check", json=payload,
                          headers={"X-Mock-Scenario": "budget_exhausted"}) as r:
            body = await r.json()
            print("  POST /mock/budget/check (budget_exhausted) ->", r.status, body)
            if body["allowed"] is not False:
                failures.append("(0) mock budget_exhausted should be denied")

    # 2. Start the adapter pointed at the mock
    sys.path.insert(0, os.path.join(REPO, "services", "erp-adapter", "src"))
    adapter = await _start_adapter_server(mock_url)
    adapter_url = f"http://localhost:{adapter.port}"
    print(f"erp-adapter listening on {adapter_url}")

    # Probe /healthz
    async with aiohttp.ClientSession() as s:
        async with s.get(f"{adapter_url}/healthz") as r:
            print("  GET /healthz ->", await r.json())

    # 3. Bearer-token gate must reject unauthenticated /api/v1/*
    async with aiohttp.ClientSession() as s:
        async with s.post(f"{adapter_url}/api/v1/budget/check", json=payload) as r:
            body = await r.json()
            print("  POST /budget/check (no auth) ->", r.status, body)
            if r.status != 401:
                failures.append("(a) missing bearer should return 401")

    auth = {"Authorization": "Bearer dev-internal-token-CHANGE_ME"}

    # 4. Happy path through adapter (mock returns allowed=True)
    async with aiohttp.ClientSession(headers=auth) as s:
        async with s.post(f"{adapter_url}/api/v1/budget/check", json=payload) as r:
            body = await r.json()
            print("  POST /budget/check (happy) ->", r.status, body)
            if not (r.status == 200 and body.get("allowed") is True and body.get("hold_id")):
                failures.append("(b) happy budget check should allow + return hold_id")

    # 5. budget_exhausted via header — adapter passes it through to mock
    async with aiohttp.ClientSession(headers={**auth, "X-Mock-Scenario": "budget_exhausted"}) as s:
        async with s.post(f"{adapter_url}/api/v1/budget/check", json=payload) as r:
            body = await r.json()
            print("  POST /budget/check (budget_exhausted) ->", r.status, body)
            if not (r.status == 200 and body.get("allowed") is False
                    and "INSUFFICIENT_FUNDS" in (body.get("reasons") or [])):
                failures.append("(c) budget_exhausted should be denied with reason")

    # 6. Orchestrator-side client end-to-end
    sys.path.insert(0, os.path.join(REPO, "services", "orchestrator", "src"))
    # Drop adapter's modules that overlap names
    for m in list(sys.modules):
        if m.split('.')[0] in {"client", "erp"}:
            sys.modules.pop(m, None)
    from erp import BudgetCheckRequest, ErpAdapterClient  # type: ignore

    client = ErpAdapterClient(
        base_url=adapter_url,
        internal_token="dev-internal-token-CHANGE_ME",
        timeout_ms=2000,
        budget_check_required=False,
    )
    req = BudgetCheckRequest(
        transaction_id="tx-orch-1",
        cost_center="CC-IND-PROC-01",
        requested_amount=Decimal("99000.00"),
    )
    res = await client.budget_check(req)
    print("  orch.budget_check (happy) ->", res)
    if not (res.allowed and res.hold_id):
        failures.append("(d) orchestrator client happy should allow")

    # Same with bad bearer -> fail-open under required=False
    bad_client = ErpAdapterClient(
        base_url=adapter_url,
        internal_token="WRONG",
        timeout_ms=2000,
        budget_check_required=False,
    )
    res = await bad_client.budget_check(req)
    print("  orch.budget_check (bad token, required=False) ->", res)
    if not (res.allowed and res.fallback):
        failures.append("(e) orchestrator client should fail-open when token wrong + required=False")

    # required=True -> propagates
    strict_client = ErpAdapterClient(
        base_url=adapter_url,
        internal_token="WRONG",
        timeout_ms=2000,
        budget_check_required=True,
    )
    try:
        await strict_client.budget_check(req)
        failures.append("(f) orchestrator strict client should have raised")
    except Exception as exc:
        print("  orch.budget_check (bad token, required=True) -> raised:", type(exc).__name__)

    # Teardown
    await adapter.close()
    await mock.close()

    # Report
    print()
    if failures:
        for f in failures:
            print(_red("FAIL"), f)
        return 1
    print(_green("M3.1 smoke OK"))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
