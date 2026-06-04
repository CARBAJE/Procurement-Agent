"""Unit tests for DataNormalizer.repositories.discovery_repo."""
from __future__ import annotations

import uuid

import pytest

from DataNormalizer.repositories import discovery_repo


@pytest.mark.asyncio
async def test_upsert_bpp_returns_existing(mock_conn):
    existing_id = uuid.uuid4()
    mock_conn.fetchrow.return_value = {"bpp_id": existing_id}

    result = await discovery_repo._upsert_bpp(
        mock_conn, "http://bpp-1.test", "ProviderOne", "beckn-default",
    )
    assert result == existing_id
    # Should have done one SELECT and one UPDATE — no INSERT
    assert mock_conn.execute.await_count == 1


@pytest.mark.asyncio
async def test_upsert_bpp_creates_new_when_missing(mock_conn):
    new_id = uuid.uuid4()
    # First fetchrow (SELECT) → None (not found). Second (INSERT … RETURNING) → row.
    mock_conn.fetchrow.side_effect = [None, {"bpp_id": new_id}]

    result = await discovery_repo._upsert_bpp(
        mock_conn, "http://new-bpp.test", "NewProvider", "beckn-default",
    )
    assert result == new_id
    assert mock_conn.fetchrow.await_count == 2


@pytest.mark.asyncio
async def test_create_discovery_inserts_query_and_offerings(mock_conn):
    query_uuid = uuid.uuid4()
    bpp_uuid = uuid.uuid4()
    offering_uuid = uuid.uuid4()

    # 1. discovery_queries INSERT.
    # 2. _upsert_bpp SELECT (found).
    # 3. seller_offerings INSERT.
    mock_conn.fetchrow.side_effect = [
        {"query_id": query_uuid},
        {"bpp_id": bpp_uuid},
        {"offering_id": offering_uuid},
    ]

    result = await discovery_repo.create_discovery(
        beckn_intent_id=str(uuid.uuid4()),
        network_id="beckn-default",
        offerings=[{
            "bpp_uri":          "http://bpp-1.test",
            "provider_name":    "ProviderOne",
            "item_id":          "item-abc",
            "price_value":      "150.00",
            "price_currency":   "INR",
            "fulfillment_hours": 48,
            "rating":            "4.5",
        }],
    )

    assert result["query_id"] == str(query_uuid)
    assert result["offering_ids"] == [
        {"item_id": "item-abc", "offering_id": str(offering_uuid)},
    ]


@pytest.mark.asyncio
async def test_create_discovery_clamps_negative_delivery_eta(mock_conn, caplog):
    mock_conn.fetchrow.side_effect = [
        {"query_id": uuid.uuid4()},
        {"bpp_id": uuid.uuid4()},
        {"offering_id": uuid.uuid4()},
    ]

    with caplog.at_level("WARNING"):
        await discovery_repo.create_discovery(
            beckn_intent_id=str(uuid.uuid4()),
            network_id="beckn-default",
            offerings=[{
                "bpp_uri":          "http://bpp.test",
                "provider_name":    "X",
                "item_id":          "i",
                "price_value":      "1",
                "fulfillment_hours": -5,
            }],
        )

    # 3rd fetchrow call is the offering INSERT; arg[6] is delivery_eta_hours.
    third_call_args = mock_conn.fetchrow.await_args_list[2].args
    assert third_call_args[6] == 1
    assert any("fulfillment_hours" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_create_discovery_non_numeric_price_defaults_to_zero(mock_conn, caplog):
    mock_conn.fetchrow.side_effect = [
        {"query_id": uuid.uuid4()},
        {"bpp_id": uuid.uuid4()},
        {"offering_id": uuid.uuid4()},
    ]

    with caplog.at_level("WARNING"):
        await discovery_repo.create_discovery(
            beckn_intent_id=str(uuid.uuid4()),
            network_id="beckn-default",
            offerings=[{
                "bpp_uri":     "http://bpp.test",
                "provider_name": "X",
                "item_id":     "i",
                "price_value": "not-a-number",
            }],
        )

    third_call_args = mock_conn.fetchrow.await_args_list[2].args
    assert third_call_args[4] == 0.0   # price
    assert any("non-numeric price_value" in r.message for r in caplog.records)
