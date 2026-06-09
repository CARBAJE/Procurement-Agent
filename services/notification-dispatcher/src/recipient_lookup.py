"""Resolve a Beckn order_id to the requester's email by querying PostgreSQL.

We chain back from `purchase_orders.beckn_confirm_ref` (= the Beckn order_id
the orchestrator publishes in every event) through the approval/negotiation
chain to `users.email`. The Beckn transaction_id is NOT a column in the DB,
but order_id is unique and gets us there.

Falls back to None if no email can be resolved or DB is unavailable.
"""
from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)

_QUERY = """
SELECT u.email
FROM purchase_orders po
JOIN approval_decisions ad   ON ad.approval_id  = po.approval_id
JOIN negotiation_outcomes no ON no.negotiation_id = ad.negotiation_id
JOIN scored_offers so        ON so.score_id     = no.score_id
JOIN seller_offerings sof    ON sof.offering_id = so.offering_id
JOIN discovery_queries dq    ON dq.query_id     = sof.query_id
JOIN beckn_intents bi        ON bi.beckn_intent_id = dq.beckn_intent_id
JOIN parsed_intents pi       ON pi.intent_id    = bi.intent_id
JOIN procurement_requests pr ON pr.request_id   = pi.request_id
JOIN users u                 ON u.user_id       = pr.requester_id
WHERE po.beckn_confirm_ref = $1
LIMIT 1
"""


class RecipientLookup:
    """Best-effort recipient resolver. Never raises into the caller."""

    def __init__(
        self, *, host: str, port: int, database: str, user: str, password: str
    ) -> None:
        self._host = host
        self._port = port
        self._db = database
        self._user = user
        self._password = password
        self._pool = None  # asyncpg pool, lazily created in start()

    async def start(self) -> None:
        if not self._user:
            logger.info("[recipients] no DB_USER set — email lookup disabled")
            return
        try:
            import asyncpg  # type: ignore
            self._pool = await asyncpg.create_pool(
                host=self._host, port=self._port, database=self._db,
                user=self._user, password=self._password,
                min_size=1, max_size=4, command_timeout=5,
            )
            logger.info("[recipients] DB pool ready (%s@%s:%s/%s)",
                        self._user, self._host, self._port, self._db)
        except Exception as exc:
            logger.warning("[recipients] DB unavailable (%s) — email lookup disabled", exc)
            self._pool = None

    async def stop(self) -> None:
        if self._pool is not None:
            try:
                await self._pool.close()
            except Exception:
                pass
            self._pool = None

    async def email_for_order(self, order_id: Optional[str]) -> Optional[str]:
        """Resolve `purchase_orders.beckn_confirm_ref` → `users.email`."""
        if not order_id or self._pool is None:
            return None
        try:
            async with self._pool.acquire() as conn:
                row = await conn.fetchrow(_QUERY, order_id)
            return row["email"] if row else None
        except Exception as exc:
            logger.warning("[recipients] lookup failed order=%s: %s", order_id, exc)
            return None

    # Backward-compatible alias — callers still using the older name.
    async def email_for_transaction(self, _txn_id: Optional[str]) -> Optional[str]:
        return None  # txn_id is not a DB key; callers must pass order_id
