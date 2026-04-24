"""Tests for the Comparison UI split: arun_compare / arun_commit + partial graphs.

Same AsyncMock pattern as test_agent.py — drive the new partial graphs directly
with a mock BecknClient, so zero real HTTP or Ollama.
"""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from shared.models import BecknIntent, BudgetConstraints
from src.agent.graph import build_commit_graph, build_compare_graph
from src.beckn.callbacks import CallbackCollector
from src.beckn.models import (
    ConfirmResponse,
    DiscoverOffering,
    DiscoverResponse,
    InitResponse,
    OrderState,
    PaymentTerms,
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
def six_offerings():
    """Mirrors the enriched catalog diversity (6 providers, varied prices)."""
    def _make(pid, name, price, rating=None, eta=None, stock=None, specs=None):
        return DiscoverOffering(
            bpp_id=f"bpp.{pid}",
            bpp_uri=f"http://bpp-{pid}.test",
            provider_id=pid,
            provider_name=name,
            item_id=f"item-{pid}",
            item_name=f"A4 Paper from {name}",
            price_value=str(price),
            price_currency="INR",
            rating=rating,
            fulfillment_hours=eta,
            available_quantity=stock,
            specifications=specs or [],
        )

    return [
        _make("p1", "OfficeWorld",    195, "4.8", 24,   1000, ["FSC"]),
        _make("p2", "PaperDirect",    189, "4.2", 48,   5000, ["ISO 9001"]),
        _make("p3", "StationeryHub",  218, "4.9", 72,    500, ["FSC", "Acid-free"]),
        _make("p4", "GreenLeaf",      182, "4.4", 96,   2000, ["Recycled 100%"]),
        _make("p5", "QuickPrint",     205, "4.0", 24,    200, ["ISO 9001"]),
        _make("p6", "BudgetPaper",    165, "3.9", 120,  3000, []),
    ]


@pytest.fixture
def mock_client(six_offerings):
    """AsyncMock BecknClient stubbed for compare + commit paths."""
    client = AsyncMock()
    client.discover_async = AsyncMock(
        return_value=DiscoverResponse(
            transaction_id="test-txn-cmp",
            offerings=six_offerings,
        )
    )
    client.select = AsyncMock(
        return_value={"message": {"ack": {"status": "ACK"}}}
    )
    client.init = AsyncMock(
        return_value=InitResponse(
            transaction_id="test-txn-cmp",
            contract_id="test-contract-cmp",
            payment_terms=PaymentTerms(
                type="ON_FULFILLMENT",
                collected_by="BPP",
                currency="INR",
            ),
            quote_total="82500.00",
            quote_currency="INR",
        )
    )
    client.confirm = AsyncMock(
        return_value=ConfirmResponse(
            transaction_id="test-txn-cmp",
            order_id="order-cmp-001",
            state=OrderState.ACCEPTED,
            fulfillment_eta="2026-04-26T10:00:00Z",
        )
    )
    return client


@pytest.fixture
def mock_collector():
    return CallbackCollector(default_timeout=0.1)


# ── Helper runners for the two partial graphs ─────────────────────────────────


async def _run_compare(client, collector, providers, intent):
    graph = build_compare_graph(client, collector, providers,
                                discover_timeout=1.0, callback_timeout=1.0)
    return await graph.ainvoke({
        "request": intent.item,
        "intent": intent,
        "offerings": [],
        "messages": [],
        "reasoning_steps": [],
    })


async def _run_commit(client, collector, providers, state):
    graph = build_commit_graph(client, collector, providers,
                               discover_timeout=1.0, callback_timeout=1.0)
    return await graph.ainvoke(state)


# ── Compare: discover + rank only, no commit ─────────────────────────────────


async def test_compare_returns_all_offerings(
    mock_client, mock_collector, providers, sample_intent,
):
    result = await _run_compare(mock_client, mock_collector, providers, sample_intent)
    assert len(result["offerings"]) == 6


async def test_compare_recommends_cheapest(
    mock_client, mock_collector, providers, sample_intent,
):
    result = await _run_compare(mock_client, mock_collector, providers, sample_intent)
    assert result["selected"].provider_name == "BudgetPaper"
    assert result["selected"].price_value == "165"


async def test_compare_does_not_call_select_init_confirm(
    mock_client, mock_collector, providers, sample_intent,
):
    await _run_compare(mock_client, mock_collector, providers, sample_intent)
    mock_client.select.assert_not_called()
    mock_client.init.assert_not_called()
    mock_client.confirm.assert_not_called()


async def test_compare_does_not_set_order_id(
    mock_client, mock_collector, providers, sample_intent,
):
    result = await _run_compare(mock_client, mock_collector, providers, sample_intent)
    assert result.get("order_id") is None
    assert result.get("contract_id") is None


async def test_compare_emits_reasoning_steps_for_each_visited_node(
    mock_client, mock_collector, providers, sample_intent,
):
    result = await _run_compare(mock_client, mock_collector, providers, sample_intent)
    nodes = {s["node"] for s in result["reasoning_steps"]}
    assert {"parse_intent", "discover", "rank_and_select", "present_results"} <= nodes


async def test_compare_reasoning_step_carries_scoring_details(
    mock_client, mock_collector, providers, sample_intent,
):
    result = await _run_compare(mock_client, mock_collector, providers, sample_intent)
    rank_step = next(s for s in result["reasoning_steps"] if s["node"] == "rank_and_select")
    details = rank_step["details"]
    assert details["strategy"] == "price_only"
    assert details["recommended_provider"] == "BudgetPaper"
    assert details["offering_count"] == 6


# ── Commit: runs select + init + confirm from a pre-populated state ─────────


async def test_commit_runs_select_init_confirm_for_user_selection(
    mock_client, mock_collector, providers, sample_intent, six_offerings,
):
    # User picks a non-recommended offering (OfficeWorld at ₹195 instead of
    # BudgetPaper at ₹165).
    user_pick = next(o for o in six_offerings if o.provider_name == "OfficeWorld")
    state = {
        "request": sample_intent.item,
        "intent": sample_intent,
        "transaction_id": "test-txn-cmp",
        "offerings": six_offerings,
        "selected": user_pick,
        "messages": [],
        "reasoning_steps": [],
    }

    result = await _run_commit(mock_client, mock_collector, providers, state)

    mock_client.select.assert_called_once()
    mock_client.init.assert_called_once()
    mock_client.confirm.assert_called_once()

    order = mock_client.select.call_args.args[0]
    assert order.provider.id == "p1"   # OfficeWorld, NOT the recommended p6


async def test_commit_returns_order_id_and_state(
    mock_client, mock_collector, providers, sample_intent, six_offerings,
):
    state = {
        "request": sample_intent.item,
        "intent": sample_intent,
        "transaction_id": "test-txn-cmp",
        "offerings": six_offerings,
        "selected": six_offerings[0],
        "messages": [],
        "reasoning_steps": [],
    }
    result = await _run_commit(mock_client, mock_collector, providers, state)
    assert result["order_id"] == "order-cmp-001"
    assert result["order_state"] == OrderState.ACCEPTED


async def test_commit_init_and_confirm_share_contract_id(
    mock_client, mock_collector, providers, sample_intent, six_offerings,
):
    state = {
        "request": sample_intent.item,
        "intent": sample_intent,
        "transaction_id": "test-txn-cmp",
        "offerings": six_offerings,
        "selected": six_offerings[0],
        "messages": [],
        "reasoning_steps": [],
    }
    await _run_commit(mock_client, mock_collector, providers, state)
    assert (
        mock_client.init.call_args.kwargs["contract_id"]
        == mock_client.confirm.call_args.kwargs["contract_id"]
    )


async def test_commit_reasoning_steps_include_select_init_confirm(
    mock_client, mock_collector, providers, sample_intent, six_offerings,
):
    state = {
        "request": sample_intent.item,
        "intent": sample_intent,
        "transaction_id": "test-txn-cmp",
        "offerings": six_offerings,
        "selected": six_offerings[0],
        "messages": [],
        "reasoning_steps": [],
    }
    result = await _run_commit(mock_client, mock_collector, providers, state)
    nodes = {s["node"] for s in result["reasoning_steps"]}
    assert {"send_select", "send_init", "send_confirm", "present_results"} <= nodes


async def test_commit_propagates_select_error_and_skips_init_confirm(
    mock_client, mock_collector, providers, sample_intent, six_offerings,
):
    mock_client.select.side_effect = RuntimeError("/select timed out")
    state = {
        "request": sample_intent.item,
        "intent": sample_intent,
        "transaction_id": "test-txn-cmp",
        "offerings": six_offerings,
        "selected": six_offerings[0],
        "messages": [],
        "reasoning_steps": [],
    }
    result = await _run_commit(mock_client, mock_collector, providers, state)
    assert result.get("error")
    assert "/select timed out" in result["error"]
    mock_client.init.assert_not_called()
    mock_client.confirm.assert_not_called()
