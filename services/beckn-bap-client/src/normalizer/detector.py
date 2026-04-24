"""Format detector — identifies which catalog schema a BPP response uses."""
from __future__ import annotations

from .formats import FormatVariant


class FormatDetector:
    """Inspects a catalog dict and returns the matching FormatVariant."""

    def detect(self, catalog: dict) -> FormatVariant:
        """Detect format from catalog dict keys.

        Format A (Beckn v2 real network): contains 'resources' list.
        Format B (mock / legacy): contains 'providers' list.
        """
        if catalog.get("resources"):
            return FormatVariant.FLAT_RESOURCES
        if catalog.get("providers"):
            return FormatVariant.NESTED_PROVIDERS
        return FormatVariant.UNKNOWN
