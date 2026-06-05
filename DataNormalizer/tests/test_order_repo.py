"""Unit tests for DataNormalizer.repositories.order_repo."""
from __future__ import annotations

import uuid

import pytest

from DataNormalizer.repositories import order_repo


@pytest.mark.asyncio
async def test_create_order_full_fk_chain(mock_conn):
    neg_id = uuid.uuid4()
    appr_id = uuid.uuid4()
    po_id = uuid.uuid4()
    # Three INSERTs in sequence: negotiation → approval → purchase_order.
    mock_conn.fetchrow.side_effect = [
        {"negotiation_id": neg_id},
        {"approval_id":    appr_id},
        {"po_id":          po_id},
    ]

    result = await order_repo.create_order(
        score_id=str(uuid.uuid4()),
        bpp_uuid=uuid.uuid4(),
        item_id="item-abc",
        quantity=500,
        agreed_price=150.0,
        beckn_confirm_ref="order-ref-001",
    )

    assert result == str(po_id)
    assert mock_conn.fetchrow.await_count == 3

    # Approval row arg[3] is amount_total = price × max(1, quantity)
    appr_args = mock_conn.fetchrow.await_args_list[1].args
    assert appr_args[3] == 150.0 * 500


@pytest.mark.asyncio
async def test_create_order_amount_total_clamps_quantity_to_one(mock_conn):
    mock_conn.fetchrow.side_effect = [
        {"negotiation_id": uuid.uuid4()},
        {"approval_id":    uuid.uuid4()},
        {"po_id":          uuid.uuid4()},
    ]

    await order_repo.create_order(
        score_id=str(uuid.uuid4()),
        bpp_uuid=uuid.uuid4(),
        item_id="x",
        quantity=0,
        agreed_price=50.0,
        beckn_confirm_ref="ref-zero-qty",
    )

    appr_args = mock_conn.fetchrow.await_args_list[1].args
    assert appr_args[3] == 50.0  # max(1, 0) × 50


@pytest.mark.asyncio
async def test_create_order_defaults_to_system_user(mock_conn):
    mock_conn.fetchrow.side_effect = [
        {"negotiation_id": uuid.uuid4()},
        {"approval_id":    uuid.uuid4()},
        {"po_id":          uuid.uuid4()},
    ]

    await order_repo.create_order(
        score_id=str(uuid.uuid4()),
        bpp_uuid=uuid.uuid4(),
        item_id="x",
        quantity=1,
        agreed_price=10.0,
        beckn_confirm_ref="ref-defaults",
        requester_id=None,
    )

    appr_args = mock_conn.fetchrow.await_args_list[1].args
    assert str(appr_args[2]) == order_repo.SYSTEM_USER_ID


@pytest.mark.asyncio
async def test_update_po_status_returns_po_id_when_matched(mock_conn):
    po_id = uuid.uuid4()
    mock_conn.fetchrow.return_value = {"po_id": po_id}

    result = await order_repo.update_po_status("order-ref-001", "delivered")

    assert result == str(po_id)


@pytest.mark.asyncio
async def test_update_po_status_returns_none_when_no_match(mock_conn):
    mock_conn.fetchrow.return_value = None

    result = await order_repo.update_po_status("missing-ref", "shipped")

    assert result is None


@pytest.mark.asyncio
async def test_update_po_status_rejects_invalid_state(mock_conn):
    with pytest.raises(ValueError, match="state"):
        await order_repo.update_po_status("order-ref", "invented_state")
    mock_conn.fetchrow.assert_not_called()
