"""HTTP client used by services/orchestrator/src/workflow.py to call
services/erp-adapter.

Two surfaces are exposed:
  * `budget_check(...)` — synchronous gate on /commit's critical path. Honors
    ERP_BUDGET_CHECK_REQUIRED: when False (dev default), vendor unavailable
    returns a fallback `allowed=True` result; when True (prod), raises so the
    orchestrator surfaces an HTTP 503.
  * `enqueue_sync(...)` — fire-and-forget PO push (M3.2). Logs and swallows
    failures so it never blocks the commit response.

No Pydantic dependency on the orchestrator side; the adapter's Pydantic
validation is authoritative.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import asdict, dataclass, field
from decimal import Decimal
from typing import Any

import aiohttp

logger = logging.getLogger(__name__)


# ── Wire models (mirror services/erp-adapter/src/models.py) ──────────────────

@dataclass
class BudgetCheckRequest:
    transaction_id: str
    cost_center: str
    requested_amount: Decimal
    currency: str = "INR"
    category: str = "uncategorized"
    requester_id: str = "anonymous"

    def to_json(self) -> dict[str, Any]:
        return {
            "transaction_id": self.transaction_id,
            "cost_center": self.cost_center,
            "requested_amount": str(self.requested_amount),
            "currency": self.currency,
            "category": self.category,
            "requester_id": self.requester_id,
        }


@dataclass
class PolicyEvaluateRequest:
    """Input for POST /api/v1/policy/evaluate.

    Mirrors services/erp-adapter/src/models.py::PolicyEvaluateRequest — keep
    field names identical on both sides.
    """
    transaction_id: str
    cost_center: str
    order_total: Decimal
    currency: str = "INR"
    category: str = "uncategorized"
    requester_id: str = "anonymous"
    item_ids: list[str] = field(default_factory=list)
    provider_ids: list[str] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        return {
            "transaction_id": self.transaction_id,
            "cost_center":    self.cost_center,
            "order_total":    str(self.order_total),
            "currency":       self.currency,
            "category":       self.category,
            "requester_id":   self.requester_id,
            "item_ids":       self.item_ids,
            "provider_ids":   self.provider_ids,
        }


@dataclass
class BudgetCheckResult:
    allowed: bool
    available_balance: str | None = None
    hold_id: str | None = None
    expires_at: str | None = None
    reasons: list[str] = field(default_factory=list)
    vendor: str | None = None
    fallback: bool = False

    @classmethod
    def from_json(cls, body: dict[str, Any]) -> "BudgetCheckResult":
        return cls(
            allowed=bool(body.get("allowed")),
            available_balance=body.get("available_balance"),
            hold_id=body.get("hold_id"),
            expires_at=body.get("expires_at"),
            reasons=list(body.get("reasons") or []),
            vendor=body.get("vendor"),
            fallback=bool(body.get("fallback", False)),
        )

    @classmethod
    def fail_open(cls) -> "BudgetCheckResult":
        return cls(allowed=True, fallback=True, reasons=["adapter_unavailable_fail_open"])


# ── Client ───────────────────────────────────────────────────────────────────

class ErpAdapterClient:
    """Tiny HTTP client. One short retry on connection error, total wall budget
    enforced by `timeout_ms`. The adapter is internal infrastructure; no auth
    rotation/refresh logic is needed beyond the static bearer.
    """

    def __init__(
        self,
        *,
        base_url: str,
        internal_token: str,
        timeout_ms: int = 800,
        budget_check_required: bool = False,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._headers = {
            "Authorization": f"Bearer {internal_token}",
            "Content-Type": "application/json",
        }
        self._timeout = aiohttp.ClientTimeout(total=timeout_ms / 1000)
        self._required = budget_check_required

    async def budget_check(self, req: BudgetCheckRequest) -> BudgetCheckResult:
        url = f"{self._base_url}/api/v1/budget/check"
        body = req.to_json()
        try:
            return await self._budget_check_with_retry(url, body)
        except Exception as exc:
            if self._required:
                logger.error("budget_check FAILED (required=True) txn=%s err=%s",
                             req.transaction_id, exc)
                raise
            logger.warning("budget_check unavailable txn=%s — fail-open (required=False) err=%s",
                           req.transaction_id, exc)
            return BudgetCheckResult.fail_open()

    async def _budget_check_with_retry(self, url: str, body: dict[str, Any]) -> BudgetCheckResult:
        last_exc: Exception | None = None
        for attempt in (1, 2):
            try:
                async with aiohttp.ClientSession(headers=self._headers, timeout=self._timeout) as s:
                    async with s.post(url, json=body) as resp:
                        data = await resp.json()
                        if resp.status == 200:
                            return BudgetCheckResult.from_json(data)
                        if resp.status == 503:
                            # vendor reports unavailable — treat as transient
                            raise aiohttp.ClientResponseError(
                                request_info=resp.request_info, history=resp.history,
                                status=503, message=data.get("reason", "vendor_unavailable"),
                            )
                        # 4xx / 5xx other than 503 → propagate
                        raise aiohttp.ClientResponseError(
                            request_info=resp.request_info, history=resp.history,
                            status=resp.status, message=str(data)[:200],
                        )
            except (aiohttp.ClientConnectorError, asyncio.TimeoutError) as exc:
                last_exc = exc
                if attempt == 1:
                    await asyncio.sleep(0.15)
                    continue
                raise
            except aiohttp.ClientResponseError as exc:
                # only 5xx is worth a second attempt
                if 500 <= exc.status < 600 and attempt == 1:
                    last_exc = exc
                    await asyncio.sleep(0.15)
                    continue
                raise
        raise last_exc if last_exc else RuntimeError("unreachable")

    async def policy_evaluate(self, req: PolicyEvaluateRequest) -> dict[str, Any]:
        """Fetch ERP procurement policy envelope. Always fail-open.

        Returns a dict with at minimum:
          preferred_supplier_ids, approval_required, auto_commit_allowed, fallback.
        fallback=True signals the PolicyEngine that ERP was unavailable and it
        should apply the base policy only.
        """
        _FAIL_OPEN: dict[str, Any] = {
            "preferred_supplier_ids": [],
            "approval_required":      False,
            "auto_commit_allowed":    True,
            "fallback":               True,
            "constraints":            [],
        }
        url = f"{self._base_url}/api/v1/policy/evaluate"
        body = req.to_json()
        try:
            async with aiohttp.ClientSession(
                headers=self._headers, timeout=self._timeout
            ) as s:
                async with s.post(url, json=body) as resp:
                    data = await resp.json()
                    if resp.status >= 400:
                        logger.warning(
                            "policy_evaluate non-2xx status=%s txn=%s",
                            resp.status, req.transaction_id,
                        )
                        return _FAIL_OPEN
                    return data
        except Exception as exc:
            logger.warning(
                "policy_evaluate unavailable txn=%s — fail-open err=%s",
                req.transaction_id, exc,
            )
            return _FAIL_OPEN

    async def enqueue_sync(self, normalized_po: dict[str, Any]) -> None:
        """Fire-and-forget. Logs on failure; never raises into the caller."""
        url = f"{self._base_url}/api/v1/po/sync"
        try:
            timeout = aiohttp.ClientTimeout(total=2.0)
            async with aiohttp.ClientSession(headers=self._headers, timeout=timeout) as s:
                async with s.post(url, json=normalized_po) as resp:
                    if resp.status >= 400:
                        logger.warning("enqueue_sync non-2xx status=%s txn=%s",
                                       resp.status, normalized_po.get("transaction_id"))
                    else:
                        body = await resp.json()
                        logger.info("enqueue_sync ok sync_id=%s txn=%s",
                                    body.get("sync_id"), normalized_po.get("transaction_id"))
        except Exception as exc:
            logger.warning("enqueue_sync failed txn=%s err=%s",
                           normalized_po.get("transaction_id"), exc)
