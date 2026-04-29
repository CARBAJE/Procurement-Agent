"""scored_offers table — persist scoring engine output."""
from __future__ import annotations

import uuid as _uuid

from ..db import get_pool


async def create_scores(query_id: str, scores: list[dict]) -> list[dict]:
    """INSERT one scored_offers row per score entry.

    score dict keys:
        offering_id   str (UUID)
        rank          int
        total_score   float  0–1  (will be multiplied × 100 → 0–100)
        price_value   str    (used as tco_value proxy)
        explanation   str    (optional)
        model_version str    (optional)

    Returns:
        [{"offering_id": str, "score_id": str}, ...]
    """
    pool = await get_pool()
    result: list[dict] = []

    async with pool.acquire() as conn:
        for s in scores:
            offering_id = s.get("offering_id")
            if not offering_id:
                continue

            # composite_score 0–1 → total_score 0–100
            raw_score = float(s.get("composite_score", s.get("total_score", 0)))
            total_score = min(100.0, max(0.0, raw_score * 100))

            tco_raw = s.get("price_value") or s.get("tco_value") or "0"
            try:
                tco = float(tco_raw)
            except (ValueError, TypeError):
                tco = 0.0

            row = await conn.fetchrow(
                """
                INSERT INTO scored_offers (
                    offering_id, rank, total_score,
                    tco_value, explanation_text, model_version
                )
                VALUES ($1, $2, $3, $4, $5, $6)
                RETURNING score_id
                """,
                _uuid.UUID(offering_id),
                int(s.get("rank") or 1),
                total_score,
                tco,
                s.get("explanation") or "Automated scoring",
                s.get("model_version") or "1.0",
            )
            result.append({
                "offering_id": offering_id,
                "score_id": str(row["score_id"]),
            })

    return result
