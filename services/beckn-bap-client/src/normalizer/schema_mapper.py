"""Schema mapper — converts raw catalog dicts to DiscoverOffering objects."""
from __future__ import annotations

from ..beckn.models import DiscoverOffering
from .formats import FormatVariant


class SchemaMapper:
    """Maps a catalog dict to a list of DiscoverOffering using the detected format."""

    def map_to_offerings(
        self,
        catalog: dict,
        bpp_id: str,
        bpp_uri: str,
        variant: FormatVariant,
    ) -> list[DiscoverOffering]:
        if variant == FormatVariant.FLAT_RESOURCES:
            return self._map_flat_resources(catalog, bpp_id, bpp_uri)
        if variant == FormatVariant.NESTED_PROVIDERS:
            return self._map_nested_providers(catalog, bpp_id, bpp_uri)
        return []

    # ── Format A: flat resources[] ────────────────────────────────────────────

    def _map_flat_resources(
        self, catalog: dict, bpp_id: str, bpp_uri: str
    ) -> list[DiscoverOffering]:
        offerings: list[DiscoverOffering] = []
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
        return offerings

    # ── Format B: providers[].items[] ─────────────────────────────────────────

    def _map_nested_providers(
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
