"""Deterministic schema mapper for known catalog format variants."""
from __future__ import annotations

import re

from shared.models import DiscoverOffering
from .formats import FormatVariant


class SchemaMapper:
    def map(
        self,
        catalog: dict,
        variant: FormatVariant,
        bpp_id: str,
        bpp_uri: str,
    ) -> list[DiscoverOffering]:
        dispatch = {
            FormatVariant.BECKN_V2_FLAT_RESOURCES: self._map_v2_flat_resources,
            FormatVariant.LEGACY_PROVIDERS_ITEMS: self._map_legacy_providers,
            FormatVariant.BPP_CATALOG_V1: self._map_bpp_v1,
            FormatVariant.ONDC_CATALOG: self._map_ondc,
        }
        handler = dispatch.get(variant)
        if handler is None:
            return []
        return handler(catalog, bpp_id, bpp_uri)

    # ── Format A: flat resources[] (real Beckn v2) ────────────────────────────

    def _map_v2_flat_resources(
        self, catalog: dict, bpp_id: str, bpp_uri: str
    ) -> list[DiscoverOffering]:
        offerings: list[DiscoverOffering] = []
        for resource in catalog.get("resources", []):
            provider = resource.get("provider", {})
            provider_id = provider.get("id", "")
            provider_name = (
                provider.get("descriptor", {}).get("name", "") or provider_id
            )
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
        return offerings

    # ── Format B: providers[].items[] (mock_onix / legacy) ───────────────────

    def _map_legacy_providers(
        self, catalog: dict, bpp_id: str, bpp_uri: str
    ) -> list[DiscoverOffering]:
        offerings: list[DiscoverOffering] = []
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
        return offerings

    # ── Format C: catalog.items[] with provider as string key ────────────────

    def _map_bpp_v1(
        self, catalog: dict, bpp_id: str, bpp_uri: str
    ) -> list[DiscoverOffering]:
        offerings: list[DiscoverOffering] = []
        for item in catalog.get("items", []):
            provider_id = item.get("provider", "")
            item_name = item.get("descriptor", {}).get("name", "")
            price = item.get("price", {})
            offerings.append(
                DiscoverOffering(
                    bpp_id=bpp_id,
                    bpp_uri=bpp_uri,
                    provider_id=provider_id,
                    provider_name=provider_id,
                    item_id=item.get("id", ""),
                    item_name=item_name,
                    price_value=str(price.get("value", "0")),
                    price_currency=price.get("currency", "INR"),
                )
            )
        return offerings

    # ── Format D: ONDC with fulfillments[] + tags[] ───────────────────────────

    def _map_ondc(
        self, catalog: dict, bpp_id: str, bpp_uri: str
    ) -> list[DiscoverOffering]:
        offerings: list[DiscoverOffering] = []
        # Build fulfillment hours lookup from fulfillments[]
        fulfillment_map: dict[str, int] = {}
        for ff in catalog.get("fulfillments", []):
            ff_id = ff.get("id", "")
            duration = ff.get("TAT") or ff.get("tat") or ff.get("duration", "")
            if ff_id and duration:
                fulfillment_map[ff_id] = _iso_duration_to_hours(duration)

        for provider in catalog.get("providers", []):
            provider_id = provider.get("id", "")
            provider_name = (
                provider.get("descriptor", {}).get("name", "") or provider_id
            )
            for item in provider.get("items", []):
                price = item.get("price", {})
                # resolve fulfillment hours from item's fulfillment_ids
                ff_hours: int | None = None
                ff_ids = item.get("fulfillment_ids") or item.get("fulfillment_id")
                if isinstance(ff_ids, str):
                    ff_ids = [ff_ids]
                if ff_ids:
                    for fid in ff_ids:
                        if fid in fulfillment_map:
                            ff_hours = fulfillment_map[fid]
                            break
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
                        fulfillment_hours=ff_hours,
                    )
                )
        return offerings


def _iso_duration_to_hours(s: str) -> int:
    """Convert ISO 8601 duration string to hours.

    Examples: 'P1D' → 24, 'PT2H' → 2, 'P2DT6H' → 54
    """
    total_hours = 0
    pattern = re.compile(
        r"P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?"
    )
    m = pattern.match(s.upper())
    if m:
        days = int(m.group(1) or 0)
        hours = int(m.group(2) or 0)
        total_hours = days * 24 + hours
    return total_hours
