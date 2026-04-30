"""FastAPI application for the IntentParser service.

Endpoints:
  POST /parse        — Stage 1+2 (sync, backward compat)
  POST /parse/batch  — Stage 1+2 batch (sync)
  POST /parse/full   — Stage 1+2+3 with recovery (async, production)
"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from pydantic import BaseModel

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
