"""Synchronous Stage 1+2 pipeline — backward-compatible entry point.

Delegates to the async orchestrator.  Callers that can use async
should import from orchestrator directly.
"""
from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor

from .models import BecknIntent, ParseResponse  # noqa: F401
from .orchestrator import parse_procurement_request
from .schemas import ParseResult

_POOL = ThreadPoolExecutor(max_workers=4, thread_name_prefix="intent-sync")


def _run(query: str) -> ParseResponse:
    """Run the async pipeline in a dedicated thread with its own event loop."""
    return asyncio.run(parse_procurement_request(query, enable_stage3=False))


def parse_request(query: str) -> ParseResult:
    """Synchronous Stage 1+2 parse — used by tests and legacy callers."""
    resp = _run(query)
    return ParseResult(
        intent=resp.intent,
        confidence=resp.confidence,
        beckn_intent=resp.beckn_intent,
        routed_to=resp.routed_to,
    )


def parse_batch(queries: list[str], max_workers: int = 4) -> list[ParseResult]:
    """Synchronous batch — uses a thread pool so each call gets its own loop."""
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        return list(pool.map(parse_request, queries))
