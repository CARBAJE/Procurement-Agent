"""SAP S/4HANA adapter — OAuth2 + CSRF + OData v4 PurchaseOrder POST.

Endpoint surface (Cloud Public Edition):
  POST {token_url}                                         OAuth client_credentials
  GET  {base}/A_PurchaseOrder   X-CSRF-Token: Fetch       → returns X-CSRF-Token + cookies
  POST {base}/A_PurchaseOrder   X-CSRF-Token + cookies    → creates the PO

Body mapping is intentionally small for the M3.4 milestone. Production
deployments will fan out additional headers (sap-language, sap-client) and
extend the line-item payload with item-level conditions/textual notes; the
mapper module is a clear extension point.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, ClassVar
from decimal import Decimal

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


# ── NormalizedPO → SAP OData v4 mapping ──────────────────────────────────────

def map_to_sap_purchase_order(po: NormalizedPO) -> dict[str, Any]:
    """Vendor mapper — pure function so the contract test can pin its output.

    Defaults align with SAP Cloud Public Edition's required fields for an
    ad-hoc PO create. Production tenants will likely override
    PurchaseOrderType / PurchasingOrganization / PurchasingGroup via config.
    """
    items: list[dict[str, Any]] = []
    for idx, li in enumerate(po.line_items, start=1):
        items.append({
            "PurchaseOrderItem": f"{idx*10:05d}",       # 00010, 00020, …
            "Material": li.item_id,
            "PurchaseOrderItemText": li.name,
            "OrderQuantity": str(li.quantity),
            "PurchaseOrderQuantityUnit": (li.unit or "EA").upper()[:3],
            "NetPriceAmount": str(li.unit_price),
            "DocumentCurrency": li.currency or po.totals.currency,
        })

    return {
        "PurchaseOrderType": "NB",
        "PurchasingOrganization": "1000",
        "PurchasingGroup": "001",
        "Supplier": po.supplier.bpp_id,
        "CompanyCode": "1000",
        "DocumentCurrency": po.totals.currency,
        "to_PurchaseOrderItem": {"results": items},
    }


# ── Adapter ───────────────────────────────────────────────────────────────────

class SAPS4HanaAdapter(ERPAdapter):
    vendor: ClassVar[str] = "sap"

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

    # ── Public Protocol surface ──────────────────────────────────────────────

    async def check_budget(self, req: BudgetCheckRequest) -> BudgetCheckResult:
        if self._breaker is not None:
            return await breaker_call(self._breaker, self._check_budget_impl, req)
        return await self._check_budget_impl(req)

    async def push_po(self, po: NormalizedPO, idempotency_key: str) -> PushResult:
        if self._breaker is not None:
            return await breaker_call(self._breaker, self._push_po_impl, po, idempotency_key)
        return await self._push_po_impl(po, idempotency_key)

    async def cancel_po(self, erp_reference_id: str, reason: str) -> None:
        # M3.4 ships the create path. Cancel is a follow-up — real SAP requires
        # DELETE on A_PurchaseOrder({PurchaseOrder}) with CSRF.
        raise NotImplementedError("SAP cancel_po — see plan §future work")

    def normalize_inbound_status(self, payload: dict, headers: dict) -> InboundStatus:
        # SAP cloud events look like {PurchaseOrder, ProcessingStatus, ...}.
        # Map the few we need; raw payload is preserved on .raw for forensics.
        ts = payload.get("EventTime") or payload.get("event_ts")
        try:
            event_ts = datetime.fromisoformat(ts) if ts else datetime.now(timezone.utc)
        except (TypeError, ValueError):
            event_ts = datetime.now(timezone.utc)
        return InboundStatus(
            vendor=self.vendor,
            transaction_id=str(payload.get("transaction_id") or payload.get("TransactionId") or ""),
            erp_reference_id=str(payload.get("PurchaseOrder")
                                 or payload.get("erp_reference_id") or "") or None,
            state=str(payload.get("ProcessingStatus")
                      or payload.get("state") or "UNKNOWN").upper(),
            event_ts=event_ts,
            vendor_event_id=payload.get("EventId") or payload.get("vendor_event_id"),
            raw=payload,
        )

    async def healthcheck(self) -> bool:
        try:
            async with self._http.get(self._base + "/A_PurchaseOrder",
                                      headers={"X-CSRF-Token": "Fetch"},
                                      timeout=5) as resp:
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
                    raise VendorTransientError(f"sap budget 5xx: {resp.status} {body}")
                if resp.status >= 400:
                    raise VendorPermanentError(f"sap budget {resp.status}: {body}")
                return BudgetCheckResult(vendor=self.vendor, **body)
        except ClientError as exc:
            raise VendorTransientError(f"sap budget network: {exc}") from exc

    async def _push_po_impl(self, po: NormalizedPO, idempotency_key: str) -> PushResult:
        token = await self._tokens.get()
        csrf_token, cookies = await self._fetch_csrf(token)
        body = map_to_sap_purchase_order(po)
        headers = {
            "Authorization": f"Bearer {token}",
            "X-CSRF-Token": csrf_token,
            "Idempotency-Key": idempotency_key,
            "Accept": "application/json",
        }
        # Dev-loop only: propagate the mock-erp scenario header. Real SAP
        # ignores unknown headers; production tenants are unaffected.
        scenario = (po.metadata or {}).get("mock_scenario")
        if scenario:
            headers["X-Mock-Scenario"] = scenario
        try:
            async with self._http.post(
                self._base + "/A_PurchaseOrder",
                json=body, headers=headers, cookies=cookies,
            ) as resp:
                if resp.status == 401:
                    # Cached token rejected — invalidate so the next attempt
                    # forces a refresh.
                    self._tokens.invalidate()
                    raise VendorTransientError("sap push_po 401 (token invalidated)")
                if 500 <= resp.status < 600:
                    text = await resp.text()
                    raise VendorTransientError(f"sap push_po 5xx: {resp.status} {text[:200]}")
                if resp.status >= 400:
                    text = await resp.text()
                    raise VendorPermanentError(f"sap push_po {resp.status}: {text[:200]}")
                payload = await resp.json(content_type=None)
                # OData v4 envelope: { "d": { "PurchaseOrder": "4500001234", ... } }
                data = payload.get("d") or payload
                po_number = data.get("PurchaseOrder") or data.get("PurchaseOrderId")
                if not po_number:
                    raise VendorPermanentError(f"sap push_po: missing PurchaseOrder in response {data}")
                return PushResult(vendor=self.vendor, erp_reference_id=str(po_number), raw=payload)
        except ClientError as exc:
            raise VendorTransientError(f"sap push_po network: {exc}") from exc

    async def _fetch_csrf(self, token: str) -> tuple[str, dict[str, str]]:
        """OData v4 dance: GET with X-CSRF-Token: Fetch → server returns token
        (and session cookies). Token + cookies must be replayed on the POST.
        """
        headers = {
            "Authorization": f"Bearer {token}",
            "X-CSRF-Token": "Fetch",
            "Accept": "application/json",
        }
        try:
            async with self._http.get(
                self._base + "/A_PurchaseOrder", headers=headers
            ) as resp:
                if 500 <= resp.status < 600:
                    raise VendorTransientError(f"sap csrf 5xx: {resp.status}")
                if resp.status >= 400:
                    raise VendorPermanentError(f"sap csrf {resp.status}")
                csrf = resp.headers.get("X-CSRF-Token", "")
                cookies = {k: v.value for k, v in resp.cookies.items()}
                if not csrf:
                    raise VendorPermanentError("sap csrf: no X-CSRF-Token header in response")
                return csrf, cookies
        except ClientError as exc:
            raise VendorTransientError(f"sap csrf network: {exc}") from exc
