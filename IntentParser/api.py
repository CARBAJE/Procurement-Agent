"""FastAPI application for the IntentParser service.

Endpoints:
  POST /parse               — Stage 1+2 (sync, backward compat)
  POST /parse/batch         — Stage 1+2 batch (sync)
  POST /parse/full          — Stage 1+2+3 with recovery (async, production)
  POST /explain-selection   — LLM natural-language explanation for scoring decision
"""
from __future__ import annotations

import re
from contextlib import asynccontextmanager

from fastapi import FastAPI
from openai import AsyncOpenAI
from pydantic import BaseModel

from .config import OLLAMA_URL, SIMPLE_MODEL
from .core import parse_batch, parse_request
from .db import close_pool, init_pool
from .models import ParseResponse
from .orchestrator import parse_procurement_request
from .schemas import ParseResult


@asynccontextmanager
async def _lifespan(app: FastAPI):
    await init_pool()
    yield
    await close_pool()


app = FastAPI(
    title="Beckn Intent Parser",
    version="2.0",
    lifespan=_lifespan,
)


class _Query(BaseModel):
    query: str


class _Batch(BaseModel):
    queries: list[str]
    max_workers: int = 4


class _OfferingScoreDetail(BaseModel):
    criterion: str
    raw: str
    normalized: float
    explanation: str


class _OfferingBrief(BaseModel):
    provider: str
    item: str
    price: float
    currency: str = "INR"
    delivery_hours: int | None = None
    composite_score: float | None = None
    rank: int | None = None
    is_recommended: bool = False
    score_details: list[_OfferingScoreDetail] = []


class _ExplainRequest(BaseModel):
    offerings: list[_OfferingBrief]
    recommended_provider: str
    rank_and_select_summary: str | None = None


class _ExplainResponse(BaseModel):
    explanation: str


# ── Stage 1+2 (legacy) ────────────────────────────────────────────────────────


@app.post("/parse", response_model=ParseResult)
def parse(req: _Query) -> ParseResult:
    return parse_request(req.query)


@app.post("/parse/batch", response_model=list[ParseResult])
def batch(req: _Batch) -> list[ParseResult]:
    return parse_batch(req.queries, req.max_workers)


# ── Stage 1+2+3 with recovery (production) ───────────────────────────────────


@app.post("/parse/full", response_model=ParseResponse)
async def parse_full(req: _Query) -> ParseResponse:
    return await parse_procurement_request(req.query)


# ── Scoring explanation (LLM) ────────────────────────────────────────────────


@app.post("/explain-selection", response_model=_ExplainResponse)
async def explain_selection(req: _ExplainRequest) -> _ExplainResponse:
    """Generate a 2-3 sentence natural-language explanation for why the scoring
    model chose the recommended supplier over the alternatives."""

    # Build a detailed per-offering block sorted by rank so the LLM can compare.
    offering_lines: list[str] = []
    for o in sorted(req.offerings, key=lambda x: (x.rank or 999)):
        score_str = f"{o.composite_score * 100:.0f}%" if o.composite_score is not None else "—"
        delivery  = f"{o.delivery_hours}h" if o.delivery_hours else "unknown"
        tag       = " ← SELECTED" if o.is_recommended else ""
        offering_lines.append(
            f"  Rank #{o.rank or '?'} — {o.provider}{tag}\n"
            f"    Price: {o.currency} {o.price:,.2f}/unit | Delivery: {delivery} | "
            f"Composite score: {score_str}"
        )
        for sd in o.score_details:
            offering_lines.append(
                f"    • {sd.criterion}: {sd.explanation} (raw={sd.raw}, normalized={sd.normalized:.3f})"
            )

    offerings_block = "\n".join(offering_lines) if offering_lines else "  (no data)"

    ranker_note = ""
    if req.rank_and_select_summary:
        ranker_note = f"\nScoring model output: {req.rank_and_select_summary}"

    prompt = (
        f"A procurement AI ranked {len(req.offerings)} supplier(s) and selected "
        f"{req.recommended_provider!r} as the best option.\n\n"
        f"Full comparison:\n{offerings_block}"
        f"{ranker_note}\n\n"
        f"In 2-3 plain sentences, explain to a procurement officer why "
        f"{req.recommended_provider!r} was the optimal choice compared to the other "
        f"supplier(s). Be specific: reference price differences, delivery speed, "
        f"and scoring details from the data above. Do not use bullet points."
    )

    client = AsyncOpenAI(base_url=OLLAMA_URL, api_key="ollama")
    response = await client.chat.completions.create(
        model=SIMPLE_MODEL,
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
    raw = response.choices[0].message.content or ""
    # Strip <think>…</think> blocks that reasoning models may emit.
    cleaned = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
    return _ExplainResponse(explanation=cleaned)
