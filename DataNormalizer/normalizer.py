"""DataNormalizer facade — orchestrates repositories and transformers.

Each public method maps 1:1 to a POST /normalize/<step> route.
"""
from __future__ import annotations

import logging

from .db import get_pool
from .repositories import discovery_repo, intent_repo, order_repo, request_repo, scoring_repo

logger = logging.getLogger(__name__)


class DataNormalizer:
    """Persistence bridge between stateless microservices and PostgreSQL."""

    # ── /normalize/request ────────────────────────────────────────────────────

    async def normalize_request(
        self,
        raw_input_text: str,
        channel: str = "web",
        requester_id: str | None = None,
    ) -> dict:
        """Create root procurement_requests row.

        Returns: {"request_id": str}
        """
        request_id = await request_repo.create_request(raw_input_text, channel, requester_id)
        logger.info("[normalizer] created request %s", request_id)
        return {"request_id": request_id}

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
        )
        logger.info("[normalizer] created purchase_order %s", po_id)
        return {"po_id": po_id}

    # ── PATCH /normalize/status ───────────────────────────────────────────────

    async def update_status(self, request_id: str, status: str) -> dict:
        """Update procurement_requests.status lifecycle column.

        Valid statuses: draft, parsing, discovering, scoring,
                        negotiating, pending_approval, confirmed, cancelled

        Returns: {"request_id": str, "status": str}
        """
        await request_repo.update_status(request_id, status)
        return {"request_id": request_id, "status": status}
