"""Full async procurement parsing pipeline.

Stage 1 → Stage 2 → Stage 3 → (optional) recovery flow.

All public functions are async coroutines.  The sync compat wrapper in
core.py exposes parse_request() for callers that cannot use async.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Optional

from .config import COMPLEX_MODEL, PROCUREMENT_INTENTS, SIMPLE_MODEL
from .llm_clients import get_json_client
from .models import BecknIntent, ParsedIntent, ParseResponse, ValidationResult, ValidationZone
from .recovery import (
    broaden_procurement_query,
    log_unmet_demand,
    notify_buyer_no_stock,
    trigger_open_rfq_flow,
)
from .validation import run_stage3_hybrid_validation

logger = logging.getLogger(__name__)

# ── Prompts ───────────────────────────────────────────────────────────────────

_INTENT_PROMPT = (
    "You are an intent classifier for a Beckn-based procurement system.\n"
    "Classify the user query into a PascalCase intent.\n"
    "Procurement intents: SearchProduct, RequestQuote, PurchaseOrder, TrackOrder, CancelOrder.\n"
    "If the query is a greeting, general question, or unrelated to procurement, return GeneralInquiry."
)

_BECKN_PROMPT = (
    "You are a procurement data extractor for the Beckn protocol. "
    "Extract structured data from the user query.\n"
    "- descriptions: all technical specs (e.g. '80gsm', 'A4', 'Cat6', '2 inch')\n"
    "- delivery_timeline: convert to hours — 1 day=24h, 1 week=168h\n"
    "- budget: numeric values only, no currency symbols; if only upper bound given, set min=0\n"
    "- location lookup: Bangalore/Bengaluru=12.9716,77.5946 | Mumbai=19.0760,72.8777 |\n"
    "  Delhi=28.7041,77.1025 | Chennai=13.0827,80.2707 | Hyderabad=17.3850,78.4867 |\n"
    "  Pune=18.5204,73.8567 | Kolkata=22.5726,88.3639 | unknown city → raw text"
)

# ── Complexity routing ────────────────────────────────────────────────────────

import re as _re

_COMPLEX_KEYWORDS = frozenset({
    "delivery", "deliver", "timeline", "deadline", "days", "weeks", "hours", "within",
    "budget", "price", "cost", "rupee", "rupees", "inr", "usd",
    "per unit", "per sheet", "per meter", "under", "maximum", "max",
})


def _is_complex(query: str) -> bool:
    lower = query.lower()
    return (
        len(query) > 120
        or len(_re.findall(r"\b\d+(?:\.\d+)?\b", query)) >= 2
        or any(kw in lower for kw in _COMPLEX_KEYWORDS)
    )


# ── Stage helpers ─────────────────────────────────────────────────────────────


async def classify_intent(query: str) -> ParsedIntent:
    """Stage 1 — classify NL query into a procurement intent."""
    client = get_json_client()
    return await client.chat.completions.create(
        model=COMPLEX_MODEL,
        messages=[
            {"role": "system", "content": _INTENT_PROMPT},
            {"role": "user", "content": query},
        ],
        response_model=ParsedIntent,
        max_retries=3,
    )


async def extract_beckn_intent(query: str) -> tuple[BecknIntent, str]:
    """Stage 2 — extract structured BecknIntent; also returns model used."""
    client = get_json_client()
    model = COMPLEX_MODEL if _is_complex(query) else SIMPLE_MODEL
    try:
        result = await client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": _BECKN_PROMPT},
                {"role": "user", "content": query},
            ],
            response_model=BecknIntent,
            max_retries=3,
        )
        return result, model
    except Exception:
        if model == SIMPLE_MODEL:
            result = await client.chat.completions.create(
                model=COMPLEX_MODEL,
                messages=[
                    {"role": "system", "content": _BECKN_PROMPT},
                    {"role": "user", "content": query},
                ],
                response_model=BecknIntent,
                max_retries=3,
            )
            return result, COMPLEX_MODEL
        raise


# ── Validation result → dict (for API response) ───────────────────────────────


def _validation_to_dict(vr: Optional[ValidationResult]) -> Optional[dict]:
    if vr is None:
        return None
    d: dict = {"status": vr.zone.value}
    if vr.top_match:
        d["matched"] = vr.top_match.item_name
        d["bpp_id"] = vr.top_match.bpp_id
        d["similarity"] = round(vr.top_match.similarity, 4)
    if vr.mcp_validated:
        d["status"] = "MCP_VALIDATED"
        d["matched"] = vr.mcp_item_name
        d["bpp_id"] = vr.mcp_bpp_id
        d["bpp_uri"] = vr.mcp_bpp_uri
    if vr.not_found:
        d["not_found"] = True
    if vr.broadened_item_name:
        d["broadened_to"] = vr.broadened_item_name
    return d


# ── Main entry point ──────────────────────────────────────────────────────────


async def parse_procurement_request(
    query: str,
    enable_stage3: bool = True,
) -> ParseResponse:
    """Full E2E pipeline: Stage 1 → 2 → 3 → optional recovery.

    Parameters
    ----------
    query:
        Raw natural-language procurement request from the buyer.
    enable_stage3:
        Set False to skip validation (e.g. during testing without a DB).
    """
    # ── Stage 1 ───────────────────────────────────────────────────────────────
    parsed_intent = await classify_intent(query)

    if parsed_intent.intent not in PROCUREMENT_INTENTS:
        return ParseResponse(
            intent=parsed_intent.intent,
            confidence=parsed_intent.confidence,
        )

    # ── Stage 2 ───────────────────────────────────────────────────────────────
    try:
        beckn_intent, model_used = await extract_beckn_intent(query)
    except Exception as exc:
        logger.error("Stage 2 extraction failed: %s", exc)
        return ParseResponse(
            intent=parsed_intent.intent,
            confidence=parsed_intent.confidence,
        )

    if not enable_stage3:
        return ParseResponse(
            intent=parsed_intent.intent,
            confidence=parsed_intent.confidence,
            beckn_intent=beckn_intent,
            routed_to=model_used,
        )

    # ── Stage 3 ───────────────────────────────────────────────────────────────
    validation_result: Optional[ValidationResult] = None
    try:
        validation_result = await run_stage3_hybrid_validation(beckn_intent)
    except Exception as exc:
        logger.warning("Stage 3 failed (continuing without validation): %s", exc)

    recovery_log: list[str] = []

    if validation_result is not None and validation_result.not_found:
        # ── Recovery flow ─────────────────────────────────────────────────────
        broadened = await broaden_procurement_query(beckn_intent)

        if broadened is not None:
            recovery_log.append(f"Broadened query to: {broadened.item}")
            try:
                validation_result = await run_stage3_hybrid_validation(broadened)
                if not validation_result.not_found:
                    validation_result.broadened_item_name = broadened.item
                    beckn_intent = broadened
            except Exception as exc:
                logger.warning("Stage 3 retry after broadening failed: %s", exc)

        if validation_result is not None and validation_result.not_found:
            recovery_log.append("No BPP catalog match. Logging unmet demand and triggering RFQ.")
            await asyncio.gather(
                log_unmet_demand(beckn_intent),
                notify_buyer_no_stock(beckn_intent.item),
                trigger_open_rfq_flow(beckn_intent),
                return_exceptions=True,
            )

    return ParseResponse(
        intent=parsed_intent.intent,
        confidence=parsed_intent.confidence,
        beckn_intent=beckn_intent,
        validation=_validation_to_dict(validation_result),
        recovery_log=recovery_log,
        routed_to=model_used,
    )
