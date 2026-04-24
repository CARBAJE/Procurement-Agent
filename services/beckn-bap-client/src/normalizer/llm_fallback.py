"""LLM fallback normalizer — handles unknown or exotic catalog formats."""
from __future__ import annotations

import logging

from ..beckn.models import DiscoverOffering

logger = logging.getLogger(__name__)


class LLMFallbackNormalizer:
    """Best-effort normalization for catalogs with unknown schema.

    Phase 1: heuristic field extraction (no LLM call).
    Phase 2: replace body with LLM ReAct call for complex formats.
    """

    def normalize(
        self, catalog: dict, bpp_id: str, bpp_uri: str
    ) -> list[DiscoverOffering]:
        """Try to extract offerings from an unknown catalog format."""
        logger.warning(
            "LLMFallbackNormalizer: unknown format for bpp_id=%s — attempting heuristic extraction",
            bpp_id,
        )
        offerings: list[DiscoverOffering] = []

        # Heuristic: look for any list of items at any depth
        for key, value in catalog.items():
            if isinstance(value, list) and value:
                for item in value:
                    if not isinstance(item, dict):
                        continue
                    price_val = (
                        item.get("price", {}).get("value")
                        or item.get("price_value")
                        or item.get("amount")
                        or "0"
                    )
                    offerings.append(
                        DiscoverOffering(
                            bpp_id=bpp_id,
                            bpp_uri=bpp_uri,
                            provider_id=item.get("provider_id", bpp_id),
                            provider_name=item.get("provider_name", bpp_id),
                            item_id=item.get("id", ""),
                            item_name=item.get("name", "") or item.get("descriptor", {}).get("name", ""),
                            price_value=str(price_val),
                        )
                    )
                if offerings:
                    return offerings

        logger.error("LLMFallbackNormalizer: could not extract any offerings from catalog")
        return []
