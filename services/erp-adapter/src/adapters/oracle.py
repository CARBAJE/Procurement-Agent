"""Oracle ERP Cloud adapter — OAuth2 client_credentials + REST.

Endpoint surface (Fusion Cloud / IDCS):
  POST {token_url}                          OAuth client_credentials
  POST {base}/purchaseOrders                creates the PO

A JWT-bearer assertion grant is also valid for some IDCS configurations;
adding it is a one-method addition to OAuthTokenCache. Out of scope for M3.4.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, ClassVar

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
    PushResult,
)
from resilience import breaker_call
from security import OAuthTokenCache

logger = logging.getLogger(__name__)


# ── NormalizedPO → Oracle REST mapping ───────────────────────────────────────

def map_to_oracle_purchase_order(po: NormalizedPO) -> dict[str, Any]:
    """Map our vendor-neutral PO into the Oracle REST shape.

    Lines are a child collection named `lines` per the Fusion REST spec.
    Production tenants set BusinessUnit / Buyer / Supplier from a config
    profile — kept hard-coded as defaults here for M3.4.
    """
    lines: list[dict[str, Any]] = []
    for idx, li in enumerate(po.line_items, start=1):
        lines.append({
            "LineNumber": idx,
            "ItemNumber": li.item_id,
            "Description": li.name,
            "Quantity": li.quantity,
            "UOMCode": (li.unit or "EA").upper()[:3],
            "Price": str(li.unit_price),
            "Currency": li.currency or po.totals.currency,
        })

    return {
        "BusinessUnit": "Vision Operations",
        "Buyer": po.buyer.name or "Procurement Agent",
        "Supplier": po.supplier.name or po.supplier.bpp_id,
        "SupplierSite": po.supplier.bpp_id,
        "Currency": po.totals.currency,
        "TotalAmount": str(po.totals.subtotal),
        "lines": lines,
    }


# ── Adapter ───────────────────────────────────────────────────────────────────

class OracleERPCloudAdapter(ERPAdapter):
    vendor: ClassVar[str] = "oracle"

    def __init__(
        self,
        *,
        base_url: str,
        token_url: str,
        client_id: str,
        client_secret: str,
        budget_check_url: str,
        http: ClientSession,
        breaker=None,
    ) -> None:
        self._base = base_url.rstrip("/")
        self._budget_url = budget_check_url
        self._http = http
        self._breaker = breaker
        self._tokens = OAuthTokenCache(
            vendor=self.vendor, token_url=token_url,
            client_id=client_id, client_secret=client_secret,
            http=http,
        )

    async def check_budget(self, req: BudgetCheckRequest) -> BudgetCheckResult:
        if self._breaker is not None:
            return await breaker_call(self._breaker, self._check_budget_impl, req)
        return await self._check_budget_impl(req)

    async def push_po(self, po: NormalizedPO, idempotency_key: str) -> PushResult:
        if self._breaker is not None:
            return await breaker_call(self._breaker, self._push_po_impl, po, idempotency_key)
        return await self._push_po_impl(po, idempotency_key)

    async def cancel_po(self, erp_reference_id: str, reason: str) -> None:
        raise NotImplementedError("Oracle cancel_po — see plan §future work")

    def normalize_inbound_status(self, payload: dict, headers: dict) -> InboundStatus:
        ts = payload.get("EventTime") or payload.get("event_ts")
        try:
            event_ts = datetime.fromisoformat(ts) if ts else datetime.now(timezone.utc)
        except (TypeError, ValueError):
            event_ts = datetime.now(timezone.utc)
        return InboundStatus(
            vendor=self.vendor,
            transaction_id=str(payload.get("transaction_id") or payload.get("TransactionId") or ""),
            erp_reference_id=str(payload.get("OrderNumber")
                                 or payload.get("erp_reference_id") or "") or None,
            state=str(payload.get("Status")
                      or payload.get("state") or "UNKNOWN").upper(),
            event_ts=event_ts,
            vendor_event_id=payload.get("EventId") or payload.get("vendor_event_id"),
            raw=payload,
        )

    async def healthcheck(self) -> bool:
        try:
            async with self._http.get(self._base + "/purchaseOrders", timeout=5) as resp:
                # 401 still proves the host is alive even without a token.
                return resp.status < 500
        except Exception:
            return False

    # ── Internals ────────────────────────────────────────────────────────────

    async def _check_budget_impl(self, req: BudgetCheckRequest) -> BudgetCheckResult:
        try:
            async with self._http.post(self._budget_url,
                                       json=req.model_dump(mode="json")) as resp:
                body = await resp.json()
                if 500 <= resp.status < 600:
                    raise VendorTransientError(f"oracle budget 5xx: {resp.status} {body}")
                if resp.status >= 400:
                    raise VendorPermanentError(f"oracle budget {resp.status}: {body}")
                return BudgetCheckResult(vendor=self.vendor, **body)
        except ClientError as exc:
            raise VendorTransientError(f"oracle budget network: {exc}") from exc

    async def _push_po_impl(self, po: NormalizedPO, idempotency_key: str) -> PushResult:
        token = await self._tokens.get()
        body = map_to_oracle_purchase_order(po)
        headers = {
            "Authorization": f"Bearer {token}",
            "Idempotency-Key": idempotency_key,
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        scenario = (po.metadata or {}).get("mock_scenario")
        if scenario:
            headers["X-Mock-Scenario"] = scenario
        try:
            async with self._http.post(
                self._base + "/purchaseOrders", json=body, headers=headers,
            ) as resp:
                if resp.status == 401:
                    self._tokens.invalidate()
                    raise VendorTransientError("oracle push_po 401 (token invalidated)")
                if 500 <= resp.status < 600:
                    text = await resp.text()
                    raise VendorTransientError(f"oracle push_po 5xx: {resp.status} {text[:200]}")
                if resp.status >= 400:
                    text = await resp.text()
                    raise VendorPermanentError(f"oracle push_po {resp.status}: {text[:200]}")
                payload = await resp.json(content_type=None)
                order_number = payload.get("OrderNumber") or payload.get("orderNumber")
                if not order_number:
                    raise VendorPermanentError(f"oracle push_po: missing OrderNumber in {payload}")
                return PushResult(vendor=self.vendor, erp_reference_id=str(order_number), raw=payload)
        except ClientError as exc:
            raise VendorTransientError(f"oracle push_po network: {exc}") from exc
