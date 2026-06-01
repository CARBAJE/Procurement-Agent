"""FastAPI prediction service for the Comparative & Scoring Phase-2 ranker.

Loads the trained Phase2Scorer from the MLflow Model Registry on startup
(with optional static-weights fallback) and exposes scoring endpoints.
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Optional

import mlflow
import mlflow.pytorch
import mlflow.tracking
import numpy as np
import torch
from fastapi import FastAPI, HTTPException, Request

from prediction_api import config
from core.features import extract_features_tensor
from core.model import Phase2Scorer
from core.schemas import ScoredItem, ScoreRequest, ScoreResponse

logging.basicConfig(
    level=config.LOG_LEVEL,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
logger = logging.getLogger("prediction_api")


def _load_model_from_mlflow(app: FastAPI) -> None:
    """Load model from MLflow registry; fall back to static weights if allowed."""
    try:
        mlflow.set_tracking_uri(config.MLFLOW_TRACKING_URI)
        model_uri = f"models:/{config.MODEL_NAME}/{config.MODEL_STAGE}"
        logger.info("Loading model from MLflow: %s", model_uri)
        model = mlflow.pytorch.load_model(model_uri)
        model.eval()

        client = mlflow.tracking.MlflowClient()
        versions = client.get_latest_versions(config.MODEL_NAME, stages=[config.MODEL_STAGE])
        version = versions[0].version if versions else "unknown"

        app.state.model = model
        app.state.model_version = f"{config.MODEL_NAME}:v{version} ({config.MODEL_STAGE})"
        logger.info("Model loaded successfully: %s", app.state.model_version)
    except Exception as exc:
        if config.ALLOW_FALLBACK_WEIGHTS:
            logger.warning(
                "Failed to load model from MLflow (%s). Falling back to static weights %s.",
                exc,
                config.FALLBACK_WEIGHTS,
            )
            fallback = Phase2Scorer.from_weights(config.FALLBACK_WEIGHTS, config.FALLBACK_BIAS)
            fallback.eval()
            app.state.model = fallback
            app.state.model_version = "fallback-static-weights"
        else:
            logger.error("Failed to load model from MLflow and fallback disabled — aborting startup.")
            raise


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.model = None
    app.state.model_version = "uninitialized"
    _load_model_from_mlflow(app)
    yield
    logger.info("shutting down")


app = FastAPI(
    title="Comparative & Scoring — Phase 2 Inference",
    version="2.0.0",
    lifespan=lifespan,
)


@app.get("/health")
async def health(request: Request) -> dict:
    model = getattr(request.app.state, "model", None)
    if model is None:
        raise HTTPException(
            status_code=503,
            detail={"status": "unavailable", "reason": "model not loaded"},
        )
    return {
        "status": "ok",
        "model_version": request.app.state.model_version,
        "service": "comparative-scoring-phase2",
    }


@app.post("/score", response_model=ScoreResponse)
async def score(payload: ScoreRequest, request: Request) -> ScoreResponse:
    if not payload.items:
        raise HTTPException(status_code=400, detail="items must not be empty")

    model = getattr(request.app.state, "model", None)
    if model is None:
        raise HTTPException(status_code=503, detail="model not loaded")

    item_dicts = [it.model_dump() for it in payload.items]
    features = extract_features_tensor(item_dicts)

    with torch.no_grad():
        scores = model(features).cpu().numpy()

    order = np.argsort(-scores)

    ranked_list: list[ScoredItem] = [
        ScoredItem(item=payload.items[int(idx)], score=float(scores[int(idx)]), rank=rank)
        for rank, idx in enumerate(order, start=1)
    ]
    recommended = payload.items[int(order[0])]

    top_id: Optional[str] = recommended.id
    top_score = float(scores[int(order[0])])
    logger.info(
        "Scored %d items — transaction_id=%s top_id=%s top_score=%.4f",
        len(payload.items),
        payload.transaction_id,
        top_id,
        top_score,
    )

    return ScoreResponse(
        recommended=recommended,
        ranked_list=ranked_list,
        model_version=request.app.state.model_version,
    )


@app.post("/reload")
async def reload_model(request: Request) -> dict:
    _load_model_from_mlflow(request.app)
    return {"status": "reloaded", "model_version": request.app.state.model_version}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "prediction_api.main:app",
        host="0.0.0.0",
        port=config.PORT,
        log_level=config.LOG_LEVEL.lower(),
    )
