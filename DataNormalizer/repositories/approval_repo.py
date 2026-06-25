"""procurement_requests approval workflow helpers.

Two lightweight functions used by Bap-1/src/server.py to persist approval
state without changing the rest of the DataNormalizer flow.
"""
from __future__ import annotations

import logging
import uuid as _uuid

logger = logging.getLogger(__name__)


async def mark_pending(
    conn,
    request_id: str,
    chosen_item_id: str,
    transaction_id: str,
) -> None:
    """Set status='pending_approval' and store the resume keys on the request row."""
    await conn.execute(
        """
        UPDATE procurement_requests
        SET
            status                   = 'pending_approval'::procurement_status,
            pending_chosen_item_id   = $2,
            pending_transaction_id   = $3,
            updated_at               = NOW()
        WHERE request_id = $1
        """,
        _uuid.UUID(request_id),
        chosen_item_id,
        transaction_id,
    )
    logger.info(
        "[approval_repo] request %s → pending_approval (item=%s, txn=%s)",
        request_id, chosen_item_id, transaction_id,
    )


async def mark_decided(
    conn,
    request_id: str,
    decision: str,
) -> None:
    """Set status='confirmed' or 'cancelled' after an approver's decision.

    `decision` must be 'approved' or 'rejected'.
    """
    target_status = "confirmed" if decision == "approved" else "cancelled"
    await conn.execute(
        """
        UPDATE procurement_requests
        SET
            status     = $2::procurement_status,
            updated_at = NOW()
        WHERE request_id = $1
        """,
        _uuid.UUID(request_id),
        target_status,
    )
    logger.info(
        "[approval_repo] request %s → %s (decision=%s)",
        request_id, target_status, decision,
    )
