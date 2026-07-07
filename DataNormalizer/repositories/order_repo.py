"""purchase_orders table — full FK chain: score → negotiation → approval → PO."""
from __future__ import annotations

import logging
import os
import uuid as _uuid
from datetime import datetime

from ..db import get_pool

logger = logging.getLogger(__name__)

SYSTEM_USER_ID = os.getenv("SYSTEM_USER_ID", "00000000-0000-0000-0000-000000000001")

VALID_PO_STATUSES = {"pending", "confirmed", "shipped", "delivered", "cancelled"}


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
    fulfillment_eta: str | None = None,
    request_id: str | None = None,
    original_price: float | None = None,
) -> str:
    """Create negotiation_outcome + approval_decision + purchase_order in one tx.

    When original_price differs from agreed_price (negotiation happened),
    negotiation_outcomes records initial=original_price, final=agreed_price so
    the analytics savings query computes the correct discount.

    Returns po_id (str UUID).
    """
    pool = await get_pool()
    rid = _uuid.UUID(requester_id) if requester_id else _uuid.UUID(SYSTEM_USER_ID)
    req_uuid = _uuid.UUID(request_id) if request_id else None

    initial_price = original_price if original_price and original_price > 0 else agreed_price
    negotiated = initial_price > agreed_price
    strategy   = "accept_margin" if negotiated else "skipped"
    acceptance = "accepted"      if negotiated else "skipped"
    discount_pct = round((initial_price - agreed_price) / initial_price * 100, 2) if negotiated and initial_price > 0 else 0.0

    # asyncpg binds timestamptz params as datetime objects, not ISO strings.
    eta_dt = None
    if fulfillment_eta:
        try:
            eta_dt = datetime.fromisoformat(fulfillment_eta)
        except (TypeError, ValueError):
            logger.warning(
                "[order_repo] unparseable fulfillment_eta %r — storing NULL",
                fulfillment_eta,
            )

    async with pool.acquire() as conn:
        async with conn.transaction():
            # 1. negotiation_outcomes — records actual negotiation savings
            neg = await conn.fetchrow(
                """
                INSERT INTO negotiation_outcomes (
                    score_id, strategy_applied, initial_price,
                    final_price, discount_percent, acceptance_status
                )
                VALUES ($1, $2, $3, $4, $5, $6)
                RETURNING negotiation_id
                """,
                _uuid.UUID(score_id),
                strategy,
                initial_price,
                agreed_price,
                discount_pct,
                acceptance,
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

            # 3. purchase_orders — direct request_id FK for simpler analytics JOIN
            po = await conn.fetchrow(
                """
                INSERT INTO purchase_orders (
                    approval_id, bpp_id, item_id, quantity, unit,
                    agreed_price, currency, delivery_terms,
                    beckn_confirm_ref, status, fulfillment_eta, request_id
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, 'pending', $10, $11)
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
                eta_dt,
                req_uuid,
            )
            return str(po["po_id"])


async def update_po_status(beckn_confirm_ref: str, state: str) -> str | None:
    """UPDATE purchase_orders.status by beckn_confirm_ref. Returns po_id or None.

    Raises ValueError if state is not a valid po_status_type enum value.
    Returns None when no row matched the beckn_confirm_ref (caller decides
    whether that should be a 404 or silent).
    """
    if state not in VALID_PO_STATUSES:
        raise ValueError(
            f"state {state!r} is not in {sorted(VALID_PO_STATUSES)}"
        )
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            UPDATE purchase_orders
            SET status = $1::po_status_type
            WHERE beckn_confirm_ref = $2
            RETURNING po_id
            """,
            state,
            beckn_confirm_ref,
        )
        return str(row["po_id"]) if row else None
