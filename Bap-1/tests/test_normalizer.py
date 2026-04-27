"""Tests for the CatalogNormalizer pipeline.

All tests run without Ollama — LLM fallback is mocked where needed.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.normalizer.detector import FormatDetector
from src.normalizer.formats import FormatVariant
from src.normalizer.llm_fallback import LLMFallbackNormalizer, NormalizedCatalog, RawOffering
from src.normalizer.normalizer import CatalogNormalizer
from src.normalizer.schema_mapper import SchemaMapper, _iso_duration_to_hours
from src.beckn.models import DiscoverOffering

# ── Sample payloads ───────────────────────────────────────────────────────────

FORMAT_A_CATALOG = {
    "resources": [
        {
            "id": "item-1",
            "descriptor": {"name": "A4 Paper"},
            "provider": {"id": "prov-1", "descriptor": {"name": "OfficeWorld"}},
            "price": {"value": 195.0, "currency": "INR"},
            "rating": {"ratingValue": "4.8"},
        }
    ]
}

FORMAT_B_CATALOG = {
    "providers": [
        {
            "id": "prov-2",
            "descriptor": {"name": "PaperDirect"},
            "rating": "4.5",
            "items": [
                {
                    "id": "item-2",
                    "descriptor": {"name": "A4 Paper Ream"},
                    "price": {"value": 189.0, "currency": "INR"},
                }
            ],
        }
    ]
}

FORMAT_C_CATALOG = {
    "items": [
        {
            "id": "item-3",
            "provider": "prov-3",
            "descriptor": {"name": "Bulk A4"},
            "price": {"value": 170.0, "currency": "INR"},
        }
    ]
}

FORMAT_D_CATALOG = {
    "fulfillments": [{"id": "ff-1", "TAT": "P1D"}],
    "tags": [{"code": "category", "value": "stationery"}],
    "providers": [
        {
            "id": "prov-4",
            "descriptor": {"name": "QuickShip"},
            "items": [
                {
                    "id": "item-4",
                    "descriptor": {"name": "A4 Express"},
                    "price": {"value": 210.0, "currency": "INR"},
                    "fulfillment_ids": ["ff-1"],
                }
            ],
        }
    ],
}

UNKNOWN_CATALOG = {"something_weird": True, "no_known_keys": []}

BPP_ID = "test-bpp"
BPP_URI = "http://test-bpp.example"


# ── FormatDetector tests ──────────────────────────────────────────────────────


def test_detect_format_a():
    detector = FormatDetector()
    assert detector.detect(FORMAT_A_CATALOG) == FormatVariant.BECKN_V2_FLAT_RESOURCES


def test_detect_format_b():
    detector = FormatDetector()
    assert detector.detect(FORMAT_B_CATALOG) == FormatVariant.LEGACY_PROVIDERS_ITEMS


def test_detect_format_c():
    detector = FormatDetector()
    assert detector.detect(FORMAT_C_CATALOG) == FormatVariant.BPP_CATALOG_V1


def test_detect_format_d():
    detector = FormatDetector()
    assert detector.detect(FORMAT_D_CATALOG) == FormatVariant.ONDC_CATALOG


def test_detect_unknown():
    detector = FormatDetector()
    assert detector.detect(UNKNOWN_CATALOG) == FormatVariant.UNKNOWN


# ── SchemaMapper tests ────────────────────────────────────────────────────────


def test_map_v2_flat_resources():
    mapper = SchemaMapper()
    result = mapper.map(FORMAT_A_CATALOG, FormatVariant.BECKN_V2_FLAT_RESOURCES, BPP_ID, BPP_URI)
    assert len(result) == 1
    o = result[0]
    assert isinstance(o, DiscoverOffering)
    assert o.item_id == "item-1"
    assert o.item_name == "A4 Paper"
    assert o.provider_id == "prov-1"
    assert o.provider_name == "OfficeWorld"
    assert o.price_value == "195.0"
    assert o.price_currency == "INR"
    assert o.rating == "4.8"
    assert o.bpp_id == BPP_ID
    assert o.bpp_uri == BPP_URI


def test_map_legacy_providers():
    mapper = SchemaMapper()
    result = mapper.map(FORMAT_B_CATALOG, FormatVariant.LEGACY_PROVIDERS_ITEMS, BPP_ID, BPP_URI)
    assert len(result) == 1
    o = result[0]
    assert o.item_id == "item-2"
    assert o.item_name == "A4 Paper Ream"
    assert o.provider_id == "prov-2"
    assert o.provider_name == "PaperDirect"
    assert o.price_value == "189.0"
    assert o.rating == "4.5"


def test_map_bpp_v1():
    mapper = SchemaMapper()
    result = mapper.map(FORMAT_C_CATALOG, FormatVariant.BPP_CATALOG_V1, BPP_ID, BPP_URI)
    assert len(result) == 1
    o = result[0]
    assert o.item_id == "item-3"
    assert o.item_name == "Bulk A4"
    assert o.provider_id == "prov-3"
    assert o.price_value == "170.0"


def test_map_ondc_duration_conversion():
    mapper = SchemaMapper()
    result = mapper.map(FORMAT_D_CATALOG, FormatVariant.ONDC_CATALOG, BPP_ID, BPP_URI)
    assert len(result) == 1
    o = result[0]
    assert o.item_id == "item-4"
    assert o.fulfillment_hours == 24  # P1D → 24 hours


# ── ISO duration helper tests ─────────────────────────────────────────────────


def test_iso_duration_p1d():
    assert _iso_duration_to_hours("P1D") == 24


def test_iso_duration_pt2h():
    assert _iso_duration_to_hours("PT2H") == 2


def test_iso_duration_p2dt6h():
    assert _iso_duration_to_hours("P2DT6H") == 54


# ── LLMFallbackNormalizer tests ───────────────────────────────────────────────


def test_llm_fallback_mocked():
    fallback = LLMFallbackNormalizer()
    mock_result = NormalizedCatalog(
        offerings=[
            RawOffering(
                item_id="llm-1",
                item_name="LLM Item",
                provider_id="llm-prov",
                provider_name="LLM Provider",
                price_value="99.0",
                price_currency="INR",
            )
        ]
    )
    with patch(
        "src.normalizer.llm_fallback._client.chat.completions.create",
        return_value=mock_result,
    ):
        result = fallback.normalize(UNKNOWN_CATALOG, BPP_ID, BPP_URI)

    assert len(result) == 1
    assert result[0].item_id == "llm-1"
    assert result[0].item_name == "LLM Item"
    assert result[0].bpp_id == BPP_ID


def test_llm_fallback_returns_empty_on_error():
    fallback = LLMFallbackNormalizer()
    with patch(
        "src.normalizer.llm_fallback._client.chat.completions.create",
        side_effect=RuntimeError("Ollama unavailable"),
    ):
        result = fallback.normalize(UNKNOWN_CATALOG, BPP_ID, BPP_URI)

    assert result == []


# ── CatalogNormalizer routing tests ──────────────────────────────────────────


def test_normalizer_routes_to_mapper_on_known():
    """Format A payload → mapper is called, LLM is not called."""
    normalizer = CatalogNormalizer()
    payload = {"message": {"catalog": FORMAT_A_CATALOG}}

    with patch.object(normalizer._mapper, "map", wraps=normalizer._mapper.map) as mock_map, \
         patch.object(normalizer._llm, "normalize") as mock_llm:
        result = normalizer.normalize(payload, BPP_ID, BPP_URI)

    mock_map.assert_called_once()
    mock_llm.assert_not_called()
    assert len(result) == 1


def test_normalizer_routes_to_llm_on_unknown():
    """Unknown structure → LLM fallback is called, mapper is not called."""
    normalizer = CatalogNormalizer()
    payload = {"message": {"catalog": UNKNOWN_CATALOG}}

    with patch.object(normalizer._mapper, "map") as mock_map, \
         patch.object(normalizer._llm, "normalize", return_value=[]) as mock_llm:
        result = normalizer.normalize(payload, BPP_ID, BPP_URI)

    mock_map.assert_not_called()
    mock_llm.assert_called_once()
    assert result == []


# ── Client integration test ───────────────────────────────────────────────────


async def test_client_uses_normalizer(adapter):
    """discover_async() returns DiscoverOfferings via CatalogNormalizer."""
    from aioresponses import aioresponses
    from src.beckn.client import BecknClient
    from src.beckn.callbacks import CallbackCollector
    from src.beckn.models import BecknIntent, BudgetConstraints, DiscoverResponse

    intent = BecknIntent(item="A4 paper", quantity=100, delivery_timeline=72)
    collector = CallbackCollector(default_timeout=0.5)
    txn_id = "test-txn-normalizer"

    # Simulate an on_discover callback with Format A catalog
    fake_callback = {
        "context": {
            "action": "on_discover",
            "bap_id": "test-bap",
            "bap_uri": "http://localhost:8000/beckn",
            "bpp_id": BPP_ID,
            "bpp_uri": BPP_URI,
            "transaction_id": txn_id,
            "message_id": "msg-1",
            "timestamp": "2024-01-01T00:00:00.000Z",
        },
        "message": {
            "catalog": FORMAT_A_CATALOG,
        },
    }

    from src.beckn.models import CallbackPayload
    collector.register(txn_id, "on_discover")
    await collector._queues[(txn_id, "on_discover")].put(
        CallbackPayload.model_validate(fake_callback)
    )

    DISCOVER_URL = adapter.discover_url
    with aioresponses() as mock:
        mock.post(DISCOVER_URL, payload={"message": {"ack": {"status": "ACK"}}})
        async with BecknClient(adapter) as client:
            # Manually trigger _build_discover_response with our pre-filled collector
            callbacks = await collector.collect(txn_id, "on_discover", timeout=1.0)
            collector.cleanup(txn_id, "on_discover")
            response = client._build_discover_response(txn_id, callbacks)

    assert isinstance(response, DiscoverResponse)
    assert len(response.offerings) == 1
    assert response.offerings[0].item_name == "A4 Paper"
    assert response.offerings[0].bpp_id == BPP_ID
