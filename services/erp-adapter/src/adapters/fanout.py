"""Multi-vendor fan-out adapter — used when ERP_VENDORS lists more than one vendor.

- check_budget: gather across vendors, AND-combine `allowed`. Reasons are
  concatenated; available_balance reports the minimum across vendors.
- push_po: M3.2 will fan out by writing one outbox row per vendor.
- normalize_inbound_status: route by `X-Vendor` header (set by the webhook handler).
"""
from __future__ import annotations

import asyncio
from decimal import Decimal
from typing import ClassVar, Sequence

from adapters.base import ERPAdapter
from models import (
    BudgetCheckRequest,
    BudgetCheckResult,
    InboundStatus,
    NormalizedPO,
    PushResult,
)


class MultiVendorAdapter(ERPAdapter):
    vendor: ClassVar[str] = "multi"

    def __init__(self, adapters: Sequence[ERPAdapter]) -> None:
        if not adapters:
            raise ValueError("MultiVendorAdapter requires at least one adapter")
        self._adapters = list(adapters)

    def for_vendor(self, vendor: str) -> ERPAdapter | None:
        """Return the per-vendor adapter inside the fan-out, or None.
        The outbox worker uses this to route a row to its specific vendor
        child instead of going through the Multi (which lacks PO push semantics
        when multiple destinations would mean implicit double-push)."""
        for a in self._adapters:
            if a.vendor == vendor:
                return a
        return None

    async def check_budget(self, req: BudgetCheckRequest) -> BudgetCheckResult:
        results = await asyncio.gather(
            *(a.check_budget(req) for a in self._adapters),
            return_exceptions=True,
        )

        balances: list[Decimal] = []
        reasons: list[str] = []
        allowed = True
        for a, r in zip(self._adapters, results):
            if isinstance(r, Exception):
                allowed = False
                reasons.append(f"{a.vendor}: {r}")
                continue
            if not r.allowed:
                allowed = False
                reasons.extend(f"{a.vendor}: {x}" for x in r.reasons)
            if r.available_balance is not None:
                balances.append(r.available_balance)

        return BudgetCheckResult(
            allowed=allowed,
            available_balance=min(balances) if balances else None,
            reasons=reasons,
            vendor=",".join(a.vendor for a in self._adapters),
        )

    async def push_po(self, po: NormalizedPO, idempotency_key: str) -> PushResult:
        # In M3.2 the outbox writes one row per vendor — the worker calls each
        # adapter directly. This method exists only for direct callers that
        # bypass the outbox; raise so we don't get silent fan-out behavior.
        raise NotImplementedError("MultiVendorAdapter.push_po — use per-vendor outbox rows in M3.2")

    async def cancel_po(self, erp_reference_id: str, reason: str) -> None:
        raise NotImplementedError("MultiVendorAdapter.cancel_po — route via outbox in M3.4")

    def normalize_inbound_status(self, payload: dict, headers: dict) -> InboundStatus:
        vendor = headers.get("X-Vendor", "")
        for a in self._adapters:
            if a.vendor == vendor:
                return a.normalize_inbound_status(payload, headers)
        raise ValueError(f"unknown vendor for inbound webhook: {vendor!r}")

    async def healthcheck(self) -> bool:
        results = await asyncio.gather(*(a.healthcheck() for a in self._adapters))
        return any(results)
