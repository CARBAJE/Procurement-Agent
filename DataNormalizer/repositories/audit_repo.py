"""audit_trail_events table — INSERT only.

This is the compliance backbone (SOX 404 / GDPR / IT Act 2000, 7-year
retention). Every meaningful agent decision lands here.

NULL semantics:
  - actor_id is NULL for autonomous agent actions; set when a human acts.
  - request_id / po_id are nullable on the schema (ON DELETE SET NULL) so
    auditable events can outlive the rows they reference.
"""
from __future__ import annotations

import json
import logging
import uuid as _uuid
from typing import Any

from ..db import get_pool

logger = logging.getLogger(__name__)

VALID_EVENT_TYPES = {
    "discover", "normalize", "score", "negotiate",
    "approve", "confirm", "override", "erp_sync", "notification",
}


async def create_audit_event(
    event_type: str,
    agent_action: str,
    reasoning_payload: dict[str, Any] | None = None,
    request_id: str | None = None,
    po_id: str | None = None,
    actor_id: str | None = None,
    kafka_offset: int = 0,
) -> str:
    """INSERT into audit_trail_events. Return event_id (str UUID).

    Raises ValueError if event_type is not one of the audit_event_type enum
    values — surfaces bad inputs early instead of letting them fail at the DB.
    """
    if event_type not in VALID_EVENT_TYPES:
        raise ValueError(
            f"event_type {event_type!r} is not in {sorted(VALID_EVENT_TYPES)}"
        )
    if not agent_action:
        raise ValueError("agent_action is required")

    payload = reasoning_payload or {}

    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO audit_trail_events
                (request_id, po_id, actor_id, event_type, agent_action,
                 reasoning_payload, kafka_offset)
            VALUES ($1, $2, $3, $4::audit_event_type, $5, $6::jsonb, $7)
            RETURNING event_id
            """,
            _uuid.UUID(request_id) if request_id else None,
            _uuid.UUID(po_id) if po_id else None,
            _uuid.UUID(actor_id) if actor_id else None,
            event_type,
            agent_action,
            json.dumps(payload),
            int(kafka_offset),
        )
        return str(row["event_id"])
