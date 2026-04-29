"""purchase_orders table — full FK chain: score → negotiation → approval → PO."""
from __future__ import annotations

import logging
import os
import uuid as _uuid

from ..db import get_pool

logger = logging.getLogger(__name__)

SYSTEM_USER_ID = os.getenv("SYSTEM_USER_ID", "00000000-0000-0000-0000-000000000001")


async def create_order(
    score_id: str,
    bpp_uuid: _uuid.UUID,
    item_id: str,
    quantity: int,
    agreed_price: float,
    beckn_confirm_ref: str,
    delivery_terms: str = "Standard delivery",
    currency: str = "INR",
    unit: str = "units",
    requester_id: str | None = None,
) -> str:
    """Create negotiation_outcome + approval_decision + purchase_order in one tx.

    negotiation uses strategy='skipped' / acceptance='skipped' (Beckn /confirm
    was already sent by beckn-bap-client; no negotiation step ran).
    approval uses level='auto' / status='auto_approved'.

    Returns po_id (str UUID).
    """
    pool = await get_pool()
    rid = _uuid.UUID(requester_id) if requester_id else _uuid.UUID(SYSTEM_USER_ID)

    async with pool.acquire() as conn:
        async with conn.transaction():
            # 1. negotiation_outcomes — skipped (direct confirm)
            neg = await conn.fetchrow(
                """
                INSERT INTO negotiation_outcomes (
                    score_id, strategy_applied, initial_price,
                    final_price, discount_percent, acceptance_status
                )
                VALUES ($1, 'skipped', $2, $2, 0.0, 'skipped')
                RETURNING negotiation_id
                """,
                _uuid.UUID(score_id),
                agreed_price,
            )
            negotiation_id = neg["negotiation_id"]

            # 2. approval_decisions — auto approved
            appr = await conn.fetchrow(
                """
                INSERT INTO approval_decisions (
                    negotiation_id, requester_id, approval_level,
                    amount_total, status, notification_channel, decided_at
                )
                VALUES ($1, $2, 'auto', $3, 'auto_approved', 'slack', NOW())
                RETURNING approval_id
                """,
                negotiation_id,
                rid,
                agreed_price * max(1, quantity),
            )
            approval_id = appr["approval_id"]

            # 3. purchase_orders
            po = await conn.fetchrow(
                """
                INSERT INTO purchase_orders (
                    approval_id, bpp_id, item_id, quantity, unit,
                    agreed_price, currency, delivery_terms,
                    beckn_confirm_ref, status
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, 'pending')
                RETURNING po_id
                """,
                approval_id,
                bpp_uuid,
                item_id,
                quantity,
                unit,
                agreed_price,
                currency,
                delivery_terms,
                beckn_confirm_ref,
            )
            return str(po["po_id"])
