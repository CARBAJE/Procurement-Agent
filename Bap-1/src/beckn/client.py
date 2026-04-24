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
    ) -> None:
        self.adapter = adapter
        self._session = session
        self._owns_session = session is None

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

        return self._parse_on_discover(txn_id, callbacks)

    def _parse_on_discover(self, txn_id: str, callbacks: list) -> DiscoverResponse:
        """Parse on_discover callback payloads into DiscoverResponse.

        Handles two Beckn v2 catalog formats:

        Format A — flat resources (real Beckn v2 Catalog Service):
          message.catalogs[].resources[].{id, descriptor, provider, price, rating}

        Format B — nested providers/items (mock_onix / legacy):
          message.catalog.providers[].items[].{id, descriptor, price}
        """
        offerings: list[DiscoverOffering] = []
        for cb in callbacks:
            msg = cb.message
            # Real Beckn v2: message.catalogs[] (array from Catalog Service)
            catalogs = msg.get("catalogs") or []
            # Mock / legacy: message.catalog (single catalog object)
            if not catalogs and msg.get("catalog"):
                catalogs = [msg["catalog"]]

            for catalog in catalogs:
                bpp_id = catalog.get("bppId") or catalog.get("bpp_id") or cb.context.bpp_id or ""
                bpp_uri = catalog.get("bppUri") or catalog.get("bpp_uri") or cb.context.bpp_uri or ""

                # Format A: flat resources[] (real Beckn v2)
                for resource in catalog.get("resources", []):
                    provider = resource.get("provider", {})
                    provider_id = provider.get("id", "")
                    provider_name = provider.get("descriptor", {}).get("name", "") or provider_id
                    price = resource.get("price", {})
                    rating_obj = resource.get("rating", {})
                    if isinstance(rating_obj, dict):
                        rating = str(rating_obj.get("ratingValue", "")) or None
                    else:
                        rating = str(rating_obj) if rating_obj is not None else None
                    offerings.append(
                        DiscoverOffering(
                            bpp_id=bpp_id,
                            bpp_uri=bpp_uri,
                            provider_id=provider_id,
                            provider_name=provider_name,
                            item_id=resource.get("id", ""),
                            item_name=resource.get("descriptor", {}).get("name", ""),
                            price_value=str(price.get("value", "0")),
                            price_currency=price.get("currency", "INR"),
                            rating=rating,
                        )
                    )

                # Format B: providers[].items[] (mock_onix / legacy)
                for provider in catalog.get("providers", []):
                    provider_id = provider.get("id", "")
                    provider_name = (
                        provider.get("descriptor", {}).get("name", "") or provider_id
                    )
                    rating = provider.get("rating")
                    for item in provider.get("items", []):
                        price = item.get("price", {})
                        offerings.append(
                            DiscoverOffering(
                                bpp_id=bpp_id,
                                bpp_uri=bpp_uri,
                                provider_id=provider_id,
                                provider_name=provider_name,
                                item_id=item.get("id", ""),
                                item_name=item.get("descriptor", {}).get("name", ""),
                                price_value=str(price.get("value", "0")),
                                price_currency=price.get("currency", "INR"),
                                rating=str(rating) if rating is not None else None,
                            )
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
        *,
        contract_id: str,
        items: list[SelectedItem],
        billing: BillingInfo,
        fulfillment: FulfillmentInfo,
        transaction_id: str,
        bpp_id: str,
        bpp_uri: str,
        collector: "CallbackCollector",
        timeout: float = 15.0,
    ) -> InitResponse:
        """Send /init and await the on_init callback.

        Follows the same async pattern as discover_async:
          register → POST → collect → cleanup → parse.

        The BPP's on_init typically adjusts payment terms, which /confirm
        must use verbatim.
        """
        payload = self.adapter.build_init_wire_payload(
            contract_id=contract_id,
            items=items,
            billing=billing,
            fulfillment=fulfillment,
            transaction_id=transaction_id,
            bpp_id=bpp_id,
            bpp_uri=bpp_uri,
        )

        collector.register(transaction_id, "on_init")
        await self._post(self.adapter.caller_action_url("init"), payload)
        callbacks = await collector.collect(transaction_id, "on_init", timeout=timeout)
        collector.cleanup(transaction_id, "on_init")

        return self._parse_on_init(transaction_id, contract_id, callbacks)

    async def confirm(
        self,
        *,
        contract_id: str,
        items: list[SelectedItem],
        payment: PaymentTerms,
        transaction_id: str,
        bpp_id: str,
        bpp_uri: str,
        collector: "CallbackCollector",
        timeout: float = 15.0,
    ) -> ConfirmResponse:
        """Send /confirm and await the on_confirm callback.

        On success the BPP returns an order_id that drives all subsequent
        /status polling. Failure to get a callback within `timeout` raises.

        Items are re-included in the payload because the Beckn v2.1 Contract
        schema requires `commitments` on every message that carries a Contract.
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

        return self._parse_on_confirm(transaction_id, callbacks)

    async def status(
        self,
        *,
        order_id: str,
        items: list[SelectedItem],
        transaction_id: str,
        bpp_id: str,
        bpp_uri: str,
        collector: "CallbackCollector",
        timeout: float = 15.0,
    ) -> StatusResponse:
        """Send /status and await the on_status callback.

        Intended for periodic polling from the UI (30s SLA in Phase 2).
        Each call uses a fresh message_id but the same transaction_id so
        the BPP can correlate.

        Items must be replayed because the v2.1 /status action inherits
        Contract's required `commitments` field.
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
    def _parse_on_init(
        txn_id: str,
        contract_id: str,
        callbacks: list,
    ) -> InitResponse:
        """Extract payment terms + quote from on_init.

        In v2.1 the BPP returns payment as `contract.settlements[0]`. We also
        accept the legacy `contract.payment` shape so older fixtures (and mock
        servers) keep working. Missing payment block → the proposed terms stand.
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

        # v2.1: contract.settlements[0]; legacy: contract.payment or msg.payment.
        settlements = contract.get("settlements") or []
        settlement = settlements[0] if settlements else {}
        payment_raw = settlement or contract.get("payment") or msg.get("payment") or {}

        payment_terms = None
        if payment_raw:
            p_type = payment_raw.get("type") or "ON_FULFILLMENT"
            if p_type not in ("ON_ORDER", "ON_FULFILLMENT", "POST_FULFILLMENT"):
                p_type = "ON_FULFILLMENT"
            payment_terms = PaymentTerms(
                type=p_type,  # type: ignore[arg-type]
                collected_by=(
                    payment_raw.get("collectedBy")
                    or payment_raw.get("collected_by")
                    or "BPP"
                ),
                currency=payment_raw.get("currency", "INR"),
                uri=payment_raw.get("uri"),
                transaction_id=(
                    payment_raw.get("transactionId")
                    or payment_raw.get("transaction_id")
                ),
                status=payment_raw.get("status", "NOT-PAID"),
            )

        # Quote: v2.1 prefers consideration[0].price; legacy uses contract.quote.
        considerations = contract.get("consideration") or []
        consid_price = (considerations[0].get("price") if considerations else None) or {}
        quote = contract.get("quote") or msg.get("quote") or {}
        legacy_price = quote.get("price") or {}
        price = consid_price or legacy_price

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
        """Extract order_id + initial state from on_confirm.

        In v2.1 the BPP response is `message.contract.{id, status.code,
        performance[0]...}`. We also accept the legacy `message.order` shape
        so older fixtures keep working. No callback → RuntimeError (a protocol
        failure the caller must surface).
        """
        if not callbacks:
            raise RuntimeError(
                f"/confirm timed out waiting for on_confirm (txn={txn_id})"
            )

        cb = callbacks[0]
        msg = cb.message
        # v2.1: the order IS the contract. Legacy fixtures nested it under `order`.
        order = msg.get("contract") or msg.get("order") or {}

        order_id = (
            order.get("id")
            or order.get("orderId")
            or msg.get("orderId")
            or f"order-{txn_id}"
        )
        state_raw = (
            (order.get("status") or {}).get("code")
            if isinstance(order.get("status"), dict)
            else order.get("state")
        ) or "CREATED"
        try:
            state = OrderState(state_raw)
        except ValueError:
            state = OrderState.CREATED

        # v2.1: ETA lives in performance[0].performanceAttributes.eta (best effort).
        performance = order.get("performance") or []
        perf_attrs = (performance[0].get("performanceAttributes") if performance else None) or {}
        eta = (
            order.get("fulfillmentEta")
            or order.get("fulfillment_eta")
            or perf_attrs.get("eta")
            or (order.get("fulfillment") or {}).get("eta")
        )

        return ConfirmResponse(
            context=cb.context,
            transaction_id=txn_id,
            order_id=str(order_id),
            state=state,
            fulfillment_eta=eta,
            raw_message=msg,
        )

    @staticmethod
    def _parse_on_status(
        txn_id: str,
        order_id: str,
        callbacks: list,
    ) -> StatusResponse:
        """Extract current state + tracking URL from on_status.

        v2.1 shape: `message.contract.{id, status, performance[0]}`.
        Legacy: `message.order.{id, state, fulfillment}`.

        No callbacks → return CREATED so polling loops can keep running.
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
        order = msg.get("contract") or msg.get("order") or {}

        state_raw = (
            (order.get("status") or {}).get("code")
            if isinstance(order.get("status"), dict)
            else order.get("state")
        ) or "CREATED"
        try:
            state = OrderState(state_raw)
        except ValueError:
            state = OrderState.CREATED

        # v2.1: tracking + ETA live in performance[0].performanceAttributes.
        performance = order.get("performance") or []
        perf_attrs = (performance[0].get("performanceAttributes") if performance else None) or {}
        legacy_fulfillment = order.get("fulfillment") or {}

        eta = (
            perf_attrs.get("eta")
            or legacy_fulfillment.get("eta")
            or order.get("fulfillmentEta")
        )
        tracking_url = (
            perf_attrs.get("trackingUrl")
            or legacy_fulfillment.get("trackingUrl")
            or order.get("trackingUrl")
        )

        return StatusResponse(
            context=cb.context,
            transaction_id=txn_id,
            order_id=str(order.get("id") or order.get("orderId") or order_id),
            state=state,
            fulfillment_eta=eta,
            tracking_url=tracking_url,
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
