"""discovery_queries + seller_offerings + bpp upsert."""
from __future__ import annotations

import json
import uuid as _uuid

from ..db import get_pool


async def _upsert_bpp(
    conn,
    bpp_uri: str,
    provider_name: str,
    network_id: str,
) -> _uuid.UUID:
    """Find-or-create a BPP row by endpoint_url; return its UUID PK.

    The bpp table has no UNIQUE constraint on endpoint_url so we use a
    SELECT-then-INSERT pattern inside the caller's transaction.
    """
    row = await conn.fetchrow(
        "SELECT bpp_id FROM bpp WHERE endpoint_url = $1", bpp_uri
    )
    if row:
        await conn.execute(
            "UPDATE bpp SET last_seen_at = NOW() WHERE bpp_id = $1", row["bpp_id"]
        )
        return row["bpp_id"]

    row = await conn.fetchrow(
        """
        INSERT INTO bpp (name, network_id, endpoint_url)
        VALUES ($1, $2, $3)
        RETURNING bpp_id
        """,
        provider_name or bpp_uri,
        network_id or "beckn-default",
        bpp_uri,
    )
    return row["bpp_id"]


async def create_discovery(
    beckn_intent_id: str,
    network_id: str,
    offerings: list[dict],
) -> dict:
    """INSERT discovery_query + all seller_offerings in one transaction.

    Returns:
        {
            "query_id": str,
            "offering_ids": [{"item_id": str, "offering_id": str}, ...]
        }
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            # 1. discovery_queries row
            q_row = await conn.fetchrow(
                """
                INSERT INTO discovery_queries
                    (beckn_intent_id, network_id, results_count)
                VALUES ($1, $2, $3)
                RETURNING query_id
                """,
                _uuid.UUID(beckn_intent_id),
                network_id or "beckn-default",
                len(offerings),
            )
            query_id = q_row["query_id"]

            # 2. One seller_offerings row per offering
            offering_ids: list[dict] = []
            for off in offerings:
                bpp_uuid = await _upsert_bpp(
                    conn,
                    off.get("bpp_uri") or "",
                    off.get("provider_name") or "",
                    network_id or "beckn-default",
                )

                price_raw = off.get("price_value") or "0"
                price = float(price_raw) if price_raw else 0.0
                delivery_hours = int(off.get("fulfillment_hours") or 24)
                # delivery_eta_hours CHECK > 0
                delivery_hours = max(1, delivery_hours)

                rating_raw = off.get("rating")
                quality_rating = float(rating_raw) if rating_raw else None

                o_row = await conn.fetchrow(
                    """
                    INSERT INTO seller_offerings (
                        query_id, bpp_id, item_id, price, currency,
                        delivery_eta_hours, quality_rating, certifications,
                        inventory_count, is_normalized
                    )
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8::jsonb, $9, TRUE)
                    RETURNING offering_id
                    """,
                    query_id,
                    bpp_uuid,
                    off.get("item_id") or "",
                    price,
                    off.get("price_currency") or "INR",
                    delivery_hours,
                    quality_rating,
                    json.dumps(off.get("specifications") or []),
                    off.get("available_quantity"),
                )
                offering_ids.append({
                    "item_id": off.get("item_id") or "",
                    "offering_id": str(o_row["offering_id"]),
                })

            return {
                "query_id": str(query_id),
                "offering_ids": offering_ids,
            }
