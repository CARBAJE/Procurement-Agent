"""sentence-transformers embedding singleton.

The model is CPU-bound; all encoding runs in a dedicated thread-pool
executor so it never blocks the asyncio event loop.
"""
from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING

import numpy as np

from .config import EMBEDDING_MODEL

if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer

_model: "SentenceTransformer | None" = None
_executor: ThreadPoolExecutor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="st-embed")


def _get_model() -> "SentenceTransformer":
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer  # deferred import

        _model = SentenceTransformer(EMBEDDING_MODEL)
    return _model


def _encode_sync(text: str) -> np.ndarray:
    return _get_model().encode(text, normalize_embeddings=True).astype(np.float32)


async def embed(text: str) -> np.ndarray:
    """Return a 384-d unit-norm float32 vector for *text*."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_executor, _encode_sync, text)


def embed_sync(text: str) -> np.ndarray:
    """Synchronous variant for use outside an event loop."""
    return _encode_sync(text)
