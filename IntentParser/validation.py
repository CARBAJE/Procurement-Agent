"""Stage 3 — semantic cache ANN query, three-zone thresholding, MCP fallback.

Also houses MCPResultAdapter for the async Path B cache write.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Optional

import numpy as np

from .config import (
    AMBIGUOUS_THRESHOLD,
    VALIDATED_THRESHOLD,
)
from .db import get_pool
from .embeddings import embed
from .mcp_client import get_mcp_client
from .models import (
    BecknIntent,
    CacheMatch,
    ValidationResult,
    ValidationZone,
)

logger = logging.getLogger(__name__)

# ── Cache query ───────────────────────────────────────────────────────────────

_ANN_SQL = """
SELECT item_name, bpp_id,
       1 - (item_embedding <=> $1::vector) AS similarity
FROM   bpp_catalog_semantic_cache
ORDER  BY item_embedding <=> $1::vector
LIMIT  $2
"""


async def query_semantic_cache(
    embedding: np.ndarray,
    top_k: int = 3,
) -> list[CacheMatch]:
    """Run an HNSW ANN query and return the top-k matches."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(_ANN_SQL, embedding.tolist(), top_k)
    return [
        CacheMatch(item_name=r["item_name"], bpp_id=r["bpp_id"], similarity=float(r["similarity"]))
        for r in rows
    ]


# ── Three-zone threshold ──────────────────────────────────────────────────────


def apply_three_zone_threshold(
    matches: list[CacheMatch],
) -> tuple[ValidationZone, Optional[CacheMatch]]:
    if not matches:
        return ValidationZone.CACHE_MISS, None
    top = matches[0]
    if top.similarity >= VALIDATED_THRESHOLD:
        return ValidationZone.VALIDATED, top
    if top.similarity >= AMBIGUOUS_THRESHOLD:
        return ValidationZone.AMBIGUOUS, top
    return ValidationZone.CACHE_MISS, top


# ── Path B writer ─────────────────────────────────────────────────────────────

_UPSERT_SQL = """
INSERT INTO bpp_catalog_semantic_cache
    (item_name, bpp_id, bpp_uri, item_embedding, descriptions,
     embedding_strategy, source)
VALUES ($1, $2, $3, $4::vector, $5, 'item_name_and_specs', 'mcp_feedback')
ON CONFLICT (item_name, bpp_id)
DO UPDATE SET
    item_embedding     = EXCLUDED.item_embedding,
    descriptions       = EXCLUDED.descriptions,
    embedding_strategy = EXCLUDED.embedding_strategy,
    source             = EXCLUDED.source,
    last_seen_at       = now()
"""


class MCPResultAdapter:
    """Writes a Path B row to the semantic cache after an MCP-confirmed hit."""

    @staticmethod
    async def write_path_b_row(
        item_name: str,
        descriptions: list[str],
        bpp_id: str,
        bpp_uri: str,
    ) -> None:
        spec_tokens = " | ".join(descriptions) if descriptions else ""
        embed_text = f"{item_name} | {spec_tokens}" if spec_tokens else item_name
        try:
            vector = await embed(embed_text)
            pool = await get_pool()
            async with pool.acquire() as conn:
                await conn.execute(
                    _UPSERT_SQL,
                    item_name,
                    bpp_id,
                    bpp_uri,
                    vector.tolist(),
                    descriptions or None,
                )
            logger.debug("Path B write: %s @ %s", item_name, bpp_id)
        except Exception as exc:
            logger.error("Path B write failed for %s: %s", item_name, exc)


# ── Stage 3 orchestration ─────────────────────────────────────────────────────


async def run_stage3_hybrid_validation(
    beckn_intent: BecknIntent,
) -> ValidationResult:
    """Run the full Stage 3 flow and return a ValidationResult.

    1. Build embedding query string from item + descriptions.
    2. ANN query against the semantic cache.
    3. Apply three-zone threshold.
    4. If CACHE_MISS, probe MCP sidecar (P2 path).
    5. On MCP hit, dispatch Path B write as a background task.
    """
    spec_tokens = " | ".join(beckn_intent.descriptions[:4]) if beckn_intent.descriptions else ""
    query_text = f"{beckn_intent.item} | {spec_tokens}" if spec_tokens else beckn_intent.item

    vector = await embed(query_text)

    try:
        matches = await query_semantic_cache(vector)
    except Exception as exc:
        logger.warning("Cache query failed: %s", exc)
        matches = []

    zone, top_match = apply_three_zone_threshold(matches)

    if zone != ValidationZone.CACHE_MISS:
        return ValidationResult(zone=zone, top_match=top_match)

    # P2 — MCP probe
    mcp_result = await get_mcp_client().search_bpp_catalog(
        item_name=beckn_intent.item,
        descriptions=beckn_intent.descriptions,
        location=beckn_intent.location_coordinates,
    )

    if not mcp_result.get("found") or not mcp_result.get("items"):
        return ValidationResult(zone=ValidationZone.CACHE_MISS, not_found=True)

    best = mcp_result["items"][0]
    mcp_item_name: str = best.get("item_name", beckn_intent.item)
    mcp_bpp_id: str = best.get("bpp_id", "")
    mcp_bpp_uri: str = best.get("bpp_uri", "")

    # Path B write — fire and forget, does NOT block the response
    asyncio.create_task(
        MCPResultAdapter.write_path_b_row(
            item_name=mcp_item_name,
            descriptions=beckn_intent.descriptions,
            bpp_id=mcp_bpp_id,
            bpp_uri=mcp_bpp_uri,
        )
    )

    return ValidationResult(
        zone=ValidationZone.CACHE_MISS,
        mcp_validated=True,
        mcp_item_name=mcp_item_name,
        mcp_bpp_id=mcp_bpp_id,
        mcp_bpp_uri=mcp_bpp_uri,
    )
