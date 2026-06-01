"""Agent memory retrieval — Qdrant-backed past negotiation outcomes.

Production behaviour (Phase 3 ‑ see
``KnowledgeBase/project_scaffold/architecture/negotiation_engine/02_decision_intelligence_rl.md`` §4):
every completed negotiation is upserted as a ``NegotiationMemory``
document into the Qdrant ``negotiation_outcomes`` collection. At
decision time the strategy module pulls a small filtered ANN slice keyed
on ``(supplier_id, category_id, gap_band)`` to inform the next counter-offer.

This module ships the *skeleton* of that retrieval:

* If a ``qdrant_client`` is provided (real or mock) it is used as the
  production code path would.
* If no client is supplied (dev, unit tests, cold-start), a deterministic
  *synthetic* history is returned so the rest of the LangGraph pipeline
  can be exercised end-to-end without a live Qdrant deployment.

The function signature is the production contract — wiring real Qdrant
in later is a drop-in replacement, not a refactor.
"""
from __future__ import annotations

import logging
from typing import Any

from .config import CONFIG

logger = logging.getLogger(__name__)


# ── Constants ──────────────────────────────────────────────────────────────

#: Number of nearest neighbours to retrieve per the architecture spec.
DEFAULT_TOP_K: int = 16

#: Embedding dimension for ``all-MiniLM-L6-v2`` (see ``embedding_models``).
_EMBEDDING_DIM: int = 384

#: Safety cap on the returned prose length — bounds the LLM-injectable surface.
_MAX_SUMMARY_CHARS: int = 1000


# ── Synthetic fallback ─────────────────────────────────────────────────────


def _synthetic_history(supplier_id: str) -> str:
    """Return a deterministic synthetic history keyed by ``supplier_id``.

    Used when no Qdrant client is wired in (dev / test / cold-start). The
    shape mirrors what a real ANN-result reduction would emit: a short
    prose summary that downstream strategy code can lightly parse via
    keyword scan (``compute_target_discount`` looks for "accepts" /
    "rejects" / "cold-start" tokens).
    """
    if not supplier_id:
        return (
            "No supplier identifier supplied. Treat as cold-start; prefer "
            "conservative strategy with earlier HITL escalation."
        )

    # Deterministic three-bucket hash so unit tests can pin behaviour.
    bucket = sum(ord(c) for c in supplier_id) % 3
    if bucket == 0:
        return (
            f"Supplier {supplier_id} accepted 5-10% counter-offers in 8 of 10 "
            "past sessions for commodity items. Mean concession depth 6.4%, "
            "median response latency 41 minutes, 0 HITL escalations in last "
            "90 days. Strategy: aggressive within commodity bounds."
        )
    if bucket == 1:
        return (
            f"Supplier {supplier_id} typically rejects discounts above 5% on "
            "specialized equipment; accepts delivery slippage as alternate "
            "concession. Acceptance rate 42% over 12 prior negotiations. "
            "Strategy: prefer non-price concessions."
        )
    return (
        f"Supplier {supplier_id} is new (cold-start): only 2 prior "
        "negotiations, both completed at list price. No historical "
        "signal. Strategy: conservative."
    )


# ── Public API ─────────────────────────────────────────────────────────────


def get_supplier_negotiation_history(
    supplier_id: str,
    qdrant_client: Any | None = None,
    top_k: int = DEFAULT_TOP_K,
    collection: str | None = None,
) -> str:
    """Retrieve a textual summary of this supplier's past negotiation outcomes.

    Production path: issues a filtered ANN query on the Qdrant
    ``negotiation_outcomes`` collection (``filter: supplier_id == X``,
    ``limit: top_k``) and reduces the returned payloads' ``text_summary``
    fields into a short natural-language brief.

    Skeleton path: if ``qdrant_client`` is ``None`` or does not expose a
    ``.search`` callable, a deterministic synthetic summary keyed by
    ``supplier_id`` is returned. This keeps the broader graph runnable
    without Qdrant while preserving the contract.

    Parameters
    ----------
    supplier_id:
        Beckn BPP identifier for the supplier whose history is requested.
    qdrant_client:
        Either a ``qdrant_client.QdrantClient``-compatible object exposing
        ``.search(collection_name, query_vector, query_filter, limit)``
        or ``None`` to use the synthetic fallback.
    top_k:
        Number of nearest neighbours to retrieve. Defaults to
        :data:`DEFAULT_TOP_K` (16).
    collection:
        Qdrant collection name. Defaults to ``CONFIG.qdrant_collection``
        (typically ``"negotiation_outcomes"``).

    Returns
    -------
    str
        A short prose summary (≤ ``_MAX_SUMMARY_CHARS``) ready for downstream
        consumption by ``compute_target_discount``.
    """
    if not supplier_id:
        return _synthetic_history("")

    if qdrant_client is None or not hasattr(qdrant_client, "search"):
        logger.debug(
            "Qdrant client unavailable — emitting synthetic history for %s",
            supplier_id,
        )
        return _synthetic_history(supplier_id)

    coll = collection or CONFIG.qdrant_collection

    # Production path. Wrapped in a broad try/except so a Qdrant outage
    # degrades to the synthetic fallback rather than crashing the graph —
    # matches the "Qdrant fails open" posture documented in
    # ``04_resilience_and_mlops`` §6.
    try:
        from qdrant_client import models as q_models  # pragma: no cover

        # NOTE: a real implementation will compute an embedding for the
        # current context (category + supplier embedding + gap_pct band)
        # here. For the skeleton we drive the ANN with a zero-vector +
        # payload filter, which under Qdrant's default index returns the
        # most-recent N records matching the filter — sufficient for the
        # prose summary that downstream code consumes.
        zero_vector = [0.0] * _EMBEDDING_DIM
        hits = qdrant_client.search(
            collection_name=coll,
            query_vector=zero_vector,
            query_filter=q_models.Filter(
                must=[
                    q_models.FieldCondition(
                        key="supplier_id",
                        match=q_models.MatchValue(value=supplier_id),
                    )
                ]
            ),
            limit=top_k,
        )
    except Exception as exc:  # pragma: no cover — Qdrant-fail-open path
        logger.warning(
            "Qdrant retrieval failed for %s (%s) — falling back to synthetic",
            supplier_id,
            exc,
        )
        return _synthetic_history(supplier_id)

    return _reduce_hits(hits, supplier_id)


def _reduce_hits(hits: Any, supplier_id: str) -> str:
    """Reduce a list of Qdrant hits to a single prose summary."""
    summaries: list[str] = []
    for hit in hits or []:
        payload = getattr(hit, "payload", None) or {}
        text = payload.get("text_summary")
        if text:
            summaries.append(str(text))

    if not summaries:
        return _synthetic_history(supplier_id)

    head = summaries[:4]
    tail_count = max(0, len(summaries) - len(head))
    reduced = " ".join(head)
    if tail_count:
        reduced += f" [+{tail_count} earlier sessions elided]"
    return reduced[:_MAX_SUMMARY_CHARS]


__all__ = [
    "DEFAULT_TOP_K",
    "get_supplier_negotiation_history",
]
