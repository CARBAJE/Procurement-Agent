"""Mock policy evaluation endpoint consumed by MockERPAdapter.

Target: POST /mock/policy/evaluate
Caller: services/erp-adapter/src/adapters/mock.py::_evaluate_policy_impl()

Returns a PolicyEnvelope-shaped JSON dict driven by the active Scenario.
The active scenario is resolved from the MOCK_SCENARIO env var or the
per-request X-Mock-Scenario header — same precedence as budget_routes.py.
"""
from __future__ import annotations

from aiohttp import web

from scenarios import SCENARIO_HEADER, resolve


async def policy_evaluate(request: web.Request) -> web.Response:
    cfg = request.app["cfg"]
    scenario = resolve(cfg.scenario, request.headers.get(SCENARIO_HEADER))

    try:
        await request.json()  # consume body; validate it's parseable JSON
    except Exception:
        return web.json_response({"error": "bad_request", "detail": "invalid JSON"}, status=400)

    preferred = list(scenario.policy_preferred_supplier_ids)

    constraints: list[dict] = []
    if scenario.policy_approval_required:
        constraints.append({
            "kind":   "requires_approval",
            "source": "erp_policy",
            "note":   f"scenario {scenario.name!r} mandates approval",
        })
    if not scenario.policy_auto_commit_allowed:
        constraints.append({
            "kind":   "auto_commit_blocked",
            "source": "erp_policy",
            "note":   f"scenario {scenario.name!r} blocks auto-commit",
        })
    for sid in preferred:
        constraints.append({
            "kind":   "preferred_supplier",
            "value":  sid,
            "source": "erp_policy",
        })

    return web.json_response({
        "preferred_supplier_ids": preferred,
        "approval_required":      scenario.policy_approval_required,
        "auto_commit_allowed":    scenario.policy_auto_commit_allowed,
        "fallback":               False,
        "constraints":            constraints,
        "vendor":                 "mock",
    })


def register(app: web.Application) -> None:
    app.router.add_post("/mock/policy/evaluate", policy_evaluate)
