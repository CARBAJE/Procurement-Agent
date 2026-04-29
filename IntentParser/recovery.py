"""Day-2 recovery actions for CACHE_MISS + not_found scenarios.

All functions are async stubs that log intent; replace stubs with real
integrations (DB logging, notification service, RFQ microservice) as
infrastructure is provisioned.
"""
from __future__ import annotations

import logging
import re
from typing import Optional

from .config import ANTHROPIC_API_KEY, CLAUDE_FALLBACK_ENABLED, CLAUDE_MODEL
from .models import BecknIntent

logger = logging.getLogger(__name__)

# ── Query broadening ──────────────────────────────────────────────────────────

_SPEC_STRIP_PATTERNS = (
    re.compile(r"\b\d+\s*(?:units?|pcs?|pieces?|nos?|numbers?)\b", re.I),
    re.compile(r"\b(?:ASTM|ISO|DIN|EN|BS|IS)\s*[A-Z]?\d+[\w\-]*\b"),
    re.compile(r"\b(?:grade|class|type|series)\s+\S+\b", re.I),
    re.compile(r"\b(?:PN|DN|NPS|SCH|ANSI)\s*\d+\b", re.I),
    re.compile(r"\b\d+(?:\.\d+)?\s*(?:inch|mm|cm|m|ft|bar|psi|kpa|mpa|hp|kw|v|a|hz)\b", re.I),
    re.compile(r"\bS\d{5}\b"),
)


def _strip_specs(text: str) -> str:
    """Remove technical spec tokens from a free-text string."""
    for pat in _SPEC_STRIP_PATTERNS:
        text = pat.sub("", text)
    return " ".join(text.split())


async def _broaden_via_claude(beckn_intent: BecknIntent) -> Optional[str]:
    """Ask Claude to suggest a broader, simpler item name."""
    if not CLAUDE_FALLBACK_ENABLED:
        return None
    try:
        import anthropic

        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        specs = ", ".join(beckn_intent.descriptions[:6]) if beckn_intent.descriptions else "none"
        prompt = (
            f"A procurement search for '{beckn_intent.item}' (specs: {specs}) "
            "returned no results in the BPP catalog network.\n"
            "Suggest ONE broader, simpler product name that is more likely to "
            "exist in a general industrial supplier catalog.\n"
            "Reply with ONLY the product name — no explanation, no punctuation."
        )
        message = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=64,
            messages=[{"role": "user", "content": prompt}],
        )
        return message.content[0].text.strip()
    except Exception as exc:
        logger.warning("Claude broadening failed: %s", exc)
        return None


async def broaden_procurement_query(
    beckn_intent: BecknIntent,
) -> Optional[BecknIntent]:
    """Return a broadened BecknIntent or None if broadening is not possible.

    Strategy:
    1. Strip the most specific spec tokens from item_name + descriptions.
    2. If >= 2 tokens remain, return broadened intent.
    3. Otherwise ask Claude for a generic category name.
    """
    stripped_item = _strip_specs(beckn_intent.item)
    kept_descriptions = [
        d for d in beckn_intent.descriptions
        if not any(pat.search(d) for pat in _SPEC_STRIP_PATTERNS)
    ]

    if len(stripped_item.split()) >= 2:
        return BecknIntent(
            item=stripped_item,
            descriptions=kept_descriptions,
            quantity=beckn_intent.quantity,
            location_coordinates=beckn_intent.location_coordinates,
            delivery_timeline=beckn_intent.delivery_timeline,
            budget_constraints=beckn_intent.budget_constraints,
        )

    broadened_name = await _broaden_via_claude(beckn_intent)
    if not broadened_name:
        return None

    return BecknIntent(
        item=broadened_name,
        descriptions=[],
        quantity=beckn_intent.quantity,
        location_coordinates=beckn_intent.location_coordinates,
        delivery_timeline=beckn_intent.delivery_timeline,
        budget_constraints=beckn_intent.budget_constraints,
    )


# ── Downstream actions ────────────────────────────────────────────────────────


async def log_unmet_demand(beckn_intent: BecknIntent) -> None:
    """Persist an unmet-demand record for analytics and supplier outreach."""
    logger.info(
        "UNMET_DEMAND | item=%s | specs=%s | qty=%s | location=%s",
        beckn_intent.item,
        beckn_intent.descriptions,
        beckn_intent.quantity,
        beckn_intent.location_coordinates,
    )


async def notify_buyer_no_stock(item_name: str) -> None:
    """Send buyer a no-stock notification (stub — replace with notification service)."""
    logger.info("BUYER_NOTIFY | no stock found for: %s", item_name)


async def trigger_open_rfq_flow(beckn_intent: BecknIntent) -> None:
    """Initiate an open RFQ broadcast (stub — replace with RFQ microservice call)."""
    logger.info(
        "OPEN_RFQ | item=%s | qty=%s | location=%s",
        beckn_intent.item,
        beckn_intent.quantity,
        beckn_intent.location_coordinates,
    )
