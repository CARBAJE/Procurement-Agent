"""Unit tests for DataNormalizer.repositories.intent_repo."""
from __future__ import annotations

import json
import uuid

import pytest

from DataNormalizer.repositories import intent_repo


@pytest.mark.asyncio
async def test_create_parsed_intent_happy_path(mock_conn):
    iid = uuid.uuid4()
    mock_conn.fetchrow.return_value = {"intent_id": iid}

    result = await intent_repo.create_parsed_intent(
        str(uuid.uuid4()), "procurement", 0.95, "qwen3:8b",
    )

    assert result == str(iid)
    args = mock_conn.fetchrow.await_args.args
    # args: sql, request_uuid, intent_class, confidence, model_version
    assert args[2] == "procurement"
    assert args[3] == 0.95
    assert args[4] == "qwen3:8b"


@pytest.mark.asyncio
async def test_create_parsed_intent_clamps_confidence_above_one(mock_conn, caplog):
    mock_conn.fetchrow.return_value = {"intent_id": uuid.uuid4()}

    with caplog.at_level("WARNING"):
        await intent_repo.create_parsed_intent(
            str(uuid.uuid4()), "procurement", 1.5, "v1",
        )

    args = mock_conn.fetchrow.await_args.args
    assert args[3] == 1.0
    assert any("confidence" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_create_parsed_intent_clamps_confidence_below_zero(mock_conn):
    mock_conn.fetchrow.return_value = {"intent_id": uuid.uuid4()}

    await intent_repo.create_parsed_intent(
        str(uuid.uuid4()), "procurement", -0.3, "v1",
    )

    assert mock_conn.fetchrow.await_args.args[3] == 0.0


@pytest.mark.asyncio
async def test_create_parsed_intent_invalid_class_defaults(mock_conn, caplog):
    mock_conn.fetchrow.return_value = {"intent_id": uuid.uuid4()}

    with caplog.at_level("WARNING"):
        await intent_repo.create_parsed_intent(
            str(uuid.uuid4()), "garbage_class", 0.5, "v1",
        )

    assert mock_conn.fetchrow.await_args.args[2] == "out_of_scope"
    assert any("intent_class 'garbage_class'" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_create_beckn_intent_applies_all_defaults(mock_conn, caplog):
    bid = uuid.uuid4()
    mock_conn.fetchrow.return_value = {"beckn_intent_id": bid}

    with caplog.at_level("WARNING"):
        # Empty beckn payload → every default should fire and log.
        await intent_repo.create_beckn_intent(str(uuid.uuid4()), {})

    args = mock_conn.fetchrow.await_args.args
    # SQL is args[0], then intent_uuid, item, descriptions, quantity, unit,
    # location_coordinates, delivery_timeline_hours, budget_min, budget_max, currency
    assert args[2] == "unknown"          # item
    assert json.loads(args[3]) == []     # descriptions
    assert args[4] == 1                  # quantity
    assert args[5] == "units"            # unit
    assert args[6] == "0.0,0.0"          # coords
    assert args[7] == 72                 # delivery_timeline_hours
    assert args[10] == "INR"             # currency

    msgs = " ".join(r.message for r in caplog.records)
    assert "beckn.item" in msgs
    assert "beckn.unit" in msgs
    assert "beckn.location_coordinates" in msgs
    assert "beckn.delivery_timeline" in msgs


@pytest.mark.asyncio
async def test_create_beckn_intent_passes_through_provided_values(mock_conn):
    mock_conn.fetchrow.return_value = {"beckn_intent_id": uuid.uuid4()}

    await intent_repo.create_beckn_intent(str(uuid.uuid4()), {
        "item": "A4 paper",
        "descriptions": ["80gsm", "white"],
        "quantity": 500,
        "unit": "ream",
        "location_coordinates": "12.97,77.59",
        "delivery_timeline": 48,
        "budget_constraints": {"min": 100, "max": 200},
    })

    args = mock_conn.fetchrow.await_args.args
    assert args[2] == "A4 paper"
    assert json.loads(args[3]) == ["80gsm", "white"]
    assert args[4] == 500
    assert args[5] == "ream"
    assert args[6] == "12.97,77.59"
    assert args[7] == 48
    assert args[8] == 100.0   # budget_min
    assert args[9] == 200.0   # budget_max
