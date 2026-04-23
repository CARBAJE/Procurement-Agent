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
from .models import BecknIntent, DiscoverOffering, DiscoverResponse, SelectOrder

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
