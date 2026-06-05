"""Unit tests for DataNormalizer.repositories.audit_repo."""
from __future__ import annotations

import json
import uuid

import pytest

from DataNormalizer.repositories import audit_repo


@pytest.mark.asyncio
async def test_create_audit_event_happy_path(mock_conn):
    event_id = uuid.uuid4()
    mock_conn.fetchrow.return_value = {"event_id": event_id}

    result = await audit_repo.create_audit_event(
        event_type="normalize",
        agent_action="request_created",
        reasoning_payload={"item": "A4 paper", "quantity": 500},
        request_id=str(uuid.uuid4()),
    )

    assert result == str(event_id)
    args = mock_conn.fetchrow.await_args.args
    # args: sql, request_uuid, po_uuid, actor_uuid, event_type, action, payload_json, kafka_offset
    assert args[4] == "normalize"
    assert args[5] == "request_created"
    assert json.loads(args[6]) == {"item": "A4 paper", "quantity": 500}
    assert args[7] == 0  # default kafka_offset


@pytest.mark.asyncio
async def test_create_audit_event_rejects_invalid_event_type():
    with pytest.raises(ValueError, match="event_type"):
        await audit_repo.create_audit_event(
            event_type="not_an_event",
            agent_action="x",
        )


@pytest.mark.asyncio
async def test_create_audit_event_requires_action():
    with pytest.raises(ValueError, match="agent_action"):
        await audit_repo.create_audit_event(
            event_type="normalize",
            agent_action="",
        )


@pytest.mark.asyncio
async def test_create_audit_event_handles_optional_uuids(mock_conn):
    mock_conn.fetchrow.return_value = {"event_id": uuid.uuid4()}

    # No request_id / po_id / actor_id provided — should pass None for each.
    await audit_repo.create_audit_event(
        event_type="confirm",
        agent_action="order_confirmed",
    )

    args = mock_conn.fetchrow.await_args.args
    assert args[1] is None  # request_id
    assert args[2] is None  # po_id
    assert args[3] is None  # actor_id


@pytest.mark.asyncio
async def test_create_audit_event_accepts_empty_payload(mock_conn):
    mock_conn.fetchrow.return_value = {"event_id": uuid.uuid4()}

    await audit_repo.create_audit_event(
        event_type="override",
        agent_action="user_cancelled",
        reasoning_payload=None,
    )

    args = mock_conn.fetchrow.await_args.args
    assert json.loads(args[6]) == {}
