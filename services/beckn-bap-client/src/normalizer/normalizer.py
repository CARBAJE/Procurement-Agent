"""Public facade for the catalog normalizer pipeline."""
from __future__ import annotations

from ..beckn.models import DiscoverOffering
from .detector import FormatDetector
from .formats import FormatVariant
from .llm_fallback import LLMFallbackNormalizer
from .schema_mapper import SchemaMapper


class CatalogNormalizer:
    """Normalizes raw Beckn catalog dicts into DiscoverOffering lists.

    Pipeline:
        1. FormatDetector  — identify schema variant
        2. SchemaMapper    — deterministic field mapping for known formats
        3. LLMFallbackNormalizer — heuristic / LLM for unknown formats
    """

    def __init__(self) -> None:
        self._detector = FormatDetector()
        self._mapper = SchemaMapper()
        self._llm = LLMFallbackNormalizer()

    def normalize(
        self, catalog: dict, bpp_id: str, bpp_uri: str
    ) -> list[DiscoverOffering]:
        """Return normalized offerings from a raw catalog dict."""
        variant = self._detector.detect(catalog)
        if variant != FormatVariant.UNKNOWN:
            return self._mapper.map_to_offerings(catalog, bpp_id, bpp_uri, variant)
        return self._llm.normalize(catalog, bpp_id, bpp_uri)
