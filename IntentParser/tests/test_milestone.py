"""
IntentParser — full test suite.

Sections
--------
A  Legacy milestone — Stage 1+2 integration (requires Ollama running)
   Validates that 18 natural-language queries are correctly classified
   and structured into BecknIntent payloads via the sync parse_request()
   wrapper.  These tests prove backward compatibility with the pre-refactor
   interface and are marked ``integration`` because they call a live LLM.

B  Orchestrator unit tests — Stage 1+2+3 pipeline, all infrastructure mocked.
   Tests the routing logic inside orchestrator.parse_procurement_request:
   gating, cache-hit short circuit, MCP fallback path, and recovery flow.
   No Ollama, DB, or MCP sidecar needed.

C  Stage 3 validation unit tests — database and MCP mocked at the lowest layer.
   Tests run_stage3_hybrid_validation directly: embedding, ANN query,
   three-zone thresholding, MCP probe, and Path B write dispatch.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest

# Public API (backward compat)
from IntentParser import parse_request
from IntentParser.models import (
    BecknIntent,
    BudgetConstraints,
    CacheMatch,
    ParsedIntent,
    ParseResponse,
    ValidationResult,
    ValidationZone,
)
from IntentParser.orchestrator import parse_procurement_request
from IntentParser.schemas import ParseResult
from IntentParser.validation import MCPResultAdapter, run_stage3_hybrid_validation

# ── Shared fixtures ───────────────────────────────────────────────────────────


@pytest.fixture
def parsed_intent_fixture() -> ParsedIntent:
    return ParsedIntent(
        intent="RequestQuote",
        product_name="SS Ball Valve",
        quantity=50,
        confidence=0.97,
        reasoning="Procurement request for industrial valves.",
    )


@pytest.fixture
def beckn_intent_fixture() -> BecknIntent:
    return BecknIntent(
        item="Stainless Steel Flanged Ball Valve",
        descriptions=["PN16", "2 inch", "SS316"],
        quantity=50,
        location_coordinates="12.9716,77.5946",
        delivery_timeline=168,
        budget_constraints=BudgetConstraints(max=5000.0, min=0.0),
    )


@pytest.fixture
def mock_embed_vector() -> np.ndarray:
    """384-d zero vector — shape and dtype match all-MiniLM-L6-v2 output."""
    return np.zeros(384, dtype=np.float32)


# ── Section A: Legacy milestone (Stage 1+2, requires Ollama) ─────────────────

PROCUREMENT_QUERIES = [
    "I need 500 units of A4 printer paper 80gsm delivered to Bangalore within 5 days, budget under 2 rupees per sheet",
    "Quote for 200 meters of UTP Cat6 cable for Mumbai office, delivery in 3 days, max 15 INR per meter",
    "50 stainless steel 2-inch gate valves for Chennai plant, deliver in 1 week, max 1500 INR each",
    "100 ISI-certified safety helmets for Hyderabad warehouse, within 48 hours, budget max 800 INR each",
    "10 Dell Latitude 5540 laptops for Delhi office, 7-day delivery, budget under 70000 INR per unit",
    "20 electric motors 5HP 415V for Pune factory, delivery in 2 weeks, max 12000 INR each",
    "300 HEPA H14 filters 610x610mm for Kolkata cleanroom, 10 days delivery, budget max 3500 INR each",
    "5000 M8×30 hex bolts Grade 8.8 galvanized for Mumbai docks, 4-day delivery, 5 INR per piece",
    "150 meters of hydraulic hose 1/4 inch SAE100R2 for Pune plant, within 72 hours, max 120 INR per meter",
    "200 units of 25mm PVC electrical conduit 3m length for Bangalore site, 3-day delivery, max 150 INR each",
    "1000 pairs of nitrile industrial gloves size L for Hyderabad, 48 hours delivery, under 30 INR per pair",
    "30 LED flood lights 200W IP65 for Chennai warehouse, 5-day delivery, max 2500 INR each",
    "10 compressed air cylinders 50L 150 bar for Delhi depot, 1 week delivery, max 15000 INR each",
    "500 square meters of 200GSM HDPE tarpaulin for Mumbai project, 3-day delivery, max 45 INR per sqm",
    "25 ergonomic office chairs with lumbar support for Bengaluru HQ, 10 days, budget max 8000 INR each",
    "20 rolls of 80mm thermal paper for Pune POS systems, same-day delivery, max 150 INR per roll",
]

NON_PROCUREMENT_QUERIES = [
    "Good morning, can you help me?",
    "What are your working hours?",
]


@pytest.mark.integration
@pytest.mark.parametrize("query", PROCUREMENT_QUERIES)
def test_procurement_query_yields_valid_beckn_intent(query: str) -> None:
    result = parse_request(query)
    print(f"\n{result.model_dump_json(indent=2)}")

    assert isinstance(result, ParseResult)
    assert result.intent, "intent must not be empty"
    assert result.confidence is not None
    assert result.beckn_intent is not None, (
        f"Expected a BecknIntent for procurement query:\n  {query}"
    )

    bi = result.beckn_intent
    assert bi.item.strip(),          "item must not be empty"
    assert bi.quantity > 0,          "quantity must be a positive integer"
    assert bi.delivery_timeline > 0, "delivery_timeline must be positive (hours)"
    assert bi.budget_constraints.max > 0, "budget max must be a positive number"
    assert isinstance(bi.descriptions, list), "descriptions must be a list"


@pytest.mark.integration
@pytest.mark.parametrize("query", NON_PROCUREMENT_QUERIES)
def test_non_procurement_query_has_no_beckn_intent(query: str) -> None:
    result = parse_request(query)
    print(f"\n{result.model_dump_json(indent=2)}")
    assert result.beckn_intent is None, (
        f"Expected no BecknIntent for non-procurement query:\n  {query}"
    )


# ── Section B: Orchestrator unit tests (all infrastructure mocked) ────────────


async def test_orchestrator_gates_non_procurement_query() -> None:
    """Stage 1 gate: GeneralInquiry intent must short-circuit before Stage 2."""
    non_procurement = ParsedIntent(
        intent="GeneralInquiry", confidence=0.95, reasoning="Just a greeting."
    )

    with patch("IntentParser.orchestrator.classify_intent", new_callable=AsyncMock, return_value=non_procurement):
        result = await parse_procurement_request("Good morning!")

    assert isinstance(result, ParseResponse)
    assert result.intent == "GeneralInquiry"
    assert result.beckn_intent is None
    assert result.validation is None


async def test_orchestrator_stage1_2_only_skips_stage3(
    parsed_intent_fixture: ParsedIntent,
    beckn_intent_fixture: BecknIntent,
) -> None:
    """enable_stage3=False must return a response with no validation dict."""
    with (
        patch("IntentParser.orchestrator.classify_intent", new_callable=AsyncMock, return_value=parsed_intent_fixture),
        patch("IntentParser.orchestrator.extract_beckn_intent", new_callable=AsyncMock, return_value=(beckn_intent_fixture, "qwen3:8b")),
        patch("IntentParser.orchestrator.run_stage3_hybrid_validation") as mock_stage3,
    ):
        result = await parse_procurement_request("50 SS ball valves Bangalore", enable_stage3=False)

    mock_stage3.assert_not_called()
    assert result.intent == "RequestQuote"
    assert result.beckn_intent is not None
    assert result.validation is None


async def test_orchestrator_cache_hit_returns_validated(
    parsed_intent_fixture: ParsedIntent,
    beckn_intent_fixture: BecknIntent,
) -> None:
    """P1 path: ANN similarity ≥ 0.85 → validation.status == 'VALIDATED'."""
    # Arrange
    cache_hit = ValidationResult(
        zone=ValidationZone.VALIDATED,
        top_match=CacheMatch(
            item_name="Stainless Steel Flanged Ball Valve 2 inch",
            bpp_id="bpp_industrial_001",
            similarity=0.91,
        ),
    )

    with (
        patch("IntentParser.orchestrator.classify_intent", new_callable=AsyncMock, return_value=parsed_intent_fixture),
        patch("IntentParser.orchestrator.extract_beckn_intent", new_callable=AsyncMock, return_value=(beckn_intent_fixture, "qwen3:8b")),
        patch("IntentParser.orchestrator.run_stage3_hybrid_validation", new_callable=AsyncMock, return_value=cache_hit),
    ):
        # Act
        result = await parse_procurement_request("50 SS flanged ball valves PN16 Bangalore")

    # Assert
    assert result.intent == "RequestQuote"
    assert result.beckn_intent is not None
    assert result.validation is not None
    assert result.validation["status"] == "VALIDATED"
    assert result.validation["matched"] == "Stainless Steel Flanged Ball Valve 2 inch"
    assert result.validation["similarity"] == 0.91
    assert result.validation["bpp_id"] == "bpp_industrial_001"
    assert result.recovery_log == []


async def test_orchestrator_mcp_hit_returns_mcp_validated(
    parsed_intent_fixture: ParsedIntent,
    beckn_intent_fixture: BecknIntent,
) -> None:
    """P2 path: CACHE_MISS + MCP confirms item → validation.status == 'MCP_VALIDATED'."""
    # Arrange
    mcp_hit = ValidationResult(
        zone=ValidationZone.CACHE_MISS,
        mcp_validated=True,
        mcp_item_name="UTP Cat6 Network Cable",
        mcp_bpp_id="bpp_network_001",
        mcp_bpp_uri="http://bpp-network.example.com",
    )

    with (
        patch("IntentParser.orchestrator.classify_intent", new_callable=AsyncMock, return_value=parsed_intent_fixture),
        patch("IntentParser.orchestrator.extract_beckn_intent", new_callable=AsyncMock, return_value=(beckn_intent_fixture, "qwen3:8b")),
        patch("IntentParser.orchestrator.run_stage3_hybrid_validation", new_callable=AsyncMock, return_value=mcp_hit),
    ):
        # Act
        result = await parse_procurement_request("Cat6 UTP cable 200m Mumbai")

    # Assert
    assert result.validation is not None
    assert result.validation["status"] == "MCP_VALIDATED"
    assert result.validation["matched"] == "UTP Cat6 Network Cable"
    assert result.validation["bpp_id"] == "bpp_network_001"
    assert result.validation["bpp_uri"] == "http://bpp-network.example.com"
    assert result.recovery_log == []


async def test_orchestrator_not_found_triggers_all_recovery_actions(
    parsed_intent_fixture: ParsedIntent,
    beckn_intent_fixture: BecknIntent,
) -> None:
    """P3 path: not_found=True must invoke log, notify, and RFQ; recovery_log populated."""
    # Arrange
    not_found = ValidationResult(zone=ValidationZone.CACHE_MISS, not_found=True)

    with (
        patch("IntentParser.orchestrator.classify_intent", new_callable=AsyncMock, return_value=parsed_intent_fixture),
        patch("IntentParser.orchestrator.extract_beckn_intent", new_callable=AsyncMock, return_value=(beckn_intent_fixture, "qwen3:8b")),
        patch("IntentParser.orchestrator.run_stage3_hybrid_validation", new_callable=AsyncMock, return_value=not_found),
        patch("IntentParser.orchestrator.broaden_procurement_query", new_callable=AsyncMock, return_value=None),
        patch("IntentParser.orchestrator.log_unmet_demand", new_callable=AsyncMock) as mock_log,
        patch("IntentParser.orchestrator.notify_buyer_no_stock", new_callable=AsyncMock) as mock_notify,
        patch("IntentParser.orchestrator.trigger_open_rfq_flow", new_callable=AsyncMock) as mock_rfq,
    ):
        # Act
        result = await parse_procurement_request("ASTM A790 S32750 super duplex 2-inch pipe fitting")

    # Assert — recovery side-effects
    mock_log.assert_called_once()
    mock_notify.assert_called_once()
    mock_rfq.assert_called_once()

    # Assert — response
    assert result.validation["not_found"] is True
    assert len(result.recovery_log) >= 1
    assert any("RFQ" in entry or "demand" in entry.lower() for entry in result.recovery_log)


async def test_orchestrator_broadens_query_and_retries_stage3(
    parsed_intent_fixture: ParsedIntent,
    beckn_intent_fixture: BecknIntent,
) -> None:
    """Recovery: broadening succeeds → Stage 3 retried; no RFQ triggered."""
    # Arrange
    not_found = ValidationResult(zone=ValidationZone.CACHE_MISS, not_found=True)
    broadened_intent = BecknIntent(
        item="Stainless Steel Ball Valve",
        descriptions=[],
        quantity=50,
        location_coordinates="12.9716,77.5946",
    )
    broadened_found = ValidationResult(
        zone=ValidationZone.VALIDATED,
        top_match=CacheMatch(
            item_name="Stainless Steel Ball Valve",
            bpp_id="bpp_industrial_002",
            similarity=0.88,
        ),
        broadened_item_name="Stainless Steel Ball Valve",
    )

    # Stage 3 is called twice: first returns not_found, second returns validated
    mock_stage3 = AsyncMock(side_effect=[not_found, broadened_found])

    with (
        patch("IntentParser.orchestrator.classify_intent", new_callable=AsyncMock, return_value=parsed_intent_fixture),
        patch("IntentParser.orchestrator.extract_beckn_intent", new_callable=AsyncMock, return_value=(beckn_intent_fixture, "qwen3:8b")),
        patch("IntentParser.orchestrator.run_stage3_hybrid_validation", mock_stage3),
        patch("IntentParser.orchestrator.broaden_procurement_query", new_callable=AsyncMock, return_value=broadened_intent),
        patch("IntentParser.orchestrator.log_unmet_demand", new_callable=AsyncMock) as mock_log,
        patch("IntentParser.orchestrator.trigger_open_rfq_flow", new_callable=AsyncMock) as mock_rfq,
    ):
        result = await parse_procurement_request("SS flanged ball valve ASTM A351 CF8M PN25")

    # Stage 3 called twice; recovery escalation NOT reached
    assert mock_stage3.call_count == 2
    mock_log.assert_not_called()
    mock_rfq.assert_not_called()

    assert result.validation["status"] == "VALIDATED"
    assert "Stainless Steel Ball Valve" in result.recovery_log[0]


# ── Section C: Stage 3 validation unit tests (DB + MCP mocked) ───────────────


async def test_stage3_returns_validated_on_cache_hit(
    beckn_intent_fixture: BecknIntent,
    mock_embed_vector: np.ndarray,
) -> None:
    """ANN similarity 0.91 ≥ 0.85 threshold → VALIDATED zone, no MCP call."""
    # Arrange
    high_sim_matches = [
        CacheMatch(
            item_name="Stainless Steel Flanged Ball Valve 2 inch",
            bpp_id="bpp_industrial_001",
            similarity=0.91,
        )
    ]
    mock_mcp = MagicMock()

    with (
        patch("IntentParser.validation.embed", new_callable=AsyncMock, return_value=mock_embed_vector),
        patch("IntentParser.validation.query_semantic_cache", new_callable=AsyncMock, return_value=high_sim_matches),
        patch("IntentParser.validation.get_mcp_client", return_value=mock_mcp),
    ):
        # Act
        result = await run_stage3_hybrid_validation(beckn_intent_fixture)

    # Assert
    assert result.zone == ValidationZone.VALIDATED
    assert result.top_match is not None
    assert result.top_match.item_name == "Stainless Steel Flanged Ball Valve 2 inch"
    assert result.top_match.similarity == 0.91
    assert result.mcp_validated is False
    assert result.not_found is False
    mock_mcp.search_bpp_catalog.assert_not_called()


async def test_stage3_returns_ambiguous_in_middle_band(
    beckn_intent_fixture: BecknIntent,
    mock_embed_vector: np.ndarray,
) -> None:
    """ANN similarity in [0.45, 0.85) → AMBIGUOUS zone."""
    mid_sim_matches = [
        CacheMatch(item_name="Ball Valve Stainless Steel", bpp_id="bpp_002", similarity=0.65)
    ]

    with (
        patch("IntentParser.validation.embed", new_callable=AsyncMock, return_value=mock_embed_vector),
        patch("IntentParser.validation.query_semantic_cache", new_callable=AsyncMock, return_value=mid_sim_matches),
    ):
        result = await run_stage3_hybrid_validation(beckn_intent_fixture)

    assert result.zone == ValidationZone.AMBIGUOUS
    assert result.top_match.similarity == 0.65
    assert result.mcp_validated is False


async def test_stage3_mcp_validates_on_cache_miss(
    beckn_intent_fixture: BecknIntent,
    mock_embed_vector: np.ndarray,
) -> None:
    """ANN similarity < 0.45 → MCP probe → found=True → mcp_validated=True + Path B dispatched."""
    # Arrange
    low_sim_matches = [
        CacheMatch(item_name="Unrelated Product X", bpp_id="bpp_000", similarity=0.12)
    ]
    mcp_response = {
        "found": True,
        "items": [
            {
                "item_name": "Stainless Steel Ball Valve Flanged End",
                "bpp_id": "bpp_industrial_002",
                "bpp_uri": "http://bpp-industrial.example.com",
            }
        ],
        "probe_latency_ms": 1240,
    }

    mock_mcp_client = MagicMock()
    mock_mcp_client.search_bpp_catalog = AsyncMock(return_value=mcp_response)

    with (
        patch("IntentParser.validation.embed", new_callable=AsyncMock, return_value=mock_embed_vector),
        patch("IntentParser.validation.query_semantic_cache", new_callable=AsyncMock, return_value=low_sim_matches),
        patch("IntentParser.validation.get_mcp_client", return_value=mock_mcp_client),
        patch.object(MCPResultAdapter, "write_path_b_row", new_callable=AsyncMock) as mock_path_b,
    ):
        # Act
        result = await run_stage3_hybrid_validation(beckn_intent_fixture)
        await asyncio.sleep(0)  # allow the create_task coroutine to tick

    # Assert — MCP validated
    assert result.mcp_validated is True
    assert result.mcp_item_name == "Stainless Steel Ball Valve Flanged End"
    assert result.mcp_bpp_id == "bpp_industrial_002"
    assert result.mcp_bpp_uri == "http://bpp-industrial.example.com"
    assert result.not_found is False

    # Assert — Path B write was scheduled
    mock_path_b.assert_called_once_with(
        item_name="Stainless Steel Ball Valve Flanged End",
        descriptions=beckn_intent_fixture.descriptions,
        bpp_id="bpp_industrial_002",
        bpp_uri="http://bpp-industrial.example.com",
    )


async def test_stage3_returns_not_found_when_mcp_empty(
    beckn_intent_fixture: BecknIntent,
    mock_embed_vector: np.ndarray,
) -> None:
    """ANN miss + MCP returns found=False → not_found=True."""
    low_sim_matches: list[CacheMatch] = []
    mcp_response = {"found": False, "items": [], "probe_latency_ms": 3000}

    mock_mcp_client = MagicMock()
    mock_mcp_client.search_bpp_catalog = AsyncMock(return_value=mcp_response)

    with (
        patch("IntentParser.validation.embed", new_callable=AsyncMock, return_value=mock_embed_vector),
        patch("IntentParser.validation.query_semantic_cache", new_callable=AsyncMock, return_value=low_sim_matches),
        patch("IntentParser.validation.get_mcp_client", return_value=mock_mcp_client),
    ):
        result = await run_stage3_hybrid_validation(beckn_intent_fixture)

    assert result.zone == ValidationZone.CACHE_MISS
    assert result.not_found is True
    assert result.mcp_validated is False


async def test_stage3_degrades_gracefully_on_db_error(
    beckn_intent_fixture: BecknIntent,
    mock_embed_vector: np.ndarray,
) -> None:
    """If the DB is unavailable, run_stage3_hybrid_validation falls back to MCP probe."""
    mcp_response = {
        "found": True,
        "items": [
            {
                "item_name": "Ball Valve SS316",
                "bpp_id": "bpp_fallback",
                "bpp_uri": "http://bpp-fallback.example.com",
            }
        ],
    }
    mock_mcp_client = MagicMock()
    mock_mcp_client.search_bpp_catalog = AsyncMock(return_value=mcp_response)

    with (
        patch("IntentParser.validation.embed", new_callable=AsyncMock, return_value=mock_embed_vector),
        patch("IntentParser.validation.query_semantic_cache", new_callable=AsyncMock, side_effect=ConnectionError("DB unreachable")),
        patch("IntentParser.validation.get_mcp_client", return_value=mock_mcp_client),
        patch.object(MCPResultAdapter, "write_path_b_row", new_callable=AsyncMock),
    ):
        result = await run_stage3_hybrid_validation(beckn_intent_fixture)
        await asyncio.sleep(0)

    # DB error is caught; MCP probe still runs
    assert result.mcp_validated is True
    assert result.mcp_item_name == "Ball Valve SS316"
