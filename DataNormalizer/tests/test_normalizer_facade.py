"""Unit tests for the DataNormalizer facade class — verifies that each public
method delegates to the correct repo with the right arguments. Repos themselves
are tested in test_*_repo.py.
"""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from DataNormalizer.normalizer import DataNormalizer


@pytest.fixture
def patched_repos(monkeypatch):
    """Replace each repo function with an AsyncMock and return the bundle."""
    from DataNormalizer import normalizer as facade_mod

    mocks = {
        "create_request":        AsyncMock(return_value="rid-1"),
        "create_parsed_intent":  AsyncMock(return_value="iid-1"),
        "create_beckn_intent":   AsyncMock(return_value="bid-1"),
        "create_discovery":      AsyncMock(return_value={
            "query_id": "qid-1",
            "offering_ids": [{"item_id": "item", "offering_id": "off-1"}],
        }),
        "create_scores":         AsyncMock(return_value=[{"offering_id": "off-1", "score_id": "sc-1"}]),
        "create_order":          AsyncMock(return_value="po-1"),
        "create_audit_event":    AsyncMock(return_value="ev-1"),
        "update_status":         AsyncMock(return_value=None),
        "update_po_status":      AsyncMock(return_value="po-1"),
        "_upsert_bpp":           AsyncMock(return_value="bpp-uuid"),
    }
    monkeypatch.setattr(facade_mod.request_repo, "create_request",       mocks["create_request"])
    monkeypatch.setattr(facade_mod.request_repo, "update_status",        mocks["update_status"])
    monkeypatch.setattr(facade_mod.intent_repo,  "create_parsed_intent", mocks["create_parsed_intent"])
    monkeypatch.setattr(facade_mod.intent_repo,  "create_beckn_intent",  mocks["create_beckn_intent"])
    monkeypatch.setattr(facade_mod.discovery_repo, "create_discovery",   mocks["create_discovery"])
    monkeypatch.setattr(facade_mod.discovery_repo, "_upsert_bpp",        mocks["_upsert_bpp"])
    monkeypatch.setattr(facade_mod.scoring_repo, "create_scores",        mocks["create_scores"])
    monkeypatch.setattr(facade_mod.order_repo,   "create_order",         mocks["create_order"])
    monkeypatch.setattr(facade_mod.order_repo,   "update_po_status",     mocks["update_po_status"])
    monkeypatch.setattr(facade_mod.audit_repo,   "create_audit_event",   mocks["create_audit_event"])
    return mocks


@pytest.mark.asyncio
async def test_normalize_request_delegates(patched_repos):
    result = await DataNormalizer().normalize_request("hello", channel="slack")
    assert result == {"request_id": "rid-1"}
    patched_repos["create_request"].assert_awaited_once_with("hello", "slack", None)


@pytest.mark.asyncio
async def test_normalize_intent_creates_both_rows(patched_repos):
    result = await DataNormalizer().normalize_intent(
        "rid-1", "procurement", 0.9, "v1", {"item": "x"},
    )
    assert result == {"intent_id": "iid-1", "beckn_intent_id": "bid-1"}
    patched_repos["create_parsed_intent"].assert_awaited_once()
    patched_repos["create_beckn_intent"].assert_awaited_once_with("iid-1", {"item": "x"})


@pytest.mark.asyncio
async def test_normalize_audit_delegates(patched_repos):
    result = await DataNormalizer().normalize_audit(
        event_type="confirm",
        agent_action="order_confirmed",
        reasoning_payload={"order_id": "order-1"},
        request_id="rid-1",
    )
    assert result == {"event_id": "ev-1"}
    patched_repos["create_audit_event"].assert_awaited_once_with(
        event_type="confirm",
        agent_action="order_confirmed",
        reasoning_payload={"order_id": "order-1"},
        request_id="rid-1",
        po_id=None,
        actor_id=None,
        kafka_offset=0,
    )


@pytest.mark.asyncio
async def test_normalize_po_status_delegates(patched_repos):
    result = await DataNormalizer().normalize_po_status("ref-1", "shipped")
    assert result == {"po_id": "po-1", "status": "shipped"}
    patched_repos["update_po_status"].assert_awaited_once_with("ref-1", "shipped")


@pytest.mark.asyncio
async def test_update_status_delegates(patched_repos):
    result = await DataNormalizer().update_status("rid-1", "cancelled")
    assert result == {"request_id": "rid-1", "status": "cancelled"}
    patched_repos["update_status"].assert_awaited_once_with("rid-1", "cancelled")
