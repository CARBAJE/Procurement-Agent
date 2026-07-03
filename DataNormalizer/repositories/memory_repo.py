"""agent_memory_vectors — write and search transaction embeddings.

Uses fastembed (ONNX Runtime, no PyTorch) with BAAI/bge-small-en-v1.5
(384 dims) to encode past procurement transactions. fastembed downloads
the ONNX model on first use and caches it in ~/.cache/fastembed.

Write path: called fire-and-forget from normalize_order after a PO is saved.
Read path:  POST /normalize/memory/search — returns top-k similar transactions.
"""
from __future__ import annotations

import json
import logging
from functools import lru_cache
from typing import Any

from ..db import get_pool

logger = logging.getLogger(__name__)

_EMBEDDING_DIM = 384
_MODEL_NAME = "BAAI/bge-small-en-v1.5"  # 384 dims, ~130MB ONNX, no PyTorch
_ENTITY_TYPE = "transaction"
_EMBEDDING_MODEL_ENUM = "all-MiniLM-L6-v2"  # closest enum value (open-source fallback)


@lru_cache(maxsize=1)
def _get_model():
    from fastembed import TextEmbedding  # imported lazily — model downloads on first use
    logger.info("[memory_repo] loading fastembed model %s", _MODEL_NAME)
    return TextEmbedding(model_name=_MODEL_NAME)


def _embed(text: str) -> list[float]:
    model = _get_model()
    vectors = list(model.embed([text]))
    return [float(v) for v in vectors[0]]


def _build_text(
    item_text: str,
    provider_name: str,
    price: float,
    currency: str,
    delivery_hours: int,
) -> str:
    return (
        f"{item_text} ordered from {provider_name} "
        f"at {price:.2f} {currency} delivery in {delivery_hours}h"
    )


async def write_transaction_memory(
    *,
    item_text: str,
    provider_name: str,
    price: float,
    currency: str,
    delivery_hours: int,
    request_id: str | None,
) -> None:
    """Embed a completed transaction and upsert into agent_memory_vectors.

    Never raises — write failures are logged and silently skipped so a
    memory hiccup never derails the confirm flow.
    """
    try:
        text = _build_text(item_text, provider_name, price, currency, delivery_hours)
        vector = _embed(text)
        metadata: dict[str, Any] = {
            "item_text":      item_text,
            "provider_name":  provider_name,
            "price":          price,
            "currency":       currency,
            "delivery_hours": delivery_hours,
            "text_summary":   text,
        }
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO agent_memory_vectors
                    (source_request_id, entity_type, embedding_vector,
                     metadata, embedding_model)
                VALUES ($1, $2::memory_entity_type, $3::vector, $4::jsonb,
                        $5::embedding_model_type)
                """,
                request_id,
                _ENTITY_TYPE,
                f"[{','.join(str(v) for v in vector)}]",
                json.dumps(metadata),
                _EMBEDDING_MODEL_ENUM,
            )
        logger.info("[memory_repo] stored transaction memory request_id=%s", request_id)
    except Exception as exc:
        logger.warning("[memory_repo] write failed (ignored): %s", exc)


async def search_similar_transactions(
    item_text: str,
    limit: int = 3,
    min_score: float = 0.75,
) -> list[dict]:
    """ANN search: return top-k past transactions similar to item_text.

    Returns a list of metadata dicts (empty list on any failure or no results
    above min_score). Each dict includes 'text_summary' and 'similarity'.
    """
    try:
        vector = _embed(item_text)
        vec_literal = f"[{','.join(str(v) for v in vector)}]"
        pool = await get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT metadata,
                       indexed_at,
                       1 - (embedding_vector <=> $1::vector) AS similarity
                FROM   agent_memory_vectors
                WHERE  entity_type = 'transaction'
                ORDER  BY embedding_vector <=> $1::vector
                LIMIT  $2
                """,
                vec_literal,
                limit * 3,  # over-fetch then filter by min_score
            )
        results = []
        for row in rows:
            sim = float(row["similarity"])
            if sim < min_score:
                continue
            meta = json.loads(row["metadata"]) if isinstance(row["metadata"], str) else dict(row["metadata"])
            meta["similarity"] = round(sim, 3)
            meta["indexed_at"] = row["indexed_at"].isoformat() if row["indexed_at"] else None
            results.append(meta)
            if len(results) >= limit:
                break
        return results
    except Exception as exc:
        logger.warning("[memory_repo] search failed (ignored): %s", exc)
        return []
