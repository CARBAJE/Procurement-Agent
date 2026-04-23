"""LLM fallback normalizer for unknown catalog formats.

Follows the same instructor + Ollama pattern as IntentParser/core.py.
"""
from __future__ import annotations

import logging
import os
from typing import Optional

import instructor
from openai import OpenAI
from pydantic import BaseModel, Field

from ..beckn.models import DiscoverOffering

logger = logging.getLogger(__name__)

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434/v1")
NORMALIZER_MODEL = os.getenv("NORMALIZER_MODEL", "qwen3:1.7b")

_client = instructor.from_openai(
    OpenAI(base_url=OLLAMA_URL, api_key="ollama"),
    mode=instructor.Mode.JSON,
)

_SYSTEM_PROMPT = """
You are a catalog normalizer for a Beckn protocol procurement system.
Given a raw catalog payload from a seller (BPP), extract all product offerings.
For each offering extract: item_id, item_name, provider_id, provider_name,
price_value (as string), price_currency, and fulfillment_hours (int, optional).
Return only what you can confidently extract — use empty string for missing string fields
and null for missing optional fields.
""".strip()


class RawOffering(BaseModel):
    item_id: str = ""
    item_name: str = ""
    provider_id: str = ""
    provider_name: str = ""
    price_value: str = "0"
    price_currency: str = "INR"
    fulfillment_hours: Optional[int] = None
    rating: Optional[str] = None
    available_quantity: Optional[int] = None
    specifications: list[str] = Field(default_factory=list)


class NormalizedCatalog(BaseModel):
    offerings: list[RawOffering] = Field(default_factory=list)


class LLMFallbackNormalizer:
    def normalize(
        self, catalog: dict, bpp_id: str, bpp_uri: str
    ) -> list[DiscoverOffering]:
        """Normalize an unknown catalog format using LLM.

        Returns [] on any error — never propagates exceptions.
        """
        try:
            result: NormalizedCatalog = _client.chat.completions.create(
                model=NORMALIZER_MODEL,
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": str(catalog)},
                ],
                response_model=NormalizedCatalog,
                max_retries=3,
            )
            return [
                DiscoverOffering(
                    bpp_id=bpp_id,
                    bpp_uri=bpp_uri,
                    provider_id=o.provider_id,
                    provider_name=o.provider_name,
                    item_id=o.item_id,
                    item_name=o.item_name,
                    price_value=o.price_value,
                    price_currency=o.price_currency,
                    rating=o.rating,
                    available_quantity=o.available_quantity,
                    specifications=o.specifications,
                    fulfillment_hours=o.fulfillment_hours,
                )
                for o in result.offerings
            ]
        except Exception as exc:
            logger.warning("LLM fallback normalizer failed: %s", exc)
            return []
