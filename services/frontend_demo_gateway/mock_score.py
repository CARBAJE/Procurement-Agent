"""Dynamic Comparison Engine mock — ``POST /api/demo/score``.

Runs the **real** Phase-2 Learning-to-Rank pipeline end-to-end:

1. Coerces the front-end payload into typed ``CatalogItem`` instances
   via :class:`core.schemas.CatalogItem` (currency parsing, type coercion).
2. Builds the canonical ``(n, 3)`` ``[price, speed, risk]`` feature
   matrix via :func:`core.features.extract_features_tensor` — the same
   normaliser the production prediction-API uses.
3. Forwards the matrix through a real ``Phase2Scorer`` (``nn.Linear(3, 1)``)
   loaded with the architecture-defined fallback weights.
4. Sorts suppliers by descending score and returns the ranked list.

The model architecture, feature extraction, and ranking math are
production-identical. Only the **weight provenance** is mocked: instead
of loading from MLflow, we use the documented fallback weights so the
gateway boots in a CI/dev env without MLflow infrastructure.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Optional

import torch
from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field

# Side-effect: pushes services/ComparativeAndScoreing onto sys.path.
from . import _paths  # noqa: F401

from core.features import extract_features_tensor  # noqa: E402  (post path inject)
from core.model import Phase2Scorer  # noqa: E402
from core.schemas import CatalogItem  # noqa: E402

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────
# Fallback weights — mirror the production prediction-API config defaults.
# ─────────────────────────────────────────────────────────────────────────

#: Coefficient vector for the linear scorer ``[w_price, w_speed, w_risk]``.
#: All features are post-normalisation in ``[0, 1]`` with "higher = better"
#: semantics (see ``core/features.py`` docstring), so a positive weight
#: means *"more important"*. The defaults mirror the Phase-2 priors:
#: price > speed > risk for typical commodity buys.
FALLBACK_WEIGHTS: list[float] = [0.50, 0.30, 0.20]
FALLBACK_BIAS: float = 0.0


def _build_model() -> Phase2Scorer:
    """Construct a real ``Phase2Scorer`` with the documented fallback weights.

    Equivalent to ``Phase2Scorer.from_weights(FALLBACK_WEIGHTS, FALLBACK_BIAS)``
    — same ``nn.Linear`` module, just deterministic coefficients instead of
    MLflow-loaded ones.
    """
    model = Phase2Scorer.from_weights(FALLBACK_WEIGHTS, FALLBACK_BIAS)
    model.eval()  # disable dropout / batch-norm bookkeeping (no-op here, but explicit)
    logger.info(
        "Phase2Scorer loaded with fallback weights price=%.2f speed=%.2f risk=%.2f bias=%.2f",
        FALLBACK_WEIGHTS[0], FALLBACK_WEIGHTS[1], FALLBACK_WEIGHTS[2], FALLBACK_BIAS,
    )
    return model


# ─────────────────────────────────────────────────────────────────────────
# Inbound / outbound schemas
# ─────────────────────────────────────────────────────────────────────────


class DemoScoreSupplier(BaseModel):
    """One supplier in the front-end's "candidates" payload.

    Field names match what the production ``CatalogItem`` accepts so the
    gateway is wire-compatible with the comparative-scoring API the
    front-end already knows about.
    """

    model_config = ConfigDict(extra="allow")

    id: str = Field(..., min_length=1)
    supplier_name: Optional[str] = None
    price: float
    delivery_time_hours: int = Field(..., ge=0)
    risk_score: Optional[float] = Field(default=None, ge=0.0, le=1.0)


class DemoScoreRequest(BaseModel):
    """Inbound payload from the front-end."""

    model_config = ConfigDict(extra="forbid")

    transaction_id: Optional[str] = None
    items: list[DemoScoreSupplier] = Field(..., min_length=1)


class DemoRankedSupplier(BaseModel):
    """One ranked supplier, annotated with the model score and rank."""

    model_config = ConfigDict(extra="allow")

    rank: int = Field(..., ge=1)
    score: float
    id: str
    supplier_name: Optional[str] = None
    price: float
    delivery_time_hours: int
    risk_score: Optional[float] = None
    features: dict[str, float] = Field(
        default_factory=dict,
        description="Post-normalisation feature vector (price/speed/risk in [0,1]).",
    )


class DemoScoreResponse(BaseModel):
    """Outbound payload — strictly sorted by descending ``score``."""

    model_config = ConfigDict(extra="forbid")

    transaction_id: Optional[str] = None
    recommended_id: str
    ranked: list[DemoRankedSupplier]
    model_version: str
    model_weights: dict[str, float]
    latency_ms: float
    pipeline: str = "phase2_ranknet_real"


# ─────────────────────────────────────────────────────────────────────────
# Router
# ─────────────────────────────────────────────────────────────────────────


router = APIRouter(prefix="/api/demo", tags=["demo:score"])


@router.post(
    "/score",
    response_model=DemoScoreResponse,
    status_code=status.HTTP_200_OK,
    summary="Score candidate suppliers via the real Phase-2 LTR model.",
)
async def score(req: DemoScoreRequest, request: Request) -> DemoScoreResponse:
    """Run the real PyTorch ``nn.Linear`` ranker against the incoming candidates.

    The handler is purely deterministic: same weights + same input →
    same ranking. ``model.eval()`` is set at module load so no
    dropout/batch-norm variance leaks into the response.
    """
    model: Phase2Scorer = request.app.state.score_model
    model_version: str = request.app.state.score_model_version

    if not req.items:
        # min_length=1 should have caught this; defensive nonetheless.
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="`items` must contain at least one supplier",
        )

    start = time.perf_counter()

    # Coerce through the production ``CatalogItem`` so we exercise the same
    # currency-parsing + type-coercion that the real scoring API uses.
    catalog_items: list[CatalogItem] = []
    for item in req.items:
        catalog_items.append(CatalogItem(**item.model_dump()))

    # Real production feature extractor: builds the (n, 3) min-max-scaled
    # tensor with the documented "higher = better" semantics.
    catalog_dicts: list[dict[str, Any]] = [ci.model_dump() for ci in catalog_items]
    features = extract_features_tensor(catalog_dicts)

    # Real PyTorch forward pass.
    with torch.no_grad():
        scores = model(features)
    scores_np = scores.detach().cpu().numpy().tolist()
    features_np = features.detach().cpu().numpy().tolist()

    # Pair up + sort. ``zip`` preserves stable ordering for ties.
    paired = list(zip(catalog_items, scores_np, features_np, strict=True))
    paired.sort(key=lambda triplet: triplet[1], reverse=True)

    ranked: list[DemoRankedSupplier] = []
    for rank_idx, (item, score_val, feat) in enumerate(paired, start=1):
        ranked.append(
            DemoRankedSupplier(
                rank=rank_idx,
                score=float(score_val),
                id=item.id,
                supplier_name=item.supplier_name,
                price=float(item.price),
                delivery_time_hours=int(item.delivery_time_hours),
                risk_score=item.risk_score,
                features={
                    "price": float(feat[0]),
                    "speed": float(feat[1]),
                    "risk":  float(feat[2]),
                },
            )
        )

    latency_ms = (time.perf_counter() - start) * 1000.0
    weights = model.get_weights()

    logger.info(
        "Scored %d suppliers in %.2f ms; top=%s score=%.4f",
        len(ranked), latency_ms, ranked[0].id, ranked[0].score,
    )

    return DemoScoreResponse(
        transaction_id=req.transaction_id,
        recommended_id=ranked[0].id,
        ranked=ranked,
        model_version=model_version,
        model_weights=weights,
        latency_ms=latency_ms,
    )


__all__ = [
    "FALLBACK_WEIGHTS",
    "FALLBACK_BIAS",
    "DemoScoreRequest",
    "DemoScoreResponse",
    "DemoRankedSupplier",
    "DemoScoreSupplier",
    "_build_model",
    "router",
]
