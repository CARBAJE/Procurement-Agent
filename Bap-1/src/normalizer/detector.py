"""Format detector — pure function, no IO, no LLM."""
from __future__ import annotations

from .formats import FINGERPRINT_RULES, FormatVariant


class FormatDetector:
    def detect(self, catalog: dict) -> FormatVariant:
        """Detect format variant by iterating fingerprint rules.

        Returns the first matching variant or UNKNOWN.
        """
        for variant, predicate in FINGERPRINT_RULES:
            if predicate(catalog):
                return variant
        return FormatVariant.UNKNOWN
