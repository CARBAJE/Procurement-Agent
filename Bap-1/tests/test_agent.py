"""Unit tests for the Procurement ReAct Agent.

All tests use AsyncMock for BecknClient and mock parse_nl_to_intent.
Zero real HTTP calls or Ollama calls.

Phase 2: the graph now runs discover → select → init → confirm, so the mock
client stubs .init and .confirm alongside .discover_async and .select.

Run:
    pytest tests/test_agent.py -v
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from shared.models import BecknIntent, BudgetConstraints
from src.agent import ProcurementAgent, ProcurementState
from src.agent.graph import build_graph
from src.beckn.callbacks import CallbackCollector
from src.beckn.models import (
    ConfirmResponse,
    DiscoverOffering,
    DiscoverResponse,
    InitResponse,
    OrderState,
    PaymentTerms,
    StatusResponse,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def sample_intent():
    return BecknIntent(
        item="A4 paper 80gsm",
        descriptions=["A4", "80gsm"],
        quantity=500,
        location_coordinates="12.9716,77.5946",
        delivery_timeline=72,
        budget_constraints=BudgetConstraints(max=200.0),
    )


@pytest.fixture
def three_offerings():
    def _make(bpp_id, name, price):
        return DiscoverOffering(
            bpp_id=bpp_id,
            bpp_uri=f"http://{bpp_id}.test",
            provider_id=bpp_id,
            provider_name=name,
            item_id="item-a4-ream",
            item_name="A4 Paper Ream",
            price_value=str(price),
            price_currency="INR",
        )

    return [
        _make("p1", "OfficeWorld",    195),
        _make("p2", "PaperDirect",    189),
        _make("p3", "StationeryHub",  201),
    ]


@pytest.fixture
def mock_client(three_offerings):
    """AsyncMock BecknClient stubbed for the full Phase 2 flow."""
    client = AsyncMock()
    client.discover_async = AsyncMock(
        return_value=DiscoverResponse(
            transaction_id="test-txn-001",
            offerings=three_offerings,
        )
    )
    client.select = AsyncMock(
        return_value={"message": {"ack": {"status": "ACK"}}}
    )
    client.init = AsyncMock(
        return_value=InitResponse(
            transaction_id="test-txn-001",
            contract_id="test-contract-001",
            payment_terms=PaymentTerms(
                type="ON_FULFILLMENT",
                collected_by="BPP",
                currency="INR",
            ),
            quote_total="189.00",
            quote_currency="INR",
        )
    )
    client.confirm = AsyncMock(
        return_value=ConfirmResponse(
            transaction_id="test-txn-001",
            order_id="order-test-001",
            state=OrderState.ACCEPTED,
            fulfillment_eta="2026-04-26T10:00:00Z",
        )
    )
    client.status = AsyncMock(
        return_value=StatusResponse(
            transaction_id="test-txn-001",
            order_id="order-test-001",
            state=OrderState.SHIPPED,
        )
    )
    return client


@pytest.fixture
def mock_collector():
    return CallbackCollector(default_timeout=0.1)


# ── Helper ────────────────────────────────────────────────────────────────────


async def _run(mock_client, mock_collector, providers, intent=None, request="test query"):
    """Run the graph with a mock client. Pre-loading intent skips NLP."""
    graph = build_graph(
        mock_client,
        mock_collector,
        providers,
        discover_timeout=1.0,
        callback_timeout=1.0,
    )
    return await graph.ainvoke(
        {
            "request": request,
            "intent": intent,
            "offerings": [],
            "messages": [],
        }
    )


# ── Tests: Phase 1 flow (still passing) ──────────────────────────────────────


async def test_initial_state_all_fields_present(
    mock_client, mock_collector, providers, sample_intent
):
    result = await _run(mock_client, mock_collector, providers, intent=sample_intent)
    for field in ("request", "intent", "transaction_id", "offerings",
                  "selected", "select_ack", "messages"):
        assert field in result, f"Missing field: {field!r}"
    assert result.get("error") is None


async def test_parse_intent_skipped_when_pre_loaded(
    mock_client, mock_collector, providers, sample_intent
):
    with patch("src.agent.nodes.parse_nl_to_intent") as mock_parse:
        await _run(mock_client, mock_collector, providers, intent=sample_intent)
        mock_parse.assert_not_called()


async def test_parse_intent_calls_facade(
    mock_client, mock_collector, providers, sample_intent
):
    with patch(
        "src.agent.nodes.parse_nl_to_intent", return_value=sample_intent
    ) as mock_parse:
        await _run(
            mock_client, mock_collector, providers,
            intent=None, request="500 reams A4 paper",
        )
        mock_parse.assert_called_once_with("500 reams A4 paper")


async def test_discover_returns_3_plus_offerings(
    mock_client, mock_collector, providers, sample_intent
):
    result = await _run(mock_client, mock_collector, providers, intent=sample_intent)
    assert len(result["offerings"]) >= 3


async def test_rank_selects_cheapest(
    mock_client, mock_collector, providers, sample_intent
):
    result = await _run(mock_client, mock_collector, providers, intent=sample_intent)
    assert result["selected"] is not None
    assert result["selected"].provider_name == "PaperDirect"
    assert result["selected"].price_value == "189"


async def test_discover_called_with_correct_intent(
    mock_client, mock_collector, providers, sample_intent
):
    await _run(mock_client, mock_collector, providers, intent=sample_intent)
    mock_client.discover_async.assert_called_once()
    called_intent = mock_client.discover_async.call_args.args[0]
    assert called_intent == sample_intent


async def test_transaction_id_propagated(
    mock_client, mock_collector, providers, sample_intent
):
    result = await _run(mock_client, mock_collector, providers, intent=sample_intent)
    assert result["transaction_id"] == "test-txn-001"


async def test_select_called_with_cheapest_provider(
    mock_client, mock_collector, providers, sample_intent
):
    await _run(mock_client, mock_collector, providers, intent=sample_intent)
    mock_client.select.assert_called_once()
    order = mock_client.select.call_args.args[0]
    assert order.provider.id == "p2"           # PaperDirect
    assert order.items[0].quantity == 500


async def test_select_ack_stored_in_state(
    mock_client, mock_collector, providers, sample_intent
):
    result = await _run(mock_client, mock_collector, providers, intent=sample_intent)
    assert result["select_ack"] == {"message": {"ack": {"status": "ACK"}}}


async def test_empty_discover_skips_select(
    mock_client, mock_collector, providers, sample_intent
):
    mock_client.discover_async.return_value = DiscoverResponse(
        transaction_id="test-txn-empty", offerings=[]
    )
    result = await _run(mock_client, mock_collector, providers, intent=sample_intent)
    mock_client.select.assert_not_called()
    mock_client.init.assert_not_called()
    mock_client.confirm.assert_not_called()
    assert result.get("error") is None
    assert result.get("selected") is None


async def test_discover_exception_captured(
    mock_client, mock_collector, providers, sample_intent
):
    mock_client.discover_async.side_effect = RuntimeError("ONIX unreachable")
    result = await _run(mock_client, mock_collector, providers, intent=sample_intent)
    assert result["error"] is not None
    assert "ONIX unreachable" in result["error"]
    mock_client.select.assert_not_called()


async def test_select_exception_captured(
    mock_client, mock_collector, providers, sample_intent
):
    mock_client.select.side_effect = RuntimeError("/select timed out")
    result = await _run(mock_client, mock_collector, providers, intent=sample_intent)
    assert result["error"] is not None
    assert "/select timed out" in result["error"]
    assert result["selected"] is not None   # selected was set before the error
    mock_client.init.assert_not_called()     # init skipped on prior error
    mock_client.confirm.assert_not_called()


async def test_messages_trace_contains_all_node_tags(
    mock_client, mock_collector, providers, sample_intent
):
    result = await _run(mock_client, mock_collector, providers, intent=sample_intent)
    trace = "\n".join(result["messages"])
    for tag in (
        "[parse_intent]",
        "[discover]",
        "[rank_and_select]",
        "[send_select]",
        "[send_init]",
        "[send_confirm]",
        "[present_results]",
    ):
        assert tag in trace, f"Tag {tag!r} missing from reasoning trace"


async def test_messages_are_ordered(
    mock_client, mock_collector, providers, sample_intent
):
    result = await _run(mock_client, mock_collector, providers, intent=sample_intent)
    trace = "\n".join(result["messages"])
    tags = [
        "[parse_intent]",
        "[discover]",
        "[rank_and_select]",
        "[send_select]",
        "[send_init]",
        "[send_confirm]",
        "[present_results]",
    ]
    positions = [trace.find(tag) for tag in tags]
    assert all(p != -1 for p in positions), "One or more node tags missing"
    assert positions == sorted(positions), "Node tags not in execution order"


# ── Tests: Phase 2 — init + confirm + status ─────────────────────────────────


async def test_init_called_after_select(
    mock_client, mock_collector, providers, sample_intent
):
    await _run(mock_client, mock_collector, providers, intent=sample_intent)
    mock_client.init.assert_called_once()
    kwargs = mock_client.init.call_args.kwargs
    assert kwargs["transaction_id"] == "test-txn-001"
    assert kwargs["bpp_id"] == "p2"                    # cheapest provider
    assert kwargs["billing"].name == "Test Buyer"      # from provider
    assert kwargs["fulfillment"].end_location == "12.9716,77.5946"


async def test_init_uses_contract_id_from_select(
    mock_client, mock_collector, providers, sample_intent
):
    result = await _run(mock_client, mock_collector, providers, intent=sample_intent)
    contract_id = result.get("contract_id")
    assert contract_id is not None
    # init and confirm must use the same contract_id — it links them.
    assert mock_client.init.call_args.kwargs["contract_id"] == contract_id
    assert mock_client.confirm.call_args.kwargs["contract_id"] == contract_id


async def test_confirm_uses_payment_terms_from_init(
    mock_client, mock_collector, providers, sample_intent
):
    """confirm must use the final terms from on_init, not the initial proposal."""
    await _run(mock_client, mock_collector, providers, intent=sample_intent)
    mock_client.confirm.assert_called_once()
    payment = mock_client.confirm.call_args.kwargs["payment"]
    assert payment.type == "ON_FULFILLMENT"
    assert payment.collected_by == "BPP"


async def test_order_id_stored_in_state(
    mock_client, mock_collector, providers, sample_intent
):
    result = await _run(mock_client, mock_collector, providers, intent=sample_intent)
    assert result.get("order_id") == "order-test-001"
    assert result.get("order_state") == OrderState.ACCEPTED


async def test_init_exception_captured(
    mock_client, mock_collector, providers, sample_intent
):
    mock_client.init.side_effect = RuntimeError("/init timed out")
    result = await _run(mock_client, mock_collector, providers, intent=sample_intent)
    assert result["error"] is not None
    assert "/init timed out" in result["error"]
    mock_client.confirm.assert_not_called()   # confirm skipped on prior error


async def test_confirm_exception_captured(
    mock_client, mock_collector, providers, sample_intent
):
    mock_client.confirm.side_effect = RuntimeError("on_confirm never arrived")
    result = await _run(mock_client, mock_collector, providers, intent=sample_intent)
    assert result["error"] is not None
    assert "on_confirm never arrived" in result["error"]
    assert result.get("order_id") is None


async def test_confirm_failure_falls_back_to_cod(
    mock_client, mock_collector, providers, sample_intent
):
    """If on_init returns no payment terms, node falls back to provider's COD."""
    mock_client.init.return_value = InitResponse(
        transaction_id="test-txn-001",
        contract_id="test-contract-001",
        payment_terms=None,   # BPP didn't echo back payment
        raw_message={},
    )
    await _run(mock_client, mock_collector, providers, intent=sample_intent)
    mock_client.confirm.assert_called_once()
    payment = mock_client.confirm.call_args.kwargs["payment"]
    assert payment.type == "ON_FULFILLMENT"
    assert payment.collected_by == "BPP"
