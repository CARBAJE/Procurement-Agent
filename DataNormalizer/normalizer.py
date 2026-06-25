"""DataNormalizer facade — orchestrates repositories and transformers.

Each public method maps 1:1 to a POST /normalize/<step> route.
"""
from __future__ import annotations

import logging

from .db import get_pool
from .repositories import (
    audit_repo,
    discovery_repo,
    intent_repo,
    order_read_repo,
    order_repo,
    request_repo,
    scoring_repo,
    user_repo,
)

logger = logging.getLogger(__name__)


class DataNormalizer:
    """Persistence bridge between stateless microservices and PostgreSQL."""

    # ── /normalize/request ────────────────────────────────────────────────────

    async def normalize_request(
        self,
        raw_input_text: str,
        channel: str = "web",
        requester_id: str | None = None,
        actor: dict | None = None,
    ) -> dict:
        """Create root procurement_requests row.

        When `actor` carries a Keycloak identity (keycloak_id) and no explicit
        requester_id is given, just-in-time provision the user and attribute the
        request to them. Any resolution failure falls back to the system user
        (requester_id stays None → request_repo uses SYSTEM_USER_ID).

        Returns: {"request_id": str, "requester_id": str | None}
        """
        if actor and actor.get("keycloak_id") and not requester_id:
            try:
                pool = await get_pool()
                async with pool.acquire() as conn:
                    requester_id = await user_repo.resolve_user(
                        conn,
                        keycloak_id=actor["keycloak_id"],
                        email=actor.get("email"),
                        name=actor.get("name"),
                        role=actor.get("role"),
                    )
            except Exception as exc:  # noqa: BLE001 — never fail the write path on identity
                logger.warning(
                    "[normalizer] user resolve failed (%s) — attributing to system user",
                    exc,
                )
                requester_id = None

        request_id = await request_repo.create_request(raw_input_text, channel, requester_id)
        logger.info("[normalizer] created request %s (requester=%s)", request_id, requester_id or "system")
        return {"request_id": request_id, "requester_id": requester_id}

    # ── /normalize/intent ─────────────────────────────────────────────────────

    async def normalize_intent(
        self,
        request_id: str,
        intent_class: str,
        confidence: float,
        model_version: str,
        beckn_intent: dict,
    ) -> dict:
        """Create parsed_intents + beckn_intents rows.

        Returns: {"intent_id": str, "beckn_intent_id": str}
        """
        intent_id = await intent_repo.create_parsed_intent(
            request_id, intent_class, confidence, model_version
        )
        beckn_intent_id = await intent_repo.create_beckn_intent(intent_id, beckn_intent)
        logger.info("[normalizer] created intent %s / beckn_intent %s", intent_id, beckn_intent_id)
        return {"intent_id": intent_id, "beckn_intent_id": beckn_intent_id}

    # ── /normalize/discovery ──────────────────────────────────────────────────

    async def normalize_discovery(
        self,
        beckn_intent_id: str,
        network_id: str,
        offerings: list[dict],
    ) -> dict:
        """Create discovery_queries row + one seller_offerings row per offering.
        Upserts bpp rows as needed.

        Returns: {"query_id": str, "offering_ids": [{"item_id", "offering_id"}, ...]}
        """
        result = await discovery_repo.create_discovery(beckn_intent_id, network_id, offerings)
        logger.info(
            "[normalizer] created discovery query %s with %d offerings",
            result["query_id"],
            len(result["offering_ids"]),
        )
        return result

    # ── /normalize/scoring ────────────────────────────────────────────────────

    async def normalize_scoring(
        self,
        query_id: str,
        scores: list[dict],
    ) -> dict:
        """Create scored_offers rows.

        score dict must contain: offering_id, rank, composite_score (0–1).

        Returns: {"score_ids": [{"offering_id", "score_id"}, ...]}
        """
        score_ids = await scoring_repo.create_scores(query_id, scores)
        logger.info("[normalizer] created %d scored_offers", len(score_ids))
        return {"score_ids": score_ids}

    # ── /normalize/order ──────────────────────────────────────────────────────

    async def normalize_order(
        self,
        score_id: str,
        bpp_uri: str,
        item_id: str,
        quantity: int,
        agreed_price: float,
        beckn_confirm_ref: str,
        delivery_terms: str = "Standard delivery",
        currency: str = "INR",
        unit: str = "units",
        network_id: str = "beckn-default",
        requester_id: str | None = None,
        fulfillment_eta: str | None = None,
    ) -> dict:
        """Create negotiation_outcome + approval_decision + purchase_order.

        Returns: {"po_id": str}
        """
        # Resolve bpp_uuid from bpp_uri (find-or-create)
        pool = await get_pool()
        async with pool.acquire() as conn:
            bpp_uuid = await discovery_repo._upsert_bpp(conn, bpp_uri, "", network_id)

        po_id = await order_repo.create_order(
            score_id=score_id,
            bpp_uuid=bpp_uuid,
            item_id=item_id,
            quantity=quantity,
            agreed_price=agreed_price,
            beckn_confirm_ref=beckn_confirm_ref,
            delivery_terms=delivery_terms,
            currency=currency,
            unit=unit,
            requester_id=requester_id,
            fulfillment_eta=fulfillment_eta,
        )
        logger.info("[normalizer] created purchase_order %s", po_id)
        return {"po_id": po_id}

    # ── /normalize/audit ──────────────────────────────────────────────────────

    async def normalize_audit(
        self,
        event_type: str,
        agent_action: str,
        reasoning_payload: dict | None = None,
        request_id: str | None = None,
        po_id: str | None = None,
        actor_id: str | None = None,
        kafka_offset: int = 0,
    ) -> dict:
        """Append a row to audit_trail_events. Returns {"event_id": str}.

        Raises ValueError if event_type is outside audit_event_type enum.
        """
        event_id = await audit_repo.create_audit_event(
            event_type=event_type,
            agent_action=agent_action,
            reasoning_payload=reasoning_payload,
            request_id=request_id,
            po_id=po_id,
            actor_id=actor_id,
            kafka_offset=kafka_offset,
        )
        logger.info("[normalizer] audit %s (%s) → %s", event_type, agent_action, event_id)
        return {"event_id": event_id}

    # ── /normalize/po_status ──────────────────────────────────────────────────

    async def normalize_po_status(self, beckn_confirm_ref: str, state: str) -> dict:
        """Update purchase_orders.status by beckn_confirm_ref.

        Valid states: pending, confirmed, shipped, delivered, cancelled.
        Returns: {"po_id": str, "status": str} or {"po_id": None, "status": state}
        when no row matched.
        """
        po_id = await order_repo.update_po_status(beckn_confirm_ref, state)
        return {"po_id": po_id, "status": state}

    # ── GET /order/{request_id} ───────────────────────────────────────────────

    async def get_order_detail(self, request_id: str) -> dict | None:
        """Reconstruct a full order detail from the DB by request_id.

        Returns the {request, intent, order} DTO, or None when request_id is
        unknown. `order` is None when the request exists but no purchase_order
        was persisted. Read-only — never writes.
        """
        return await order_read_repo.get_order_detail(request_id)

    # ── PATCH /normalize/status ───────────────────────────────────────────────

    async def update_status(
        self, request_id: str, status: str, category: str | None = None
    ) -> dict:
        """Update procurement_requests.status lifecycle column.

        Valid statuses: draft, parsing, discovering, scoring,
                        negotiating, pending_approval, confirmed, cancelled

        Optional `category` sets the supplier-declared category (from discovery).

        Returns: {"request_id": str, "status": str}
        """
        await request_repo.update_status(request_id, status, category)
        return {"request_id": request_id, "status": status}
