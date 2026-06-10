"""Read-side: reconstruct a full order detail from the DB by request_id.

This is the only read-by-id path in the persistence layer. It walks the FK
chain that the write side builds across many tables and returns a single DTO
shaped for the frontend order-detail page (request + intent + chosen offering +
optional purchase_order). See 21_order_detail_fidelity.sql for the two columns
this relies on (seller_offerings.item_name, purchase_orders.fulfillment_eta).
"""
from __future__ import annotations

import json
import logging

from ..db import get_pool

logger = logging.getLogger(__name__)

# purchase_orders.status (po_status_type) → frontend OrderState enum.
# po_status_type only has 5 values; PACKED / OUT_FOR_DELIVERY never occur here.
_PO_STATUS_TO_ORDER_STATE = {
    "pending":   "CREATED",
    "confirmed": "ACCEPTED",
    "shipped":   "SHIPPED",
    "delivered": "DELIVERED",
    "cancelled": "CANCELLED",
}


def _as_list(value) -> list:
    """beckn_intents.descriptions is JSONB — asyncpg may hand back str or list."""
    if value is None:
        return []
    if isinstance(value, list):
        return value
    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, list) else []
    except (TypeError, ValueError):
        return []


def _build_intent(row) -> dict:
    budget_min = row["budget_min"]
    budget_max = row["budget_max"]
    budget = None
    if budget_min is not None or budget_max is not None:
        budget = {
            "max": float(budget_max) if budget_max is not None else None,
            "min": float(budget_min) if budget_min is not None else None,
        }
    return {
        "item": row["item"] or "",
        "descriptions": _as_list(row["descriptions"]),
        "quantity": row["quantity"] or 1,
        "unit": row["unit"] or "units",
        "location_coordinates": row["location_coordinates"] or "",
        "delivery_timeline": row["delivery_timeline_hours"],
        "budget_constraints": budget,
    }


async def get_order_detail(request_id: str) -> dict | None:
    """Return {request, intent, order} for a request_id, or None if not found.

    `order` is None when the request exists but no purchase_order was persisted
    (best-effort persistence may skip it). Never raises on missing PO.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        # 1. Request + intent (always present for a known request_id).
        req = await conn.fetchrow(
            """
            SELECT pr.request_id, pr.raw_input_text, pr.status AS request_status,
                   pr.category, pr.created_at,
                   bi.item, bi.descriptions, bi.quantity, bi.unit,
                   bi.location_coordinates, bi.delivery_timeline_hours,
                   bi.budget_min, bi.budget_max
            FROM procurement_requests pr
            LEFT JOIN parsed_intents pi ON pi.request_id = pr.request_id
            LEFT JOIN beckn_intents  bi ON bi.intent_id  = pi.intent_id
            WHERE pr.request_id = $1::uuid
            """,
            request_id,
        )
        if req is None:
            return None

        intent = _build_intent(req) if req["item"] is not None else None

        # 2. The committed order + its chosen offering + provider (may be absent).
        po = await conn.fetchrow(
            """
            SELECT po.beckn_confirm_ref, po.item_id, po.quantity, po.unit,
                   po.agreed_price, po.currency, po.delivery_terms,
                   po.status AS po_status, po.fulfillment_eta,
                   so.item_name, so.delivery_eta_hours, so.quality_rating,
                   b.bpp_id, b.name AS provider_name, b.endpoint_url AS bpp_uri
            FROM procurement_requests pr
            JOIN parsed_intents       pi ON pi.request_id      = pr.request_id
            JOIN beckn_intents        bi ON bi.intent_id       = pi.intent_id
            JOIN discovery_queries    dq ON dq.beckn_intent_id = bi.beckn_intent_id
            JOIN seller_offerings     so ON so.query_id        = dq.query_id
            JOIN scored_offers        sc ON sc.offering_id     = so.offering_id
            JOIN negotiation_outcomes no ON no.score_id        = sc.score_id
            JOIN approval_decisions   ad ON ad.negotiation_id  = no.negotiation_id
            JOIN purchase_orders      po ON po.approval_id     = ad.approval_id
            JOIN bpp                   b ON b.bpp_id           = po.bpp_id
            WHERE pr.request_id = $1::uuid
            ORDER BY po.created_at DESC
            LIMIT 1
            """,
            request_id,
        )

        order = None
        if po is not None:
            price_str = f"{float(po['agreed_price']):.2f}"
            eta = po["fulfillment_eta"]
            order = {
                "order_id": po["beckn_confirm_ref"],
                "order_state": _PO_STATUS_TO_ORDER_STATE.get(po["po_status"], "CREATED"),
                "fulfillment_eta": eta.isoformat() if eta is not None else None,
                "bpp_id": str(po["bpp_id"]),
                "bpp_uri": po["bpp_uri"] or "",
                # A persisted purchase_order only exists after a successful real
                # confirm (the order is written in the live commit path), so a
                # reconstructed historical order is "live" — never "Local Catalog".
                "status": "live",
                "quantity": po["quantity"] or 1,
                "offering": {
                    "bpp_id": str(po["bpp_id"]),
                    "bpp_uri": po["bpp_uri"] or "",
                    "provider_id": "",
                    "provider_name": po["provider_name"] or "",
                    "item_id": po["item_id"] or "",
                    "item_name": po["item_name"] or (intent or {}).get("item") or po["item_id"] or "",
                    "price_value": price_str,
                    "price_currency": po["currency"] or "INR",
                    "rating": str(po["quality_rating"]) if po["quality_rating"] is not None else None,
                    "fulfillment_hours": po["delivery_eta_hours"],
                    "specifications": [],
                    "available_quantity": None,
                },
            }

        created = req["created_at"]
        return {
            "found": True,
            "request_id": str(req["request_id"]),
            "raw_input_text": req["raw_input_text"] or "",
            "request_status": req["request_status"],
            "category": req["category"],
            "created_at": created.isoformat() if created is not None else None,
            "intent": intent,
            "order": order,
        }
