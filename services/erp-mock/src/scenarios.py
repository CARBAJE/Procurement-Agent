"""Selectable behaviors for the mock ERP.

The active scenario is chosen by the `MOCK_SCENARIO` env or the per-request
`X-Mock-Scenario` header. Each scenario describes how the SAP and Oracle
surfaces, the budget endpoint, and the webhook emitter should behave so the
adapter's resilience / error paths can be exercised deterministically.
"""
from __future__ import annotations

from dataclasses import dataclass

SCENARIO_HEADER = "X-Mock-Scenario"


@dataclass(frozen=True)
class Scenario:
    name: str
    budget_allowed: bool
    available_balance: float
    po_create_failures_before_success: int
    webhook_delay_seconds: float | None  # None = use default
    # Policy evaluation fields (read by /mock/policy/evaluate)
    policy_approval_required: bool = False
    policy_auto_commit_allowed: bool = True
    policy_preferred_supplier_ids: tuple[str, ...] = ()


HAPPY             = Scenario("happy",             True,  250_000.0, 0,  None)
BUDGET_EXHAUSTED  = Scenario("budget_exhausted",  False,       0.0, 0,  None)
PO_CREATE_FAILS   = Scenario("po_create_fails",   True,  250_000.0, 10, None)
WEBHOOK_DELAYED   = Scenario("webhook_delayed",   True,  250_000.0, 0,  30.0)

# Policy-specific scenarios for testing the PolicyEngine ERP integration paths.
ERP_APPROVAL_REQUIRED = Scenario(
    "erp_approval_required", True, 250_000.0, 0, None,
    policy_approval_required=True,
    policy_auto_commit_allowed=False,
)
ERP_PREFERRED_SUPPLIER = Scenario(
    "erp_preferred_supplier", True, 250_000.0, 0, None,
    policy_preferred_supplier_ids=("preferred-bpp-001",),
)

_REGISTRY: dict[str, Scenario] = {
    s.name: s
    for s in (
        HAPPY, BUDGET_EXHAUSTED, PO_CREATE_FAILS, WEBHOOK_DELAYED,
        ERP_APPROVAL_REQUIRED, ERP_PREFERRED_SUPPLIER,
    )
}


def resolve(default: str, header_value: str | None) -> Scenario:
    name = (header_value or default or "happy").strip()
    return _REGISTRY.get(name, HAPPY)
