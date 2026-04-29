"""Async BAP HTTP client for Beckn Protocol v2.

Two discover modes:
  - discover()       — sync response (mock_onix.py only, used by unit tests)
  - discover_async() — real Beckn network: sends to /bap/caller/discover,
                       waits for on_discover callback via CallbackCollector

All calls go through the beckn-onix adapter, which handles Beckn compliance.

Usage (real network):
    async with BecknClient(adapter) as client:
        response = await client.discover_async(intent, collector)
        ack = await client.select(order, txn_id, bpp_id, bpp_uri)
        init_result = await client.init(contract_id, items, txn_id, bpp_id, bpp_uri, collector)
        confirm_result = await client.confirm(contract_id, items, payment, txn_id, bpp_id, bpp_uri, collector)
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

import aiohttp

from .adapter import BecknProtocolAdapter
from .models import (
    BecknIntent,
    BillingInfo,
    ConfirmResponse,
    DiscoverOffering,
    DiscoverResponse,
    FulfillmentInfo,
    InitResponse,
    OrderState,
    PaymentTerms,
    SelectOrder,
    SelectedItem,
    StatusResponse,
)

if TYPE_CHECKING:
    from .callbacks import CallbackCollector


class BecknClient:
    def __init__(
        self,
        adapter: BecknProtocolAdapter,
        session: aiohttp.ClientSession | None = None,
        catalog_normalizer_url: str = "http://localhost:8005",
    ) -> None:
        self.adapter = adapter
        self._session = session
        self._owns_session = session is None
        self._catalog_normalizer_url = catalog_normalizer_url

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def __aenter__(self) -> "BecknClient":
        if self._owns_session:
            self._session = aiohttp.ClientSession(
                headers={"Content-Type": "application/json"},
            )
        return self

    async def __aexit__(self, *_: Any) -> None:
        if self._owns_session and self._session:
            await self._session.close()
            self._session = None

    # ── Core flows ────────────────────────────────────────────────────────────

    async def discover(
        self,
        intent: BecknIntent,
        transaction_id: str | None = None,
    ) -> DiscoverResponse:
        """Discover matching offerings via the ONIX adapter (synchronous).

        In Beckn v2, BPPs proactively publish their catalogs to the Catalog
        Service. The Discovery Service queries it and returns matching offerings
        directly — no async callbacks required.

        Returns:
            DiscoverResponse with list of offerings and transaction_id
        """
        request = self.adapter.build_discover_request(intent, transaction_id)
        payload = self.adapter.sign_request(
            request.model_dump(exclude_none=True)
        )
        data = await self._post(self.adapter.discover_url, payload)
        return DiscoverResponse.model_validate(data)

    async def discover_async(
        self,
        intent: BecknIntent,
        collector: "CallbackCollector",
        transaction_id: str | None = None,
        timeout: float = 15.0,
    ) -> DiscoverResponse:
        """Discover via real Beckn network (async on_discover callback).

        Sends camelCase Beckn v2 payload to /bap/caller/discover.
        ONIX signs & forwards to Discovery Service.
        Waits for on_discover callback with catalog.

        Args:
            collector: CallbackCollector to receive on_discover callbacks
            timeout:   Seconds to wait for callbacks before returning empty list
        """
        payload, txn_id = self.adapter.build_discover_wire_payload(intent, transaction_id)

        collector.register(txn_id, "on_discover")
        await self._post(self.adapter.discover_url, payload)  # returns ACK

        callbacks = await collector.collect(txn_id, "on_discover", timeout=timeout)
        collector.cleanup(txn_id, "on_discover")

        return await self._build_discover_response(txn_id, callbacks)

    async def _build_discover_response(self, txn_id: str, callbacks: list) -> DiscoverResponse:
        """Normalize on_discover callback payloads via catalog-normalizer service."""
        offerings: list[DiscoverOffering] = []
        for cb in callbacks:
            msg = cb.message
            catalogs = msg.get("catalogs") or []
            if not catalogs and msg.get("catalog"):
                catalogs = [msg["catalog"]]

            for catalog in catalogs:
                bpp_id = catalog.get("bppId") or catalog.get("bpp_id") or cb.context.bpp_id or ""
                bpp_uri = catalog.get("bppUri") or catalog.get("bpp_uri") or cb.context.bpp_uri or ""

                payload = {
                    "payload": {"message": {"catalog": catalog}},
                    "bpp_id": bpp_id,
                    "bpp_uri": bpp_uri,
                }
                try:
                    async with self._session.post(
                        f"{self._catalog_normalizer_url}/normalize", json=payload
                    ) as resp:
                        data = await resp.json()
                        offerings.extend(
                            [DiscoverOffering(**o) for o in data.get("offerings", [])]
                        )
                except Exception as exc:
                    import logging
                    logging.getLogger(__name__).warning(
                        "catalog-normalizer call failed: %s", exc
                    )

        ctx = callbacks[0].context if callbacks else None
        return DiscoverResponse(
            context=ctx,
            transaction_id=txn_id,
            offerings=offerings,
        )

    async def select(
        self,
        order: SelectOrder,
        transaction_id: str,
        bpp_id: str,
        bpp_uri: str,
    ) -> dict:
        """Send /select via ONIX adapter.

        ONIX routes to POST /bpp/receiver/select on the chosen BPP.
        The async callback (on_select) arrives at /bap/receiver/on_select.

        Returns:
            ONIX ACK dict
        """
        payload = self.adapter.build_select_wire_payload(
            order, transaction_id, bpp_id, bpp_uri
        )
        return await self._post(self.adapter.select_url, payload)

    async def init(
        self,
        contract_id: str,
        items: list[SelectedItem],
        transaction_id: str,
        bpp_id: str,
        bpp_uri: str,
        collector: "CallbackCollector",
        timeout: float = 15.0,
        *,
        billing: BillingInfo | None = None,
        fulfillment: FulfillmentInfo | None = None,
    ) -> InitResponse:
        """Send /init and await the on_init callback.

        Follows the same async pattern as discover_async:
          register → POST → collect → cleanup → parse.

        Returns:
            InitResponse with payment_terms from BPP (None if BPP didn't return them).
        """
        payload = self.adapter.build_init_wire_payload(
            contract_id=contract_id,
            items=items,
            transaction_id=transaction_id,
            bpp_id=bpp_id,
            bpp_uri=bpp_uri,
            billing=billing,
            fulfillment=fulfillment,
        )

        collector.register(transaction_id, "on_init")
        await self._post(self.adapter.caller_action_url("init"), payload)
        callbacks = await collector.collect(transaction_id, "on_init", timeout=timeout)
        collector.cleanup(transaction_id, "on_init")

        return self._parse_on_init(transaction_id, contract_id, callbacks)

    async def confirm(
        self,
        contract_id: str,
        items: list[SelectedItem],
        payment: dict,
        transaction_id: str,
        bpp_id: str,
        bpp_uri: str,
        collector: "CallbackCollector",
        timeout: float = 15.0,
    ) -> ConfirmResponse:
        """Send /confirm and await the on_confirm callback.

        Items are re-included because Beckn v2.1 Contract schema requires
        commitments on every message that carries a Contract.

        Raises:
            RuntimeError: if no callback arrives within timeout — the
            orchestrator's /commit handler catches this and falls back to mock.
        """
        payload = self.adapter.build_confirm_wire_payload(
            contract_id=contract_id,
            items=items,
            payment=payment,
            transaction_id=transaction_id,
            bpp_id=bpp_id,
            bpp_uri=bpp_uri,
        )

        collector.register(transaction_id, "on_confirm")
        await self._post(self.adapter.caller_action_url("confirm"), payload)
        callbacks = await collector.collect(transaction_id, "on_confirm", timeout=timeout)
        collector.cleanup(transaction_id, "on_confirm")

        if not callbacks:
            raise RuntimeError(f"/confirm timed out (txn={transaction_id})")

        return self._parse_on_confirm(transaction_id, callbacks)

    async def status(
        self,
        order_id: str,
        items: list[SelectedItem],
        transaction_id: str,
        bpp_id: str,
        bpp_uri: str,
        collector: "CallbackCollector",
        timeout: float = 15.0,
    ) -> StatusResponse:
        """Send /status and await the on_status callback.

        Items must be replayed because the v2.1 /status action inherits
        Contract's required commitments field.
        Never raises — status polling must be resilient to timeout.
        """
        payload = self.adapter.build_status_wire_payload(
            order_id=order_id,
            items=items,
            transaction_id=transaction_id,
            bpp_id=bpp_id,
            bpp_uri=bpp_uri,
        )

        collector.register(transaction_id, "on_status")
        await self._post(self.adapter.caller_action_url("status"), payload)
        callbacks = await collector.collect(transaction_id, "on_status", timeout=timeout)
        collector.cleanup(transaction_id, "on_status")

        return self._parse_on_status(transaction_id, order_id, callbacks)

    # ── Callback parsers ──────────────────────────────────────────────────────

    @staticmethod
    def _parse_on_init(txn_id: str, contract_id: str, callbacks: list) -> InitResponse:
        """Extract payment terms + quote from on_init callback.

        Tries contract.settlements[0] (v2.1), then contract.payment, then
        message.payment (legacy). payment_terms is None when the BPP doesn't
        include payment terms — orchestrator falls back to ON_FULFILLMENT defaults.
        """
        if not callbacks:
            return InitResponse(
                transaction_id=txn_id,
                contract_id=contract_id,
                payment_terms=None,
                raw_message={},
            )

        cb = callbacks[0]
        msg = cb.message
        contract = msg.get("contract") or {}

        settlements = contract.get("settlements") or []
        settlement = settlements[0] if settlements else {}
        payment_raw = settlement or contract.get("payment") or msg.get("payment") or {}

        payment_terms = None
        if payment_raw:
            p_type = payment_raw.get("type") or payment_raw.get("paymentType") or "ON_FULFILLMENT"
            if p_type not in ("ON_ORDER", "ON_FULFILLMENT", "POST_FULFILLMENT"):
                p_type = "ON_FULFILLMENT"
            payment_terms = PaymentTerms(
                type=p_type,  # type: ignore[arg-type]
                collected_by=(
                    payment_raw.get("collectedBy")
                    or payment_raw.get("collected_by")
                    or "BPP"
                ),
                currency=payment_raw.get("currency") or "INR",
                uri=payment_raw.get("uri"),
                transaction_id=(
                    payment_raw.get("transactionId")
                    or payment_raw.get("transaction_id")
                ),
                status=payment_raw.get("status") or "NOT-PAID",
            )

        # Quote: v2.1 prefers consideration[0].price; legacy uses contract.quote.
        considerations = contract.get("consideration") or []
        consid_price = (considerations[0].get("price") if considerations else None) or {}
        quote = contract.get("quote") or msg.get("quote") or {}
        price = consid_price or quote.get("price") or {}

        return InitResponse(
            context=cb.context,
            transaction_id=txn_id,
            contract_id=contract.get("id") or contract_id,
            payment_terms=payment_terms,
            quote_total=price.get("value"),
            quote_currency=price.get("currency", "INR"),
            raw_message=msg,
        )

    @staticmethod
    def _parse_on_confirm(txn_id: str, callbacks: list) -> ConfirmResponse:
        """Extract order_id + state from on_confirm callback.

        v2.1 shape: message.contract.{id, status.code, performance[0]}.
        Legacy: message.order.{id, state, fulfillment}.
        """
        msg = callbacks[0].message
        contract = msg.get("contract") or {}
        order = msg.get("order") or {}

        order_id = (
            contract.get("id")
            or order.get("id")
            or order.get("orderId")
            or f"order-{txn_id}"
        )
        state_raw = (
            (contract.get("status") or {}).get("code")
            or order.get("state")
            or "CREATED"
        )
        try:
            state = OrderState(state_raw)
        except ValueError:
            state = OrderState.CREATED

        performance = contract.get("performance") or []
        perf_attrs = (performance[0].get("performanceAttributes") if performance else None) or {}
        eta = (
            perf_attrs.get("eta")
            or order.get("fulfillmentEta")
            or order.get("fulfillment_eta")
        )

        return ConfirmResponse(
            context=callbacks[0].context,
            transaction_id=txn_id,
            order_id=str(order_id),
            state=state,
            fulfillment_eta=eta,
            raw_message=msg,
        )

    @staticmethod
    def _parse_on_status(txn_id: str, order_id: str, callbacks: list) -> StatusResponse:
        """Extract current state + tracking URL from on_status callback.

        v2.1 shape: message.contract.{id, status, performance[0]}.
        Legacy: message.order.{id, state, fulfillment}.
        No callbacks → CREATED so polling loops keep running.
        """
        if not callbacks:
            return StatusResponse(
                transaction_id=txn_id,
                order_id=order_id,
                state=OrderState.CREATED,
                raw_message={},
            )

        cb = callbacks[0]
        msg = cb.message
        contract = msg.get("contract") or {}
        order = msg.get("order") or {}
        fulfillment = msg.get("fulfillment") or {}

        state_raw = (
            (contract.get("status") or {}).get("code")
            or order.get("state")
            or "CREATED"
        )
        try:
            state = OrderState(state_raw)
        except ValueError:
            state = OrderState.CREATED

        performance = contract.get("performance") or []
        perf_attrs = (performance[0].get("performanceAttributes") if performance else None) or {}

        eta = (
            perf_attrs.get("eta")
            or fulfillment.get("eta")
            or fulfillment.get("fulfillmentEta")
            or order.get("fulfillmentEta")
            or msg.get("fulfillmentEta")
        )
        tracking = (
            perf_attrs.get("trackingUrl")
            or fulfillment.get("trackingUrl")
            or fulfillment.get("tracking_url")
            or order.get("trackingUrl")
            or msg.get("trackingUrl")
        )

        return StatusResponse(
            context=cb.context,
            transaction_id=txn_id,
            order_id=str(contract.get("id") or order.get("id") or order.get("orderId") or order_id),
            state=state,
            fulfillment_eta=eta,
            tracking_url=tracking,
            raw_message=msg,
        )

    # ── Internal ──────────────────────────────────────────────────────────────

    async def _post(self, url: str, payload: dict) -> dict:
        if self._session is None:
            raise RuntimeError(
                "BecknClient must be used as an async context manager"
            )
        timeout = aiohttp.ClientTimeout(
            total=self.adapter.config.request_timeout
        )
        async with self._session.post(url, json=payload, timeout=timeout) as resp:
            resp.raise_for_status()
            return await resp.json()
