"""procurement_requests table — create and update status."""
from __future__ import annotations

import logging
import os
import uuid as _uuid

from ..db import get_pool

logger = logging.getLogger(__name__)

SYSTEM_USER_ID = os.getenv("SYSTEM_USER_ID", "00000000-0000-0000-0000-000000000001")


async def _ensure_system_user(conn) -> None:
    """Upsert a system-level user so FK on procurement_requests is always satisfied."""
    try:
        await conn.execute(
            """
            INSERT INTO users
                (user_id, email, name, role, department,
                 approval_threshold, keycloak_id, idp_provider)
            VALUES ($1, $2, $3, 'requester', 'Procurement',
                    999999.99, $4, 'keycloak')
            ON CONFLICT (user_id) DO NOTHING
            """,
            _uuid.UUID(SYSTEM_USER_ID),
            "system@procurement-agent.internal",
            "System Agent",
            "system-agent-kc-001",
        )
    except Exception:
        # email or keycloak_id unique constraint — user already exists, ignore
        pass


async def create_request(
    raw_input_text: str,
    channel: str = "web",
    requester_id: str | None = None,
) -> str:
    """INSERT into procurement_requests, return request_id (str UUID)."""
    pool = await get_pool()
    # Validate channel — DB accepts 'web', 'slack', 'teams'
    valid_channels = {"web", "slack", "teams"}
    ch = channel if channel in valid_channels else "web"
    async with pool.acquire() as conn:
        await _ensure_system_user(conn)
        rid = _uuid.UUID(requester_id) if requester_id else _uuid.UUID(SYSTEM_USER_ID)
        row = await conn.fetchrow(
            """
            INSERT INTO procurement_requests
                (requester_id, raw_input_text, channel, status)
            VALUES ($1, $2, $3::channel_type, 'draft')
            RETURNING request_id
            """,
            rid,
            raw_input_text,
            ch,
        )
        return str(row["request_id"])


async def update_status(request_id: str, status: str) -> None:
    """UPDATE procurement_requests.status lifecycle column."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE procurement_requests
            SET status = $1::procurement_status, updated_at = NOW()
            WHERE request_id = $2
            """,
            status,
            _uuid.UUID(request_id),
        )
