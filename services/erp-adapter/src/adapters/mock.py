"""Adapter that talks to services/erp-mock.

Used for local dev, integration tests, and CI. When a real SAP/Oracle tenant
is available, swap to SAPS4HanaAdapter / OracleERPCloudAdapter — the contract
is identical.
"""
from __future__ import annotations

import contextvars
import logging
from datetime import datetime, timezone
from typing import ClassVar

from aiohttp import ClientError, ClientSession

from adapters.base import (
    ERPAdapter,
    VendorPermanentError,
    VendorTransientError,
)
from models import (
    BudgetCheckRequest,
    BudgetCheckResult,
    InboundStatus,
    NormalizedPO,
    PolicyEnvelope,
    PolicyEvaluateRequest,
    PushResult,
)
from resilience import breaker_call

logger = logging.getLogger(__name__)

# Per-request override channel for the mock scenario. Route handlers set this
# from the inbound `X-Mock-Scenario` header; MockERPAdapter forwards it as the
# same header to services/erp-mock. Decouples mock-specific behavior from the
# vendor-neutral ERPAdapter Protocol.
mock_scenario_ctx: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "erp_adapter_mock_scenario", default=None,
)


class MockERPAdapter(ERPAdapter):
    vendor: ClassVar[str] = "mock"

    def __init__(self, base_url: str, http: ClientSession, *, breaker=None) -> None:
        self._base_url = base_url.rstrip("/")
        self._http = http
        self._breaker = breaker

    async def check_budget(self, req: BudgetCheckRequest) -> BudgetCheckResult:
        if self._breaker is not None:
            return await breaker_call(self._breaker, self._check_budget_impl, req)
        return await self._check_budget_impl(req)

    async def _check_budget_impl(self, req: BudgetCheckRequest) -> BudgetCheckResult:
        url = f"{self._base_url}/mock/budget/check"
        payload = req.model_dump(mode="json")
        headers: dict[str, str] = {}
        scenario = mock_scenario_ctx.get()
        if scenario:
            headers["X-Mock-Scenario"] = scenario
        try:
            async with self._http.post(url, json=payload, headers=headers) as resp:
                body = await resp.json()
                if 500 <= resp.status < 600:
                    raise VendorTransientError(f"mock budget 5xx: {resp.status} {body}")
                if resp.status >= 400:
                    raise VendorPermanentError(f"mock budget {resp.status}: {body}")
                # erp-mock returns the BudgetCheckResult shape directly
                return BudgetCheckResult(vendor=self.vendor, **body)
        except ClientError as exc:
            raise VendorTransientError(f"mock budget network: {exc}") from exc

    async def evaluate_policy(self, req: PolicyEvaluateRequest) -> PolicyEnvelope:
        if self._breaker is not None:
            return await breaker_call(self._breaker, self._evaluate_policy_impl, req)
        return await self._evaluate_policy_impl(req)

    async def _evaluate_policy_impl(self, req: PolicyEvaluateRequest) -> PolicyEnvelope:
        url = f"{self._base_url}/mock/policy/evaluate"
        payload = req.model_dump(mode="json")
        headers: dict[str, str] = {}
        scenario = mock_scenario_ctx.get()
        if scenario:
            headers["X-Mock-Scenario"] = scenario
        try:
            async with self._http.post(url, json=payload, headers=headers) as resp:
                body = await resp.json()
                if 500 <= resp.status < 600:
                    raise VendorTransientError(f"mock policy 5xx: {resp.status} {body}")
                if resp.status >= 400:
                    raise VendorPermanentError(f"mock policy {resp.status}: {body}")
                return PolicyEnvelope.model_validate(body)
        except ClientError as exc:
            raise VendorTransientError(f"mock policy network: {exc}") from exc

    async def push_po(self, po: NormalizedPO, idempotency_key: str) -> PushResult:
        if self._breaker is not None:
            return await breaker_call(self._breaker, self._push_po_impl, po, idempotency_key)
        return await self._push_po_impl(po, idempotency_key)

    async def _push_po_impl(self, po: NormalizedPO, idempotency_key: str) -> PushResult:
        url = f"{self._base_url}/mock/po/create"
        headers: dict[str, str] = {"Idempotency-Key": idempotency_key}
        # Scenario priority: payload metadata (survives async hop into outbox
        # worker) > contextvar (synchronous request-scoped path)
        scenario = (po.metadata or {}).get("mock_scenario") or mock_scenario_ctx.get()
        if scenario:
            headers["X-Mock-Scenario"] = scenario
        try:
            async with self._http.post(url, json=po.model_dump(mode="json"), headers=headers) as resp:
                body = await resp.json()
                if 500 <= resp.status < 600:
                    raise VendorTransientError(f"mock po_create 5xx: {resp.status} {body}")
                if resp.status >= 400:
                    raise VendorPermanentError(f"mock po_create {resp.status}: {body}")
                erp_ref = body.get("erp_reference_id")
                if not erp_ref:
                    raise VendorPermanentError(f"mock po_create: missing erp_reference_id in {body}")
                return PushResult(vendor=self.vendor, erp_reference_id=erp_ref, raw=body)
        except ClientError as exc:
            raise VendorTransientError(f"mock po_create network: {exc}") from exc

    async def cancel_po(self, erp_reference_id: str, reason: str) -> None:
        raise NotImplementedError("cancel_po lands in M3.4")

    def normalize_inbound_status(self, payload: dict, headers: dict) -> InboundStatus:
        """Mock webhook envelope mirrors the InboundStatus shape directly —
        the mock emitter (services/erp-mock/src/webhook_emitter.py) writes
        the canonical fields, so we just validate and pass through.

        event_ts: prefer the vendor-provided timestamp; fall back to NOW.
        """
        ts = payload.get("event_ts")
        try:
            event_ts = datetime.fromisoformat(ts) if ts else datetime.now(timezone.utc)
        except (TypeError, ValueError):
            event_ts = datetime.now(timezone.utc)
        return InboundStatus(
            vendor=self.vendor,
            transaction_id=payload.get("transaction_id", ""),
            erp_reference_id=payload.get("erp_reference_id"),
            state=payload.get("state", "UNKNOWN"),
            event_ts=event_ts,
            vendor_event_id=payload.get("vendor_event_id"),
            raw=payload,
        )

    async def healthcheck(self) -> bool:
        try:
            async with self._http.get(f"{self._base_url}/health", timeout=3) as resp:
                return resp.status == 200
        except Exception:
            return False
