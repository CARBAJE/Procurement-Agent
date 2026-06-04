"""Lambda 3 — Comparative & Scoring microservice (HTTP adapter to the ML model).

Production-faithful design: this service does NOT score in-process. It is a
thin **HTTP adapter** that forwards offerings to the ML inference microservice
``prediction-api`` (Phase2Scorer / RankNet served from the MLflow registry) over
the docker network, and maps the response back to the caller's contract.

Contract (unchanged for the orchestrator):
    POST /score  { "offerings": [DiscoverOffering...] }
    → { "selected": DiscoverOffering } | { "selected": null }

Flow:
    offerings ──(map)──> ScoreRequest{items} ──HTTP──> prediction-api:8004/score
            <──(match recommended.id == item_id)── ScoreResponse

Resilience: if ``prediction-api`` is unreachable / errors and
``SCORING_FALLBACK_ENABLED`` is true, fall back to the in-process Phase-1
min-price heuristic (``ComparativeScoring.score``) so the demo never hard-fails.
The two log lines ("scored via prediction-api ..." vs "scored via fallback
heuristic") are the monitoring signal for which path served the request.

The DiscoverOffering→item field mapping mirrors the source of truth in
``services/ComparativeAndScoreing/core/schemas.py::CatalogItem.from_discover_offering``.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from typing import Any, Optional

sys.path.insert(0, "/app")

import aiohttp
from aiohttp import web

# In-process heuristic kept ONLY for the resilience fallback path.
from ComparativeScoring import score as _heuristic_score  # type: ignore[import]

logger = logging.getLogger(__name__)

# ── Config (módulo-nivel, por convención del repo — sin os.getenv disperso) ──
PREDICTION_API_URL = os.getenv("PREDICTION_API_URL", "http://prediction-api:8004")
PREDICTION_TIMEOUT_S = float(os.getenv("PREDICTION_TIMEOUT_S", "8.0"))
SCORING_FALLBACK_ENABLED = os.getenv("SCORING_FALLBACK_ENABLED", "true").lower() in (
    "1",
    "true",
    "yes",
)

_SESSION_KEY = "pred_session"


# ── Mapeo DiscoverOffering → CatalogItem (espejo de core/schemas.py:60) ──────


def _coerce_float(value: Any) -> Optional[float]:
    """Best-effort float coercion; returns None when not parseable."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text:
        return None
    import re

    cleaned = re.sub(r"[^0-9.\-eE]", "", text)
    if cleaned in ("", "-", ".", "-.", "e", "E"):
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def _to_score_request(offerings: list[dict]) -> dict:
    """Build the prediction-api ``ScoreRequest`` body from DiscoverOfferings.

    Field mapping (source of truth: ``core/schemas.py::from_discover_offering``):
      id                  <- item_id
      price               <- price_value  (prediction-api coerces "₹ 1,200" -> float)
      delivery_time_hours <- fulfillment_hours
      supplier_name       <- provider_name
      risk_score          <- rating (coerced to float | None)
    """
    items: list[dict] = []
    for off in offerings:
        fulfillment = off.get("fulfillment_hours")
        items.append(
            {
                "id": str(off.get("item_id", "")),
                "price": off.get("price_value", 0.0),
                "delivery_time_hours": int(fulfillment) if fulfillment is not None else 0,
                "supplier_name": off.get("provider_name"),
                "risk_score": _coerce_float(off.get("rating")),
            }
        )
    return {"items": items}


def _ml_scoring_from_response(resp: dict) -> dict:
    """Extract the ML ranking from the prediction-api ScoreResponse.

    Returns a normalized scoring block the orchestrator turns into the
    frontend's criteria shape:
        {engine, model_version, pipeline, ranking:[{item_id, score, rank}]}
    ``item_id`` == ``CatalogItem.id`` (which we set from the original item_id).
    """
    ranking: list[dict] = []
    for idx, scored in enumerate((resp or {}).get("ranked_list") or [], start=1):
        item = (scored or {}).get("item") or {}
        ranking.append(
            {
                "item_id": str(item.get("id", "")),
                "score": float(scored.get("score", 0.0)),
                "rank": int(scored.get("rank", idx)),
            }
        )
    return {
        "engine": "ml",
        "model_version": resp.get("model_version"),
        "pipeline": resp.get("pipeline"),
        "ranking": ranking,
    }


def _select_from_response(resp: dict, offerings: list[dict]) -> Optional[dict]:
    """Map the ML response back to the ORIGINAL DiscoverOffering.

    Matches ``recommended.id`` (== item_id) against the original offerings and
    returns the original dict unchanged (preserves every Beckn field the
    downstream /select step needs). Falls back to the top of ``ranked_list``.
    """
    recommended = (resp or {}).get("recommended") or {}
    rec_id = str(recommended.get("id", ""))

    def _find(item_id: str) -> Optional[dict]:
        for off in offerings:
            if str(off.get("item_id", "")) == item_id:
                return off
        return None

    match = _find(rec_id)
    if match is not None:
        return match

    # Defensive: try the ranked_list head if recommended didn't match.
    for scored in (resp or {}).get("ranked_list") or []:
        cand = str(((scored or {}).get("item") or {}).get("id", ""))
        m = _find(cand)
        if m is not None:
            return m
    return None


# ── Handlers ─────────────────────────────────────────────────────────────


async def health(request: web.Request) -> web.Response:
    return web.json_response(
        {
            "status": "ok",
            "service": "comparative-scoring",
            "mode": "ml-adapter",
            "prediction_api": PREDICTION_API_URL,
            "fallback_enabled": SCORING_FALLBACK_ENABLED,
        }
    )


async def score_handler(request: web.Request) -> web.Response:
    """POST /score — delegate ranking to the ML prediction-api (with fallback)."""
    try:
        body = await request.json()
    except json.JSONDecodeError:
        raise web.HTTPBadRequest(reason="Invalid JSON")

    offerings: list[dict] = body.get("offerings", [])
    if not offerings:
        return web.json_response({"selected": None})

    session: aiohttp.ClientSession = request.app[_SESSION_KEY]

    # ── Camino primario: el modelo ML vía prediction-api (HTTP, in-network) ──
    try:
        payload = _to_score_request(offerings)
        async with session.post(
            f"{PREDICTION_API_URL}/score",
            json=payload,
            timeout=aiohttp.ClientTimeout(total=PREDICTION_TIMEOUT_S),
        ) as resp:
            resp.raise_for_status()
            data = await resp.json()
        selected = _select_from_response(data, offerings)
        ml_scoring = _ml_scoring_from_response(data)
        logger.info(
            "scored via prediction-api model_version=%s pipeline=%s selected_item_id=%s",
            data.get("model_version"),
            data.get("pipeline"),
            (selected or {}).get("item_id"),
        )
        return web.json_response({"selected": selected, "scoring": ml_scoring})
    except (
        aiohttp.ClientError,
        asyncio.TimeoutError,
        KeyError,
        ValueError,
        TypeError,
    ) as exc:
        if not SCORING_FALLBACK_ENABLED:
            logger.error("prediction-api failed and fallback disabled: %s", exc)
            raise web.HTTPBadGateway(reason=f"prediction-api unavailable: {exc}")
        logger.warning(
            "prediction-api unreachable (%s) — falling back to min-price heuristic",
            exc,
        )

    # ── Camino de resiliencia: heurística in-process (precio más bajo) ──
    try:
        selected = _heuristic_score(offerings)
    except (KeyError, ValueError, TypeError) as exc:
        raise web.HTTPUnprocessableEntity(
            reason=f"Invalid offering data — price_value must be numeric: {exc}"
        )
    logger.info(
        "scored via fallback heuristic selected_item_id=%s",
        (selected or {}).get("item_id") if isinstance(selected, dict) else None,
    )
    return web.json_response(
        {"selected": selected, "scoring": {"engine": "heuristic_min_price"}}
    )


# ── App lifecycle ───────────────────────────────────────────────────────


async def _on_startup(app: web.Application) -> None:
    app[_SESSION_KEY] = aiohttp.ClientSession()
    logger.info(
        "comparative-scoring adapter ready — prediction_api=%s fallback=%s",
        PREDICTION_API_URL,
        SCORING_FALLBACK_ENABLED,
    )


async def _on_cleanup(app: web.Application) -> None:
    session = app.get(_SESSION_KEY)
    if session is not None:
        await session.close()


def create_app() -> web.Application:
    app = web.Application()
    app.router.add_get("/health", health)
    app.router.add_post("/score", score_handler)
    app.on_startup.append(_on_startup)
    app.on_cleanup.append(_on_cleanup)
    return app


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    port = int(os.getenv("PORT", "8003"))
    web.run_app(create_app(), host="0.0.0.0", port=port)
