"""Unit tests for DataNormalizer.repositories.request_repo."""
from __future__ import annotations

import uuid

import pytest

from DataNormalizer.repositories import request_repo


@pytest.mark.asyncio
async def test_create_request_happy_path(mock_conn):
    rid = uuid.uuid4()
    mock_conn.fetchrow.return_value = {"request_id": rid}

    result = await request_repo.create_request("500 reams A4 paper", channel="web")

    assert result == str(rid)
    # _ensure_system_user is the first execute; create_request fetchrow is the next.
    assert mock_conn.execute.await_count == 1
    assert mock_conn.fetchrow.await_count == 1
    insert_args = mock_conn.fetchrow.await_args.args
    # args: (sql, requester_id, raw_input_text, channel)
    assert insert_args[2] == "500 reams A4 paper"
    assert insert_args[3] == "web"


@pytest.mark.asyncio
async def test_create_request_invalid_channel_defaults_to_web(mock_conn, caplog):
    mock_conn.fetchrow.return_value = {"request_id": uuid.uuid4()}

    with caplog.at_level("WARNING"):
        await request_repo.create_request("hello", channel="carrier-pigeon")

    insert_args = mock_conn.fetchrow.await_args.args
    assert insert_args[3] == "web"
    assert any("channel 'carrier-pigeon'" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_create_request_uses_system_user_when_no_requester(mock_conn):
    mock_conn.fetchrow.return_value = {"request_id": uuid.uuid4()}

    await request_repo.create_request("hello", channel="web", requester_id=None)

    insert_args = mock_conn.fetchrow.await_args.args
    # requester_id is positional arg[1], should equal SYSTEM_USER_ID as UUID
    assert str(insert_args[1]) == request_repo.SYSTEM_USER_ID


@pytest.mark.asyncio
async def test_update_status_executes_update(mock_conn):
    rid = str(uuid.uuid4())
    await request_repo.update_status(rid, "cancelled")

    assert mock_conn.execute.await_count == 1
    sql, status, request_uuid = mock_conn.execute.await_args.args
    assert "UPDATE procurement_requests" in sql
    assert status == "cancelled"
    assert str(request_uuid) == rid
