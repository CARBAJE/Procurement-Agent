"""Lambda 1 — Intention Parser microservice.

Thin aiohttp wrapper around IntentParser.parse_request().
IntentParser/ is mounted at /app/IntentParser via Docker volume.

POST /parse               { "query": "..." }
POST /explain-selection   { "offerings": [...], "recommended_provider": "...", ... }
"""
from __future__ import annotations

import json
import logging
import os
import re
import sys

# IntentParser/ and shared/ are mounted as volumes at /app/
sys.path.insert(0, "/app")

from aiohttp import web
from openai import AsyncOpenAI

logger = logging.getLogger(__name__)

_PROCUREMENT_INTENTS = {"SearchProduct", "RequestQuote", "PurchaseOrder"}


async def health(request: web.Request) -> web.Response:
    return web.json_response({"status": "ok", "service": "intention-parser"})


async def parse(request: web.Request) -> web.Response:
    """POST /parse — NL query → ParseResult JSON."""
    try:
        body = await request.json()
    except json.JSONDecodeError:
        raise web.HTTPBadRequest(reason="Invalid JSON")

    query = body.get("query", "").strip()
    if not query:
        raise web.HTTPBadRequest(reason="query is required")

    try:
        from IntentParser.orchestrator import parse_procurement_request  # type: ignore[import]
        result = await parse_procurement_request(query, enable_stage3=False)

        intent_type = "procurement" if result.intent in _PROCUREMENT_INTENTS else "unknown"
        beckn_dict = None
        if result.beckn_intent:
            beckn_dict = {**result.beckn_intent.model_dump(), "unit": "unit"}

        return web.json_response({
            "intent":       intent_type,
            "confidence":   result.confidence,
            "beckn_intent": beckn_dict,
            "routed_to":    result.routed_to,
        })
    except Exception as exc:
        logger.error("Intent parsing failed: %s", exc)
        safe_reason = str(exc).replace("\r", " ").replace("\n", " ")[:200]
        raise web.HTTPInternalServerError(
            reason=f"Intent parsing failed: {safe_reason}",
            text=json.dumps({"detail": f"Intent parsing failed: {safe_reason}"}),
            content_type="application/json",
        )


async def explain_selection(request: web.Request) -> web.Response:
    """POST /explain-selection — LLM natural-language explanation for scoring decision."""
    try:
        body = await request.json()
    except json.JSONDecodeError:
        raise web.HTTPBadRequest(reason="Invalid JSON")

    offerings        = body.get("offerings", [])
    recommended      = body.get("recommended_provider", "")
    ranker_summary   = body.get("rank_and_select_summary") or ""

    # Build a detailed per-offering block sorted by rank.
    lines: list[str] = []
    for o in sorted(offerings, key=lambda x: (x.get("rank") or 999)):
        score = o.get("composite_score")
        score_str = f"{score * 100:.0f}%" if score is not None else "—"
        dh        = o.get("delivery_hours")
        delivery  = f"{dh}h" if dh else "unknown"
        tag       = " ← SELECTED" if o.get("is_recommended") else ""
        currency  = o.get("currency", "INR")
        price     = o.get("price", 0)
        rank      = o.get("rank") or "?"
        lines.append(
            f"  Rank #{rank} — {o.get('provider', '?')}{tag}\n"
            f"    Price: {currency} {price:,.2f}/unit | Delivery: {delivery} | "
            f"Composite score: {score_str}"
        )
        for sd in o.get("score_details", []):
            lines.append(
                f"    • {sd.get('criterion', '')}: {sd.get('explanation', '')} "
                f"(raw={sd.get('raw', '')}, normalized={sd.get('normalized', 0):.3f})"
            )

    offerings_block = "\n".join(lines) if lines else "  (no data)"
    ranker_note     = f"\nScoring model output: {ranker_summary}" if ranker_summary else ""

    prompt = (
        f"A procurement AI ranked {len(offerings)} supplier(s) and selected "
        f"{recommended!r} as the best option.\n\n"
        f"Full comparison:\n{offerings_block}"
        f"{ranker_note}\n\n"
        f"In 2-3 plain sentences, explain to a procurement officer why "
        f"{recommended!r} was the optimal choice compared to the other supplier(s). "
        f"Be specific: reference price differences, delivery speed, and scoring details "
        f"from the data above. Do not use bullet points."
    )

    ollama_url  = os.getenv("OLLAMA_URL", "http://host.docker.internal:11434/v1")
    simple_model = os.getenv("SIMPLE_MODEL", "qwen3:1.7b")

    try:
        client   = AsyncOpenAI(base_url=ollama_url, api_key="ollama")
        response = await client.chat.completions.create(
            model=simple_model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a concise B2B procurement assistant. "
                        "Reply with exactly 2-3 plain sentences. "
                        "No preamble, no bullet points, no markdown formatting. /no_think"
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.3,
            max_tokens=350,
        )
        raw     = response.choices[0].message.content or ""
        cleaned = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
        return web.json_response({"explanation": cleaned})
    except Exception as exc:
        logger.error("explain-selection LLM call failed: %s", exc)
        return web.json_response({"explanation": ""}, status=502)


def create_app() -> web.Application:
    app = web.Application()
    app.router.add_get("/health",             health)
    app.router.add_post("/parse",             parse)
    app.router.add_post("/explain-selection", explain_selection)
    return app


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    port = int(os.getenv("PORT", "8001"))
    web.run_app(create_app(), host="0.0.0.0", port=port)
