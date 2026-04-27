"""Public facade for the catalog normalizer pipeline."""
from __future__ import annotations

from ..beckn.models import DiscoverOffering
from .detector import FormatDetector
from .formats import FormatVariant
from .llm_fallback import LLMFallbackNormalizer
from .schema_mapper import SchemaMapper


class CatalogNormalizer:
    def __init__(self) -> None:
        self._detector = FormatDetector()
        self._mapper = SchemaMapper()
        self._llm = LLMFallbackNormalizer()

    def normalize(
        self, payload: dict, bpp_id: str, bpp_uri: str
    ) -> list[DiscoverOffering]:
        """Normalize a raw on_discover payload into a list of DiscoverOffering.

        Pipeline:
          1. Extract catalog from payload (handles message.catalog or raw dict)
          2. Detect format variant
          3. Map deterministically (variants 1–4) or via LLM fallback (variant 5)
        """
        catalog = payload.get("message", {}).get("catalog", payload)
        variant = self._detector.detect(catalog)
        if variant != FormatVariant.UNKNOWN:
            return self._mapper.map(catalog, variant, bpp_id, bpp_uri)
        return self._llm.normalize(catalog, bpp_id, bpp_uri)
