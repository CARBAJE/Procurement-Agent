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


def _row_to_dict(row) -> dict:
    """Convert an asyncpg Record from audit_trail_events to a JSON-serialisable dict."""
    payload = row["reasoning_payload"]
    if isinstance(payload, str):
        payload = json.loads(payload)
    elif payload is None:
        payload = {}
    return {
        "event_id":          str(row["event_id"]),
        "request_id":        str(row["request_id"])  if row["request_id"]  else None,
        "po_id":             str(row["po_id"])        if row["po_id"]        else None,
        "actor_id":          str(row["actor_id"])     if row["actor_id"]     else None,
        "event_type":        row["event_type"],
        "agent_action":      row["agent_action"],
        "reasoning_payload": payload,
        "kafka_offset":      row["kafka_offset"],
        "splunk_indexed":    row["splunk_indexed"],
        "event_timestamp":   row["event_timestamp"].isoformat() if row["event_timestamp"] else None,
        "retention_until":   row["retention_until"].isoformat()  if row["retention_until"]  else None,
    }


async def get_events_by_request(request_id: str, limit: int = 100) -> list[dict]:
    """Return audit events for a request_id, ordered by event_timestamp ASC."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT event_id, request_id, po_id, actor_id, event_type, agent_action,
                   reasoning_payload, kafka_offset, splunk_indexed,
                   event_timestamp, retention_until
            FROM audit_trail_events
            WHERE request_id = $1
            ORDER BY event_timestamp ASC
            LIMIT $2
            """,
            _uuid.UUID(request_id),
            limit,
        )
    return [_row_to_dict(r) for r in rows]


async def get_events_by_po(po_id: str, limit: int = 100) -> list[dict]:
    """Return audit events for a po_id, ordered by event_timestamp ASC."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT event_id, request_id, po_id, actor_id, event_type, agent_action,
                   reasoning_payload, kafka_offset, splunk_indexed,
                   event_timestamp, retention_until
            FROM audit_trail_events
            WHERE po_id = $1
            ORDER BY event_timestamp ASC
            LIMIT $2
            """,
            _uuid.UUID(po_id),
            limit,
        )
    return [_row_to_dict(r) for r in rows]


async def get_event_by_id(event_id: str) -> dict | None:
    """Return a single audit event by event_id, or None if not found."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT event_id, request_id, po_id, actor_id, event_type, agent_action,
                   reasoning_payload, kafka_offset, splunk_indexed,
                   event_timestamp, retention_until
            FROM audit_trail_events
            WHERE event_id = $1
            """,
            _uuid.UUID(event_id),
        )
    return _row_to_dict(row) if row else None
