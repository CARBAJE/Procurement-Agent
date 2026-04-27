"""Format variant definitions and fingerprint rules for catalog detection."""
from __future__ import annotations

from enum import IntEnum
from typing import Callable


class FormatVariant(IntEnum):
    BECKN_V2_FLAT_RESOURCES = 1  # resources[] in catalog root (Format A)
    LEGACY_PROVIDERS_ITEMS = 2   # providers[].items[] (Format B)
    BPP_CATALOG_V1 = 3           # catalog.items[] with provider as string key
    ONDC_CATALOG = 4             # has fulfillments[] + tags[]
    UNKNOWN = 5                  # activates LLM fallback


def _has_resources(c: dict) -> bool:
    return isinstance(c.get("resources"), list) and len(c["resources"]) > 0


def _has_providers_items(c: dict) -> bool:
    return isinstance(c.get("providers"), list) and any(
        "items" in p for p in c["providers"]
    )


def _has_items_with_string_provider(c: dict) -> bool:
    items = c.get("items")
    return (
        isinstance(items, list)
        and len(items) > 0
        and isinstance(items[0].get("provider"), str)
    )


def _has_fulfillments_and_tags(c: dict) -> bool:
    return "fulfillments" in c and "tags" in c


# Ordered list of (variant, predicate) — first match wins.
# More specific variants must come before general ones:
# ONDC (has fulfillments+tags) is checked before LEGACY (has providers+items)
# because ONDC catalogs also contain providers[].items[].
FINGERPRINT_RULES: list[tuple[FormatVariant, Callable[[dict], bool]]] = [
    (FormatVariant.BECKN_V2_FLAT_RESOURCES, _has_resources),
    (FormatVariant.ONDC_CATALOG, _has_fulfillments_and_tags),
    (FormatVariant.LEGACY_PROVIDERS_ITEMS, _has_providers_items),
    (FormatVariant.BPP_CATALOG_V1, _has_items_with_string_provider),
]
