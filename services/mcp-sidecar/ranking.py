"""Semantic ranking of ONIX BPP catalog items against a buyer query.

Uses all-MiniLM-L6-v2 (384-d) — the same model as IntentParser Stage 3 —
so similarity scores are comparable to the pgvector cache thresholds.

The SentenceTransformer model is loaded lazily and cached for the process
lifetime.  Encoding runs in a thread-pool executor to avoid blocking the
asyncio event loop.
"""
from __future__ import annotations

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache

import numpy as np
from sentence_transformers import SentenceTransformer

from config import settings

logger = logging.getLogger(__name__)

_MODEL_NAME = "all-MiniLM-L6-v2"
_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="st-rank")


@lru_cache(maxsize=1)
def _get_model() -> SentenceTransformer:
    logger.info("Loading sentence-transformers model: %s", _MODEL_NAME)
    return SentenceTransformer(_MODEL_NAME)


def _rank_sync(query: str, candidates: list[str]) -> np.ndarray:
    """Encode query + candidates in one batch; return per-candidate cosine similarities."""
    model = _get_model()
    # Batch encode: index 0 is the query, 1..N are candidates
    embeddings: np.ndarray = model.encode(
        [query] + candidates,
        normalize_embeddings=True,
        show_progress_bar=False,
    )
    return np.dot(embeddings[1:], embeddings[0])


async def rank_and_filter_items(
    query_item_name: str,
    onix_items: list[dict],
) -> list[dict]:
    """Rank ONIX items by cosine similarity to the buyer's item name.

    Items scoring below RANKING_MIN_SIMILARITY are discarded.
    The returned list is sorted highest-similarity-first.

    On any encoding error, all items are returned unranked so the
    caller can still surface a degraded-but-non-empty result.
    """
    if not onix_items:
        return []

    candidates = [item.get("item_name", "") for item in onix_items]

    loop = asyncio.get_running_loop()
    try:
        similarities: np.ndarray = await loop.run_in_executor(
            _executor,
            _rank_sync,
            query_item_name,
            candidates,
        )
    except Exception as exc:
        logger.warning("Semantic ranking failed — returning all items unranked: %s", exc)
        return onix_items

    scored = [
        (item, float(sim))
        for item, sim in zip(onix_items, similarities)
        if float(sim) >= settings.ranking_min_similarity
    ]
    scored.sort(key=lambda x: x[1], reverse=True)
    return [item for item, _ in scored]
