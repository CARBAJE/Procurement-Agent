"""Catalog format variants supported by the Beckn BAP normalizer."""
from __future__ import annotations

from enum import Enum, auto


class FormatVariant(Enum):
    """Known catalog response formats from BPPs / Catalog Service."""

    FLAT_RESOURCES = auto()    # Beckn v2: message.catalogs[].resources[]
    NESTED_PROVIDERS = auto()  # Legacy / mock: message.catalog.providers[].items[]
    UNKNOWN = auto()           # Unrecognised — handed to LLM fallback
