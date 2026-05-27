"""ERPAdapter Protocol + vendor exception tree.

Concrete adapters (mock.py, sap.py, oracle.py, fanout.py) all conform to this
Protocol. The exception tree lets the outbox worker distinguish "retry later"
(VendorTransientError) from "give up now" (VendorPermanentError).
"""
from __future__ import annotations

from typing import ClassVar, Protocol, runtime_checkable

from models import (
    BudgetCheckRequest,
    BudgetCheckResult,
    InboundStatus,
    NormalizedPO,
    PushResult,
)


# ── Exception tree ────────────────────────────────────────────────────────────

class VendorError(Exception):
    """Base class for any error originating from a vendor adapter."""


class VendorTransientError(VendorError):
    """Retryable failure — timeout, 5xx, 429, network blip.

    Outbox worker reschedules with exponential backoff up to MAX_ATTEMPTS.
    Budget-check tenacity profile retries this twice within the 800ms budget.
    """


class VendorPermanentError(VendorError):
    """Non-retryable failure — 4xx (other than 429), validation, unknown vendor.

    Outbox worker marks the row failed without scheduling further attempts.
    """


# ── Protocol ──────────────────────────────────────────────────────────────────

@runtime_checkable
class ERPAdapter(Protocol):
    """Vendor-neutral adapter contract."""

    vendor: ClassVar[str]

    async def check_budget(self, req: BudgetCheckRequest) -> BudgetCheckResult: ...

    async def push_po(self, po: NormalizedPO, idempotency_key: str) -> PushResult: ...

    async def cancel_po(self, erp_reference_id: str, reason: str) -> None: ...

    def normalize_inbound_status(self, payload: dict, headers: dict) -> InboundStatus: ...

    async def healthcheck(self) -> bool: ...
