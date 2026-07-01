"""Step Functions local simulator — orchestrates the 4-step procurement pipeline.

State machine:
  Step 1 — Intention Parser  (POST /parse)
  Step 2 — Beckn BAP Client  (POST /discover)
  Step 3 — Comparative Score (POST /score)
  Step 4 — Beckn BAP Client  (POST /select)

Exposes:
  POST /run      { "query": "..." }           Full 4-step pipeline (NL → select)
  POST /parse    { "query": "..." }           Proxy to intention-parser
  POST /discover BecknIntent JSON             Steps 2→3→4 (pre-parsed intent)
  POST /compare  BecknIntent JSON             Steps 2→3 only, stores session
  POST /commit   { transaction_id, chosen_item_id }  select→init→confirm
  GET  /status/{txn_id}/{order_id}            Poll order lifecycle
  GET  /health

Service URLs are read from env vars so the orchestrator works both in Docker
(service names) and locally (localhost + ports).
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import time
from decimal import Decimal
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import aiohttp
from aiohttp import web

# Make `erp` importable when this file is launched as `python src/workflow.py`
sys.path.insert(0, os.path.dirname(__file__))

from erp import BudgetCheckRequest, ErpAdapterClient, build_normalized_po  # noqa: E402

logger = logging.getLogger(__name__)

# ── Service URLs (set via env vars in docker-compose) ─────────────────────────

INTENTION_PARSER_URL     = os.getenv("INTENTION_PARSER_URL",     "http://localhost:8001")
BECKN_BAP_URL            = os.getenv("BECKN_BAP_URL",            "http://localhost:8002")
COMPARATIVE_SCORING_URL  = os.getenv("COMPARATIVE_SCORING_URL",  "http://localhost:8003")
DATA_NORMALIZER_URL      = os.getenv("DATA_NORMALIZER_URL",      "http://localhost:8006")

ANALYTICS_URL = os.getenv("ANALYTICS_URL", "http://localhost:8009")

# ── ERP adapter (synchronous budget gate + outbox sync) ──────────────────────

ERP_ADAPTER_URL            = os.getenv("ERP_ADAPTER_URL",            "http://localhost:8007")
ERP_INTERNAL_TOKEN         = os.getenv("ERP_INTERNAL_TOKEN",         "dev-internal-token-CHANGE_ME")
ERP_BUDGET_CHECK_ENABLED   = os.getenv("ERP_BUDGET_CHECK_ENABLED",   "true").lower() == "true"
ERP_BUDGET_CHECK_REQUIRED  = os.getenv("ERP_BUDGET_CHECK_REQUIRED",  "false").lower() == "true"
ERP_BUDGET_CHECK_TIMEOUT_MS = int(os.getenv("ERP_BUDGET_CHECK_TIMEOUT_MS", "800"))
ERP_SYNC_ENABLED           = os.getenv("ERP_SYNC_ENABLED",           "true").lower() == "true"
ERP_DEFAULT_COST_CENTER    = os.getenv("ERP_DEFAULT_COST_CENTER",    "CC-IND-PROC-01")

# Redis is used in M3.3 only to receive ERP status updates published by the
# adapter on `po.status_changed:{txn_id}`. When Redis is unreachable the
# orchestrator still serves /status from the Beckn poll alone — no regression.
REDIS_URL                  = os.getenv("REDIS_URL",                  "")
ERP_STATE_CACHE_TTL_SECS   = int(os.getenv("ERP_STATE_CACHE_TTL_SECS", "3600"))

# ── Buyer billing config (mirrors Bap-1's ConfigBillingProvider) ─────────────

BUYER_NAME              = os.getenv("BUYER_NAME",              "Procurement Agent")
BUYER_EMAIL             = os.getenv("BUYER_EMAIL",             "procurement@example.com")
BUYER_PHONE             = os.getenv("BUYER_PHONE",             "+91-0000000000")
BUYER_ADDRESS_STREET    = os.getenv("BUYER_ADDRESS_STREET",    "")
BUYER_ADDRESS_CITY      = os.getenv("BUYER_ADDRESS_CITY",      "Bangalore")
BUYER_ADDRESS_STATE     = os.getenv("BUYER_ADDRESS_STATE",     "Karnataka")
BUYER_ADDRESS_AREA_CODE = os.getenv("BUYER_ADDRESS_AREA_CODE", "560100")
BUYER_ADDRESS_COUNTRY   = os.getenv("BUYER_ADDRESS_COUNTRY",   "IND")

# ── Session store (in-memory, 30-minute TTL, lazy expiry) ────────────────────

_sessions: dict[str, dict] = {}
_session_times: dict[str, float] = {}
SESSION_TTL = 1800  # seconds

# ── Pending approvals (in-memory, keyed by request_id) ───────────────────────
# Populated by /commit when order_total > user's approval_threshold.
# Consumed by /approvals (list) and /approvals/{id}/decide (approve/reject).
_pending_approvals: dict[str, dict] = {}

# ── ERP inbound state cache (populated by the Redis psubscribe task) ─────────
# Keyed by transaction_id. Each entry carries the most-recent inbound webhook
# payload from the ERP adapter (state, erp_reference_id, vendor, event_ts, …).
# `/status` reads from this cache to enrich the Beckn response.
_erp_state_cache: dict[str, dict] = {}
_erp_state_times: dict[str, float] = {}


def _session_put(txn_id: str, state: dict) -> None:
    _sessions[txn_id] = state
    _session_times[txn_id] = time.monotonic()


def _session_get(txn_id: str) -> dict | None:
    if txn_id not in _sessions:
        return None
    if time.monotonic() - _session_times[txn_id] > SESSION_TTL:
        _sessions.pop(txn_id, None)
        _session_times.pop(txn_id, None)
        return None
    return _sessions[txn_id]


# ── Helpers ───────────────────────────────────────────────────────────────────

_erp_client: ErpAdapterClient | None = None


def _get_erp_client() -> ErpAdapterClient:
    """Lazy singleton — built on first use. Keeping the orchestrator's existing
    style of module-level state instead of routing through web.Application["..."].
    """
    global _erp_client
    if _erp_client is None:
        _erp_client = ErpAdapterClient(
            base_url=ERP_ADAPTER_URL,
            internal_token=ERP_INTERNAL_TOKEN,
            timeout_ms=ERP_BUDGET_CHECK_TIMEOUT_MS,
            budget_check_required=ERP_BUDGET_CHECK_REQUIRED,
        )
    return _erp_client


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _build_billing_info() -> dict:
    """Build billing dict from BUYER_* env vars (mirrors Bap-1's ConfigBillingProvider).

    Returns a plain dict — beckn-bap-client deserialises it into BillingInfo.
    """
    address: dict = {
        "city":      BUYER_ADDRESS_CITY,
        "area_code": BUYER_ADDRESS_AREA_CODE,
        "country":   BUYER_ADDRESS_COUNTRY,
    }
    if BUYER_ADDRESS_STREET:
        address["street"] = BUYER_ADDRESS_STREET
    if BUYER_ADDRESS_STATE:
        address["state"] = BUYER_ADDRESS_STATE
    return {
        "name":    BUYER_NAME,
        "email":   BUYER_EMAIL,
        "phone":   BUYER_PHONE,
        "address": address,
    }


def _build_buyer_dict() -> dict:
    """Buyer block embedded in NormalizedPO for the ERP adapter (M3.2)."""
    return {
        "id": None,
        "name": BUYER_NAME,
        "email": BUYER_EMAIL,
        "phone": BUYER_PHONE,
        "tax_id": None,
        "cost_center": ERP_DEFAULT_COST_CENTER,
        "address": {
            "street":    BUYER_ADDRESS_STREET,
            "city":      BUYER_ADDRESS_CITY,
            "state":     BUYER_ADDRESS_STATE,
            "area_code": BUYER_ADDRESS_AREA_CODE,
            "country":   BUYER_ADDRESS_COUNTRY,
        },
    }


def _build_fulfillment_info(intent: dict) -> dict:
    """Derive fulfillment dict from the session's BecknIntent (mirrors Bap-1's ConfigFulfillmentProvider).

    end_location: intent.location_coordinates or default Bangalore coords.
    end_address:  same as billing address (delivery to buyer's office).
    delivery_timeline: from intent (hours).
    """
    end_location = intent.get("location_coordinates") or "12.9716,77.5946"
    end_address: dict = {
        "city":      BUYER_ADDRESS_CITY,
        "area_code": BUYER_ADDRESS_AREA_CODE,
        "country":   BUYER_ADDRESS_COUNTRY,
    }
    if BUYER_ADDRESS_STREET:
        end_address["street"] = BUYER_ADDRESS_STREET
    if BUYER_ADDRESS_STATE:
        end_address["state"] = BUYER_ADDRESS_STATE
    out: dict = {
        "type":          "Delivery",
        "end_location":  end_location,
        "end_address":   end_address,
        "contact_name":  BUYER_NAME,
        "contact_phone": BUYER_PHONE,
    }
    if intent.get("delivery_timeline"):
        out["delivery_timeline"] = intent["delivery_timeline"]
    return out


def _build_ml_scoring(
    offerings: list[dict],
    ml_scoring: dict,
    recommended_item_id: str | None,
) -> dict:
    """Build the frontend ``Scoring`` shape from the ML model's ranking.

    Uses the RankNet scores returned by prediction-api (via the
    comparative-scoring adapter) instead of the price heuristic. Same shape
    the frontend renders — ``{recommended_item_id, criteria[], ranking[]}`` —
    with a single "ML Score (RankNet)" criterion (direction=max).
    """
    ranking_in = ml_scoring.get("ranking") or []
    by_id = {r["item_id"]: r for r in ranking_in}
    scores = [float(r.get("score", 0.0)) for r in ranking_in] or [0.0]
    s_min, s_max = min(scores), max(scores)
    spread = (s_max - s_min) or 1.0

    rank_scores = []
    for o in offerings:
        r = by_id.get(o["item_id"])
        raw = float(r["score"]) if r else 0.0
        normalized = (raw - s_min) / spread  # higher ML score → closer to 1
        rank_no = r["rank"] if r else len(offerings)
        rank_scores.append({
            "item_id": o["item_id"],
            "raw": f"{raw:.4f}",
            "normalized": round(normalized, 4),
            "explanation": (
                f"RankNet score {raw:.3f} (rank #{rank_no})"
                + (" — recommended" if o["item_id"] == recommended_item_id else "")
            ),
        })

    ranking = sorted(
        [{"item_id": s["item_id"], "composite_score": s["normalized"], "rank": 0}
         for s in rank_scores],
        key=lambda r: -r["composite_score"],
    )
    for idx, row in enumerate(ranking, start=1):
        row["rank"] = idx

    model_version = ml_scoring.get("model_version") or "unknown"
    return {
        "recommended_item_id": recommended_item_id,
        "criteria": [
            {
                "key": "ml_score",
                "label": f"ML Score · RankNet ({model_version})",
                "weight": 1.0,
                "direction": "max",
                "scores": rank_scores,
            }
        ],
        "ranking": ranking,
    }


# Maps the Beckn order state (BPP-reported) to our po_status_type enum.
# Unknown states return None so the caller can skip the persist call.
_BECKN_STATE_TO_PO_STATUS = {
    "CREATED":           "pending",
    "ACCEPTED":          "confirmed",
    "PACKED":            "confirmed",
    "SHIPPED":           "shipped",
    "OUT_FOR_DELIVERY":  "shipped",
    "DELIVERED":         "delivered",
    "CANCELLED":         "cancelled",
}


def _beckn_state_to_po_status(beckn_state: str) -> str | None:
    """Return the po_status_type value for a Beckn order state, or None."""
    return _BECKN_STATE_TO_PO_STATUS.get((beckn_state or "").upper())


def _build_scoring(offerings: list[dict], recommended_item_id: str | None) -> dict:
    """Price-based scoring — lower price = higher score.

    Produces a multi-criterion-ready shape with a single price criterion.
    TODO(comparison-engine): swap for strategy-based scoring when the
    Comparison Engine ships.
    """
    if not offerings:
        return {"recommended_item_id": None, "criteria": [], "ranking": []}

    prices = [float(o["price_value"]) for o in offerings]
    p_min, p_max = min(prices), max(prices)
    spread = (p_max - p_min) or 1.0

    price_scores = []
    for o in offerings:
        raw = float(o["price_value"])
        normalized = 1.0 - (raw - p_min) / spread
        explanation = (
            "Cheapest option" if raw == p_min else
            f"₹{raw - p_min:.2f} above cheapest"
        )
        price_scores.append({
            "item_id": o["item_id"],
            "raw": o["price_value"],
            "normalized": round(normalized, 4),
            "explanation": explanation,
        })

    ranking = sorted(
        [
            {
                "item_id": s["item_id"],
                "composite_score": s["normalized"],
                "rank": 0,
            }
            for s in price_scores
        ],
        key=lambda r: -r["composite_score"],
    )
    for idx, row in enumerate(ranking, start=1):
        row["rank"] = idx

    return {
        "recommended_item_id": recommended_item_id,
        "criteria": [
            {
                "key": "price",
                "label": "Price",
                "weight": 1.0,
                "direction": "min",
                "scores": price_scores,
            }
        ],
        "ranking": ranking,
    }


def _local_catalog_as_offerings() -> list[dict]:
    """Convert the local catalog to DiscoverOffering-shaped dicts for mock fallback."""
    result = []
    for item in _LOCAL_CATALOG:
        provider = item.get("provider", {})
        price = item.get("price", {})
        rating_obj = item.get("rating", {})
        rating = str(rating_obj.get("ratingValue", "")) if isinstance(rating_obj, dict) else None
        qty = item.get("quantity", {}).get("available", {}).get("count")
        result.append({
            "bpp_id": "bpp.example.com",
            "bpp_uri": "http://onix-bpp:8082/bpp/receiver",
            "provider_id": provider.get("id", ""),
            "provider_name": provider.get("descriptor", {}).get("name", ""),
            "item_id": item.get("id", ""),
            "item_name": item.get("descriptor", {}).get("name", ""),
            "price_value": price.get("value", "0"),
            "price_currency": price.get("currency", "INR"),
            "available_quantity": qty,
            "rating": rating,
            "specifications": item.get("specifications", []),
            "fulfillment_hours": item.get("fulfillmentHours"),
        })
    return result


# ── Local catalog (6 items) — used when beckn-bap-client is unreachable ───────
# Same catalog as Bap-1/src/server.py for consistency between the two modes.

_LOCAL_CATALOG = [
    {
        "id": "item-a4-paperdirect",
        "descriptor": {
            "name": "A4 Paper 80gsm Ream",
            "shortDesc": "Standard A4 80gsm ream, 500 sheets",
        },
        "provider": {"id": "PROV-PAPERDIRECT-01", "descriptor": {"name": "PaperDirect India"}},
        "price": {"value": "168.00", "currency": "INR"},
        "rating": {"ratingValue": 4.2},
        "quantity": {"available": {"count": 5000}},
        "fulfillmentHours": 48,
        "specifications": ["Brightness 92", "Recycled 30%", "ISO 9001"],
    },
    {
        "id": "item-a4-officeworld",
        "descriptor": {
            "name": "A4 Paper 80gsm (500 sheets)",
            "shortDesc": "Trusted brand A4 paper, office grade",
        },
        "provider": {"id": "PROV-OFFICEWORLD-01", "descriptor": {"name": "OfficeWorld Supplies"}},
        "price": {"value": "195.00", "currency": "INR"},
        "rating": {"ratingValue": 4.8},
        "quantity": {"available": {"count": 1000}},
        "fulfillmentHours": 24,
        "specifications": ["Brightness 96", "Recycled 50%", "FSC Certified"],
    },
    {
        "id": "item-a4-stathub-premium",
        "descriptor": {
            "name": "A4 Paper Premium 80gsm",
            "shortDesc": "Premium A4 paper, high brightness",
        },
        "provider": {"id": "PROV-STATHUB-01", "descriptor": {"name": "Stationery Hub"}},
        "price": {"value": "218.00", "currency": "INR"},
        "rating": {"ratingValue": 4.9},
        "quantity": {"available": {"count": 500}},
        "fulfillmentHours": 72,
        "specifications": ["Brightness 98", "FSC Certified", "Acid-free"],
    },
    {
        "id": "item-a4-greenleaf",
        "descriptor": {
            "name": "A4 Paper Eco 80gsm",
            "shortDesc": "100% recycled A4 paper",
        },
        "provider": {"id": "PROV-GREENLEAF-01", "descriptor": {"name": "GreenLeaf Papers"}},
        "price": {"value": "182.00", "currency": "INR"},
        "rating": {"ratingValue": 4.4},
        "quantity": {"available": {"count": 2000}},
        "fulfillmentHours": 96,
        "specifications": ["Brightness 88", "Recycled 100%", "FSC Certified"],
    },
    {
        "id": "item-a4-quickprint",
        "descriptor": {
            "name": "A4 Paper 80gsm Express",
            "shortDesc": "Same-day dispatch A4 paper",
        },
        "provider": {"id": "PROV-QUICKPRINT-01", "descriptor": {"name": "QuickPrint Depot"}},
        "price": {"value": "205.00", "currency": "INR"},
        "rating": {"ratingValue": 4.0},
        "quantity": {"available": {"count": 200}},
        "fulfillmentHours": 24,
        "specifications": ["Brightness 94", "ISO 9001"],
    },
    {
        "id": "item-a4-budgetpaper",
        "descriptor": {
            "name": "A4 Paper Basic 80gsm",
            "shortDesc": "Budget-friendly A4 paper",
        },
        "provider": {"id": "PROV-BUDGETPAPER-01", "descriptor": {"name": "Budget Paper Co"}},
        "price": {"value": "165.00", "currency": "INR"},
        "rating": {"ratingValue": 3.9},
        "quantity": {"available": {"count": 3000}},
        "fulfillmentHours": 120,
        "specifications": ["Brightness 85", "Recycled 20%"],
    },
]


# ── Pipeline ──────────────────────────────────────────────────────────────────


async def _post(session: aiohttp.ClientSession, url: str, body: dict) -> dict:
    """POST JSON to a service and return the parsed response dict."""
    async with session.post(url, json=body) as resp:
        resp.raise_for_status()
        return await resp.json()


async def _persist(session: aiohttp.ClientSession, path: str, body: dict) -> dict:
    """POST to Data Normalizer with retries. Never raises — logs on failure."""
    if not DATA_NORMALIZER_URL:
        return {}
    for attempt in range(1, 4):  # 3 attempts
        try:
            async with session.post(
                f"{DATA_NORMALIZER_URL}{path}", json=body, timeout=aiohttp.ClientTimeout(total=5)
            ) as resp:
                if resp.status < 300:
                    return await resp.json()
                logger.warning(
                    "[data-normalizer] %s returned HTTP %s (attempt %s/3)",
                    path, resp.status, attempt,
                )
        except Exception as exc:
            logger.warning(
                "[data-normalizer] %s failed (attempt %s/3): %s",
                path, attempt, exc,
            )
        if attempt < 3:
            await asyncio.sleep(attempt)  # 1s, 2s entre reintentos
    logger.warning("[data-normalizer] %s gave up after 3 attempts — audit record lost", path)
    return {}


async def _persist_status(
    session: aiohttp.ClientSession,
    request_id: str,
    status: str,
    category: str | None = None,
) -> None:
    """PATCH /normalize/status — fire-and-forget update of procurement lifecycle.

    Used during the happy path (parsing → discovering → scoring → negotiating →
    confirmed). Silent on failure so an audit hiccup never derails the live
    user-facing flow. For user-triggered status changes (cancel), use
    _patch_status_strict instead so failures bubble up.

    `category` (optional) sets the supplier-declared category on the request —
    passed once discovery/scoring resolves the chosen offering's category.
    """
    if not DATA_NORMALIZER_URL or not request_id:
        return
    body: dict = {"request_id": request_id, "status": status}
    if category:
        body["category"] = category
    try:
        async with session.patch(
            f"{DATA_NORMALIZER_URL}/normalize/status",
            json=body,
            timeout=aiohttp.ClientTimeout(total=5),
        ) as resp:
            if resp.status >= 400:
                body = await resp.text()
                logger.warning(
                    "[data-normalizer] status=%s for %s returned HTTP %s: %s",
                    status, request_id, resp.status, body[:200],
                )
    except Exception as exc:
        logger.warning("[data-normalizer] status update skipped: %s", exc)


async def _patch_status_strict(
    session: aiohttp.ClientSession,
    request_id: str,
    status: str,
) -> None:
    """PATCH /normalize/status and raise on any failure.

    Used by the user-triggered /cancel route so a silent DB miss never returns
    a fake success to the frontend.
    """
    if not DATA_NORMALIZER_URL:
        raise RuntimeError("DATA_NORMALIZER_URL is not configured")
    if not request_id:
        raise ValueError("request_id is required")
    async with session.patch(
        f"{DATA_NORMALIZER_URL}/normalize/status",
        json={"request_id": request_id, "status": status},
        timeout=aiohttp.ClientTimeout(total=5),
    ) as resp:
        if resp.status >= 400:
            body = await resp.text()
            raise RuntimeError(
                f"/normalize/status returned HTTP {resp.status}: {body[:200]}"
            )


async def _persist_audit(
    session: aiohttp.ClientSession,
    event_type: str,
    agent_action: str,
    reasoning_payload: dict | None = None,
    request_id: str | None = None,
    po_id: str | None = None,
    actor_id: str | None = None,
) -> None:
    """POST /normalize/audit — fire-and-forget compliance event log.

    event_type must be one of the audit_event_type enum values (discover,
    normalize, score, negotiate, approve, confirm, override, erp_sync,
    notification). Silent on failure so audit hiccups never break the flow.
    """
    if not DATA_NORMALIZER_URL:
        return
    body: dict = {
        "event_type":        event_type,
        "agent_action":      agent_action,
        "reasoning_payload": reasoning_payload or {},
        "kafka_offset":      0,  # TODO(kafka): real offset when topic is wired
    }
    if request_id:
        body["request_id"] = request_id
    if po_id:
        body["po_id"] = po_id
    if actor_id:
        body["actor_id"] = actor_id
    try:
        async with session.post(
            f"{DATA_NORMALIZER_URL}/normalize/audit",
            json=body,
            timeout=aiohttp.ClientTimeout(total=5),
        ) as resp:
            if resp.status >= 400:
                text = await resp.text()
                logger.warning(
                    "[data-normalizer] audit %s returned HTTP %s: %s",
                    event_type, resp.status, text[:200],
                )
    except Exception as exc:
        logger.warning("[data-normalizer] audit skipped: %s", exc)


async def run_pipeline_from_intent(beckn_intent: dict, request_id: str | None = None) -> dict:
    """Execute Steps 2→3→4 of the state machine with a pre-parsed BecknIntent.

    Used by POST /discover (frontend-compatible endpoint) when the NL parse
    step has already happened and the user has confirmed the intent preview.

    Returns the same shape as run_pipeline() but without parse_result.
    """
    messages: list[str] = []

    async with aiohttp.ClientSession(
        headers={"Content-Type": "application/json"}
    ) as session:

        # ── Persist: create request record if not already created ─────────────
        if not request_id:
            nr = await _persist(session, "/normalize/request", {
                "raw_input_text": str(beckn_intent.get("item", "direct-intent")),
                "channel": "web",
            })
            request_id = nr.get("request_id", "")
            if request_id:
                await _persist_audit(
                    session, "normalize", "request_created",
                    reasoning_payload={"item": beckn_intent.get("item")},
                    request_id=request_id,
                )

        # ── Persist: normalize intent (pre-parsed — no NL classification) ─────
        beckn_intent_id = ""
        if request_id:
            ir = await _persist(session, "/normalize/intent", {
                "request_id":   request_id,
                "intent_class": "procurement",
                "confidence":   1.0,
                "model_version": "direct",
                "beckn_intent": beckn_intent,
            })
            beckn_intent_id = ir.get("beckn_intent_id", "")
            if beckn_intent_id:
                await _persist_audit(
                    session, "normalize", "intent_persisted",
                    reasoning_payload={"beckn_intent_id": beckn_intent_id, "intent": beckn_intent},
                    request_id=request_id,
                )
            await _persist_status(session, request_id, "discovering")

        # ── Step 2: Beckn BAP Client Lambda (discover) ───────────────────────
        logger.info("Step 2 — Beckn BAP Client /discover (from pre-parsed intent)")
        discover_result = await _post(
            session, f"{BECKN_BAP_URL}/discover", beckn_intent
        )
        transaction_id = discover_result.get("transaction_id", "")
        offerings = discover_result.get("offerings", [])
        messages.append(
            f"[beckn-bap-client] txn={transaction_id} "
            f"found {len(offerings)} offering(s)"
        )

        # ── Persist: discovery ────────────────────────────────────────────────
        query_id = ""
        offering_ids_map: dict[str, str] = {}
        if beckn_intent_id and offerings:
            dr = await _persist(session, "/normalize/discovery", {
                "beckn_intent_id": beckn_intent_id,
                "network_id": discover_result.get("network_id", "beckn-default"),
                "offerings": offerings,
            })
            query_id = dr.get("query_id", "")
            offering_ids_map = {
                o["item_id"]: o["offering_id"]
                for o in dr.get("offering_ids", [])
            }
            await _persist_status(session, request_id, "scoring")

        if not offerings:
            return {
                "transaction_id": transaction_id,
                "offerings": [],
                "selected": None,
                "messages": messages,
                "status": "live",
            }

        # ── Step 3: Comparative & Scoring Lambda ─────────────────────────────
        logger.info("Step 3 — Comparative Scoring /score")
        score_result = await _post(
            session, f"{COMPARATIVE_SCORING_URL}/score", {"offerings": offerings}
        )
        selected = score_result.get("selected")
        if selected:
            messages.append(
                f"[comparative-scoring] selected {selected.get('provider_name')!r} "
                f"₹{selected.get('price_value')} (cheapest of {len(offerings)})"
            )
        else:
            messages.append("[comparative-scoring] no offering selected")

        # ── Persist: scoring ──────────────────────────────────────────────────
        score_ids_map: dict[str, str] = {}
        if query_id and offering_ids_map:
            scoring_data = _build_scoring(
                offerings,
                selected.get("item_id") if selected else None,
            )
            scores_payload = []
            for rank_item in scoring_data.get("ranking", []):
                item_id = rank_item["item_id"]
                offering_id = offering_ids_map.get(item_id)
                if not offering_id:
                    continue
                price_val = next(
                    (o["price_value"] for o in offerings if o["item_id"] == item_id),
                    "0",
                )
                scores_payload.append({
                    "offering_id":    offering_id,
                    "rank":           rank_item["rank"],
                    "composite_score": rank_item["composite_score"],
                    "price_value":    price_val,
                })
            sr = await _persist(session, "/normalize/scoring", {
                "query_id": query_id,
                "scores":   scores_payload,
            })
            score_ids_map = {
                s["offering_id"]: s["score_id"]
                for s in sr.get("score_ids", [])
            }
            await _persist_audit(
                session, "score", f"scored {len(scores_payload)} offerings",
                reasoning_payload={
                    "recommended_item_id": selected.get("item_id") if selected else None,
                    "recommended_provider": (selected or {}).get("provider_name"),
                    "score_count": len(scores_payload),
                },
                request_id=request_id,
            )
            await _persist_status(session, request_id, "negotiating")

        if not selected:
            return {
                "transaction_id": transaction_id,
                "offerings": offerings,
                "selected": None,
                "messages": messages,
                "status": "live",
            }

        # ── Step 4: Beckn BAP Client Lambda (select) ─────────────────────────
        logger.info("Step 4 — Beckn BAP Client /select")
        select_body = {
            "transaction_id": transaction_id,
            "bpp_id":         selected.get("bpp_id", ""),
            "bpp_uri":        selected.get("bpp_uri", ""),
            "item_id":        selected.get("item_id", ""),
            "item_name":      selected.get("item_name", ""),
            "provider_id":    selected.get("provider_id", ""),
            "price_value":    selected.get("price_value", "0"),
            "price_currency": selected.get("price_currency", "INR"),
            "quantity":       beckn_intent.get("quantity", 1),
        }
        select_result = await _post(session, f"{BECKN_BAP_URL}/select", select_body)
        ack_status = select_result.get("ack", "UNKNOWN")
        messages.append(
            f"[beckn-bap-client/select] ACK={ack_status} "
            f"bpp={selected.get('bpp_id')} provider={selected.get('provider_name')}"
        )

        qty = beckn_intent.get("quantity", "?")
        summary = (
            f"Order initiated — {selected.get('provider_name')} | "
            f"{selected.get('item_name')} × {qty} | "
            f"₹{selected.get('price_value')} {selected.get('price_currency')} | "
            f"txn={transaction_id}"
        )
        messages.append(f"[orchestrator] {summary}")

        return {
            "transaction_id":  transaction_id,
            "offerings":       offerings,
            "selected":        selected,
            "messages":        messages,
            "status":          "live",
            "_persist": {
                "request_id":       request_id,
                "beckn_intent_id":  beckn_intent_id,
                "query_id":         query_id,
                "offering_ids_map": offering_ids_map,
                "score_ids_map":    score_ids_map,
            },
        }


async def run_pipeline(query: str) -> dict:
    """Execute the 4-step Step Functions state machine.

    Returns a dict with keys:
      parse_result, discover_result, score_result, select_result, messages
    """
    messages: list[str] = []

    async with aiohttp.ClientSession(
        headers={"Content-Type": "application/json"}
    ) as session:

        # ── Persist: create request record ────────────────────────────────────
        request_id = ""
        nr = await _persist(session, "/normalize/request", {
            "raw_input_text": query,
            "channel": "web",
        })
        request_id = nr.get("request_id", "")
        if request_id:
            await _persist_audit(
                session, "normalize", "request_created",
                reasoning_payload={"raw_query": query},
                request_id=request_id,
            )

        # ── Step 1: Intention Parser Lambda ──────────────────────────────────
        logger.info("Step 1 — Intention Parser")
        await _persist_status(session, request_id, "parsing")
        parse_result = await _post(
            session, f"{INTENTION_PARSER_URL}/parse", {"query": query}
        )
        messages.append(
            f"[intention-parser] intent={parse_result.get('intent')} "
            f"confidence={parse_result.get('confidence')} "
            f"routed_to={parse_result.get('routed_to')}"
        )

        if parse_result.get("intent") != "procurement":
            await _persist_status(session, request_id, "cancelled")
            return {
                "error": f"Query not recognised as procurement: {query!r}",
                "messages": messages,
                "parse_result": parse_result,
            }

        beckn_intent = parse_result.get("beckn_intent")
        if not beckn_intent:
            await _persist_status(session, request_id, "cancelled")
            return {
                "error": "Intent parser returned no beckn_intent",
                "messages": messages,
                "parse_result": parse_result,
            }

        # ── Persist: normalize intent ─────────────────────────────────────────
        beckn_intent_id = ""
        if request_id:
            ir = await _persist(session, "/normalize/intent", {
                "request_id":    request_id,
                "intent_class":  parse_result.get("intent", "procurement"),
                "confidence":    float(parse_result.get("confidence", 1.0)),
                "model_version": parse_result.get("model_version", "1.0"),
                "beckn_intent":  beckn_intent,
            })
            beckn_intent_id = ir.get("beckn_intent_id", "")
            if beckn_intent_id:
                await _persist_audit(
                    session, "normalize", "intent_persisted",
                    reasoning_payload={
                        "beckn_intent_id": beckn_intent_id,
                        "intent_class": parse_result.get("intent"),
                        "confidence": parse_result.get("confidence"),
                        "model_version": parse_result.get("model_version"),
                    },
                    request_id=request_id,
                )
            await _persist_status(session, request_id, "discovering")

        # ── Step 2: Beckn BAP Client Lambda (discover) ───────────────────────
        logger.info("Step 2 — Beckn BAP Client /discover")
        discover_result = await _post(
            session, f"{BECKN_BAP_URL}/discover", beckn_intent
        )
        transaction_id = discover_result.get("transaction_id", "")
        offerings = discover_result.get("offerings", [])
        messages.append(
            f"[beckn-bap-client] txn={transaction_id} "
            f"found {len(offerings)} offering(s)"
        )

        # ── Persist: discovery ────────────────────────────────────────────────
        query_id = ""
        offering_ids_map: dict[str, str] = {}
        if beckn_intent_id and offerings:
            dr = await _persist(session, "/normalize/discovery", {
                "beckn_intent_id": beckn_intent_id,
                "network_id": discover_result.get("network_id", "beckn-default"),
                "offerings": offerings,
            })
            query_id = dr.get("query_id", "")
            offering_ids_map = {
                o["item_id"]: o["offering_id"]
                for o in dr.get("offering_ids", [])
            }
            if query_id:
                await _persist_audit(
                    session, "discover", f"discovery_completed: {len(offerings)} offerings",
                    reasoning_payload={
                        "query_id": query_id,
                        "transaction_id": transaction_id,
                        "offering_count": len(offerings),
                    },
                    request_id=request_id,
                )
            await _persist_status(session, request_id, "scoring")

        if not offerings:
            return {
                "transaction_id": transaction_id,
                "offerings": [],
                "selected": None,
                "messages": messages,
                "parse_result": parse_result,
                "discover_result": discover_result,
            }

        # ── Step 3: Comparative & Scoring Lambda ─────────────────────────────
        logger.info("Step 3 — Comparative Scoring /score")
        score_result = await _post(
            session, f"{COMPARATIVE_SCORING_URL}/score", {"offerings": offerings}
        )
        selected = score_result.get("selected")
        if selected:
            messages.append(
                f"[comparative-scoring] selected {selected.get('provider_name')!r} "
                f"₹{selected.get('price_value')} (cheapest of {len(offerings)})"
            )
        else:
            messages.append("[comparative-scoring] no offering selected")

        # ── Persist: scoring ──────────────────────────────────────────────────
        score_ids_map: dict[str, str] = {}
        if query_id and offering_ids_map:
            scoring_data = _build_scoring(
                offerings,
                selected.get("item_id") if selected else None,
            )
            scores_payload = []
            for rank_item in scoring_data.get("ranking", []):
                item_id = rank_item["item_id"]
                offering_id = offering_ids_map.get(item_id)
                if not offering_id:
                    continue
                price_val = next(
                    (o["price_value"] for o in offerings if o["item_id"] == item_id),
                    "0",
                )
                scores_payload.append({
                    "offering_id":     offering_id,
                    "rank":            rank_item["rank"],
                    "composite_score": rank_item["composite_score"],
                    "price_value":     price_val,
                })
            sr = await _persist(session, "/normalize/scoring", {
                "query_id": query_id,
                "scores":   scores_payload,
            })
            score_ids_map = {
                s["offering_id"]: s["score_id"]
                for s in sr.get("score_ids", [])
            }
            await _persist_audit(
                session, "score", f"scored {len(scores_payload)} offerings",
                reasoning_payload={
                    "recommended_item_id": selected.get("item_id") if selected else None,
                    "recommended_provider": (selected or {}).get("provider_name"),
                    "score_count": len(scores_payload),
                },
                request_id=request_id,
            )
            await _persist_status(session, request_id, "negotiating")

        if not selected:
            return {
                "transaction_id": transaction_id,
                "offerings": offerings,
                "selected": None,
                "messages": messages,
                "parse_result": parse_result,
                "discover_result": discover_result,
                "score_result": score_result,
            }

        # ── Step 4: Beckn BAP Client Lambda (select) ─────────────────────────
        logger.info("Step 4 — Beckn BAP Client /select")
        select_body = {
            "transaction_id": transaction_id,
            "bpp_id":         selected.get("bpp_id", ""),
            "bpp_uri":        selected.get("bpp_uri", ""),
            "item_id":        selected.get("item_id", ""),
            "item_name":      selected.get("item_name", ""),
            "provider_id":    selected.get("provider_id", ""),
            "price_value":    selected.get("price_value", "0"),
            "price_currency": selected.get("price_currency", "INR"),
            "quantity":       beckn_intent.get("quantity", 1),
        }
        select_result = await _post(session, f"{BECKN_BAP_URL}/select", select_body)
        ack_status = select_result.get("ack", "UNKNOWN")
        messages.append(
            f"[beckn-bap-client/select] ACK={ack_status} "
            f"bpp={selected.get('bpp_id')} provider={selected.get('provider_name')}"
        )

        # ── Final summary ─────────────────────────────────────────────────────
        qty = beckn_intent.get("quantity", "?")
        summary = (
            f"Order initiated — {selected.get('provider_name')} | "
            f"{selected.get('item_name')} × {qty} | "
            f"₹{selected.get('price_value')} {selected.get('price_currency')} | "
            f"txn={transaction_id}"
        )
        messages.append(f"[orchestrator] {summary}")

        return {
            "transaction_id":  transaction_id,
            "offerings":       offerings,
            "selected":        selected,
            "messages":        messages,
            "parse_result":    parse_result,
            "discover_result": discover_result,
            "score_result":    score_result,
            "select_result":   select_result,
            "_persist": {
                "request_id":       request_id,
                "beckn_intent_id":  beckn_intent_id,
                "query_id":         query_id,
                "offering_ids_map": offering_ids_map,
                "score_ids_map":    score_ids_map,
            },
        }


# ── HTTP handlers ─────────────────────────────────────────────────────────────


async def health(request: web.Request) -> web.Response:
    return web.json_response({
        "status": "ok",
        "service": "orchestrator",
        "upstream": {
            "intention_parser":    INTENTION_PARSER_URL,
            "beckn_bap_client":    BECKN_BAP_URL,
            "comparative_scoring": COMPARATIVE_SCORING_URL,
        },
    })


async def parse(request: web.Request) -> web.Response:
    """POST /parse — proxy NL query to intention-parser.

    Forwards the request body verbatim to INTENTION_PARSER_URL/parse and
    returns the response. This lets the frontend use BAP_URL=http://localhost:8000
    for both /parse and /compare in microservices mode.
    """
    try:
        body = await request.json()
    except json.JSONDecodeError:
        raise web.HTTPBadRequest(reason="Invalid JSON")

    try:
        async with aiohttp.ClientSession(
            headers={"Content-Type": "application/json"}
        ) as session:
            result = await _post(session, f"{INTENTION_PARSER_URL}/parse", body)
        return web.json_response(result)
    except aiohttp.ClientError as exc:
        logger.error("[parse proxy] Intention parser unreachable: %s", exc)
        raise web.HTTPBadGateway(reason="The AI service is temporarily unavailable. Please try again.")
    except Exception as exc:
        logger.error("[parse proxy] Error: %s", exc)
        raise web.HTTPInternalServerError(reason="Unable to process your request. Please try again.")


async def compare(request: web.Request) -> web.Response:
    """POST /compare — discover + score, store session, return offerings + scoring.

    Equivalent to Bap-1's POST /compare. Runs Steps 2→3 (discover + rank) but
    does NOT run Step 4 (select) — that happens in /commit after the user picks.

    Body:     BecknIntent fields (item, quantity, location_coordinates, …)
    Response: { transaction_id, offerings[], recommended_item_id,
                scoring, reasoning_steps, messages, status }
    """
    try:
        body = await request.json()
    except json.JSONDecodeError:
        raise web.HTTPBadRequest(reason="Invalid JSON")

    # raw_query is the user's original NL prompt from /parse — preferred for the
    # raw_input_text audit column. Pop it before forwarding to /discover so it
    # doesn't leak into the Beckn payload.
    raw_query = (body.pop("raw_query", None) or "").strip()
    # Authenticated Keycloak identity injected by the frontend proxy. Popped
    # before the body is forwarded to /discover so it never leaks into the
    # Beckn payload nor the stored BecknIntent.
    actor = body.pop("actor", None)

    if not body.get("item"):
        raise web.HTTPBadRequest(reason="item is required in BecknIntent body")

    # Declared outside the try so the except can mark the row as cancelled
    # when discover/score fails mid-flow (avoids orphan draft rows).
    request_id = ""
    requester_id: str | None = None

    try:
        async with aiohttp.ClientSession(
            headers={"Content-Type": "application/json"}
        ) as session:

            # ── Persist request + intent BEFORE external calls ───────────────
            # The row appears in procurement_requests immediately so the
            # frontend wait shows a visible row transitioning through
            # discovering → scoring → negotiating in real time, instead of
            # all states flashing past in <50ms at the very end.
            beckn_intent_id = ""
            nr = await _persist(session, "/normalize/request", {
                "raw_input_text": raw_query or body.get("item", "compare-request"),
                "channel": "web",
                "actor": actor,
            })
            request_id = nr.get("request_id", "")
            requester_id = nr.get("requester_id")
            approval_threshold = float(nr.get("approval_threshold") or 0.0)
            if request_id:
                await _persist_audit(
                    session, "normalize", "request_created",
                    reasoning_payload={"raw_query": raw_query, "item": body.get("item")},
                    request_id=request_id,
                )
                ir = await _persist(session, "/normalize/intent", {
                    "request_id":    request_id,
                    "intent_class":  "procurement",
                    "confidence":    1.0,
                    "model_version": "direct",
                    "beckn_intent":  body,
                })
                beckn_intent_id = ir.get("beckn_intent_id", "")
                if beckn_intent_id:
                    await _persist_audit(
                        session, "normalize", "intent_persisted",
                        reasoning_payload={"beckn_intent_id": beckn_intent_id, "intent": body},
                        request_id=request_id,
                    )
                # Status → 'discovering' BEFORE the external call. The DB
                # now reflects the phase that's running, not the one that
                # just finished.
                await _persist_status(session, request_id, "discovering")

            # Step 2: discover
            discover_result = await _post(session, f"{BECKN_BAP_URL}/discover", body)
            transaction_id = discover_result.get("transaction_id") or str(uuid4())
            offerings: list[dict] = discover_result.get("offerings", [])

            if not offerings:
                # Honest "no suppliers found" — a valid empty result, NOT an
                # error and never mock. The frontend shows an empty state.
                if request_id:
                    await _persist_audit(
                        session, "discover", "no_offerings_found",
                        reasoning_payload={"item": body.get("item")},
                        request_id=request_id,
                    )
                    await _persist_status(session, request_id, "cancelled")
                return web.json_response({
                    "transaction_id":      transaction_id,
                    "request_id":          request_id,
                    "offerings":           [],
                    "recommended_item_id": None,
                    "scoring":             {"recommended_item_id": None, "criteria": [], "ranking": []},
                    "reasoning_steps":     [],
                    "messages":            ["No offerings returned from the supplier network"],
                    "status":              "live",
                })

            # ── Persist discovery, then advance status to 'scoring' BEFORE
            # the external score call ────────────────────────────────────────
            query_id = ""
            offering_ids_map: dict[str, str] = {}
            if beckn_intent_id and offerings:
                dr = await _persist(session, "/normalize/discovery", {
                    "beckn_intent_id": beckn_intent_id,
                    "network_id": "beckn-default",
                    "offerings": offerings,
                })
                query_id = dr.get("query_id", "")
                offering_ids_map = {
                    o["item_id"]: o["offering_id"]
                    for o in dr.get("offering_ids", [])
                }
                if query_id:
                    await _persist_audit(
                        session, "discover", f"discovery_completed: {len(offerings)} offerings",
                        reasoning_payload={
                            "query_id": query_id,
                            "offering_count": len(offerings),
                            "providers": [o.get("provider_name") for o in offerings],
                        },
                        request_id=request_id,
                    )
            if request_id:
                await _persist_status(session, request_id, "scoring")

            # Step 3: score (rank-only, no select)
            score_result = await _post(
                session, f"{COMPARATIVE_SCORING_URL}/score", {"offerings": offerings}
            )
            selected: dict | None = score_result.get("selected")
            # The comparative-scoring adapter reports which engine scored:
            #   {"engine":"ml", model_version, pipeline, ranking[]}  (RankNet)
            #   {"engine":"heuristic_min_price"}                      (fallback)
            adapter_scoring: dict = score_result.get("scoring") or {}

            recommended_item_id = selected["item_id"] if selected else None
            engine = adapter_scoring.get("engine")
            used_ml = engine == "ml" and bool(adapter_scoring.get("ranking"))
            model_version = adapter_scoring.get("model_version") or "unknown"

            if selected and used_ml:
                select_msg = (
                    f"[rank_and_select] ML model {model_version} recommended "
                    f"{selected['provider_name']!r} ₹{selected['price_value']}"
                )
            elif selected:
                select_msg = (
                    f"[rank_and_select] (fallback heurístico) recommended "
                    f"{selected['provider_name']!r} ₹{selected['price_value']}"
                )
            else:
                select_msg = "[rank_and_select] no offering selected"
            messages = [
                f"[discover] txn={transaction_id} found {len(offerings)} offering(s)",
                select_msg,
            ]

            reasoning_steps = [
                {
                    "node": "discover",
                    "role": "act",
                    "summary": f"Discovered {len(offerings)} offering(s) on the Beckn network",
                    "details": {
                        "transaction_id": transaction_id,
                        "offering_count": len(offerings),
                        "providers": [o["provider_name"] for o in offerings],
                    },
                    "timestamp": _now_iso(),
                },
            ]
            if selected and used_ml:
                # Build the ML ranking presentation + reason step from RankNet scores.
                scoring_block = _build_ml_scoring(offerings, adapter_scoring, recommended_item_id)
                ranked_provider = {o["item_id"]: o["provider_name"] for o in offerings}
                top = scoring_block["ranking"][0] if scoring_block["ranking"] else {}
                reasoning_steps.append({
                    "node": "rank_and_select",
                    "role": "reason",
                    "summary": (
                        f"RankNet ({model_version}) ranked {len(offerings)} offering(s); "
                        f"recommended {selected['provider_name']}"
                    ),
                    "details": {
                        "strategy": "ml_ranknet",
                        "model_version": model_version,
                        "pipeline": adapter_scoring.get("pipeline"),
                        "recommended_item_id": selected["item_id"],
                        "recommended_provider": selected["provider_name"],
                        "recommended_price": selected["price_value"],
                        "ml_ranking": [
                            {
                                "rank": r["rank"],
                                "provider": ranked_provider.get(r["item_id"], r["item_id"]),
                                "ml_score": r["composite_score"],
                            }
                            for r in scoring_block["ranking"]
                        ],
                        "offering_count": len(offerings),
                    },
                    "timestamp": _now_iso(),
                })
            elif selected:
                # Genuine fallback path (ML unavailable) — price-only narrative.
                scoring_block = _build_scoring(offerings, recommended_item_id)
                prices = [float(o["price_value"]) for o in offerings]
                prices_sorted = sorted(prices)
                savings = f"{prices_sorted[1] - prices_sorted[0]:.2f}" if len(prices_sorted) > 1 else None
                reasoning_steps.append({
                    "node": "rank_and_select",
                    "role": "reason",
                    "summary": f"Recommended {selected['provider_name']} — cheapest of {len(offerings)} (fallback)",
                    "details": {
                        "strategy": "price_only_fallback",
                        "recommended_item_id": selected["item_id"],
                        "recommended_provider": selected["provider_name"],
                        "recommended_price": selected["price_value"],
                        "savings_vs_next_cheapest": savings,
                        "offering_count": len(offerings),
                    },
                    "timestamp": _now_iso(),
                })
            else:
                scoring_block = _build_scoring(offerings, recommended_item_id)
                reasoning_steps.append({
                    "node": "rank_and_select",
                    "role": "reason",
                    "summary": "No offerings to rank",
                    "details": {},
                    "timestamp": _now_iso(),
                })

            # ── Persist scoring + final status (depends on score result) ────
            score_ids_map: dict[str, str] = {}
            if query_id and offering_ids_map:
                local_scoring = _build_scoring(offerings, recommended_item_id)
                scores_payload = []
                for rank_item in local_scoring.get("ranking", []):
                    item_id = rank_item["item_id"]
                    offering_id = offering_ids_map.get(item_id)
                    if not offering_id:
                        continue
                    price_val = next(
                        (o["price_value"] for o in offerings if o["item_id"] == item_id),
                        "0",
                    )
                    scores_payload.append({
                        "offering_id":     offering_id,
                        "rank":            rank_item["rank"],
                        "composite_score": rank_item["composite_score"],
                        "price_value":     price_val,
                    })
                sr = await _persist(session, "/normalize/scoring", {
                    "query_id": query_id,
                    "scores":   scores_payload,
                })
                score_ids_map = {
                    s["offering_id"]: s["score_id"]
                    for s in sr.get("score_ids", [])
                }
                await _persist_audit(
                    session, "score", f"scored {len(scores_payload)} offerings",
                    reasoning_payload={
                        "recommended_item_id": recommended_item_id,
                        "recommended_provider": (selected or {}).get("provider_name"),
                        "score_count": len(scores_payload),
                    },
                    request_id=request_id,
                )
                # Persist the supplier-declared category of the chosen offering
                # (Beckn catalog) onto the request, alongside the status bump.
                recommended_category = (
                    (selected or {}).get("category")
                    or (offerings[0].get("category") if offerings else None)
                )
                await _persist_status(
                    session, request_id, "negotiating", category=recommended_category
                )

            _session_put(transaction_id, {
                "transaction_id":    transaction_id,
                "offerings":         offerings,
                "selected":          selected,
                "intent":            body,
                "request_id":        request_id,
                "requester_id":      requester_id,
                "approval_threshold": approval_threshold,
                "beckn_intent_id":   beckn_intent_id,
                "query_id":          query_id,
                "offering_ids_map":  offering_ids_map,
                "score_ids_map":     score_ids_map,
            })

        return web.json_response({
            "transaction_id":      transaction_id,
            "request_id":          request_id,
            "offerings":           offerings,
            "recommended_item_id": recommended_item_id,
            "scoring":             scoring_block,
            "reasoning_steps":     reasoning_steps,
            "messages":            messages,
            "status":              "live",
        })

    except Exception as exc:
        # If a row was already created but discover/score failed, mark it
        # cancelled so it doesn't linger in draft/discovering/scoring forever.
        # The original session was closed when the async-with exited on the
        # exception, so we open a short-lived one just for the cleanup PATCH.
        if request_id:
            try:
                async with aiohttp.ClientSession(
                    headers={"Content-Type": "application/json"}
                ) as cleanup_session:
                    await _persist_status(cleanup_session, request_id, "cancelled")
            except Exception:
                pass
        logger.error("compare live path failed (%s) — returning error (no mock)", exc)
        return web.json_response(
            {"error": "Supplier network unavailable",
             "detail": "Could not reach the Beckn supplier network. Please try again."},
            status=502,
        )


def _mock_compare_response() -> web.Response:
    """Fallback compare response using the local catalog (microservices offline)."""
    txn_id = str(uuid4())
    offerings = _local_catalog_as_offerings()
    recommended = min(offerings, key=lambda o: float(o["price_value"]))
    recommended_item_id = recommended["item_id"]

    _session_put(txn_id, {
        "transaction_id": txn_id,
        "offerings": offerings,
        "selected": recommended,
        "intent": {},
    })

    return web.json_response({
        "transaction_id":      txn_id,
        "offerings":           offerings,
        "recommended_item_id": recommended_item_id,
        "scoring":             _build_scoring(offerings, recommended_item_id),
        "reasoning_steps":     [],
        "messages":            [f"[mock] {len(offerings)} offerings from local catalog"],
        "status":              "mock",
    })


async def commit(request: web.Request) -> web.Response:
    """POST /commit — select + init + confirm for a previously compared transaction.

    Loads session by transaction_id, overrides selected with chosen_item_id,
    then runs the Beckn transactional flow: /select → /init → /confirm.

    Body:     { transaction_id, chosen_item_id }
    Response: { transaction_id, order_id, order_state, payment_terms,
                fulfillment_eta, bpp_id, bpp_uri, contract_id,
                reasoning_steps, messages, status }
    """
    try:
        body = await request.json()
    except json.JSONDecodeError:
        raise web.HTTPBadRequest(reason="Invalid JSON")

    actor = body.pop("actor", {})
    actor_role = (actor.get("role") or "requester").lower()

    txn_id = body.get("transaction_id")
    chosen_item_id = body.get("chosen_item_id")
    if not txn_id or not chosen_item_id:
        raise web.HTTPBadRequest(reason="transaction_id and chosen_item_id are required")

    state = _session_get(txn_id)
    if state is None:
        raise web.HTTPNotFound(reason=f"Unknown transaction_id: {txn_id}")

    offerings: list[dict] = state.get("offerings", [])
    chosen = next((o for o in offerings if o["item_id"] == chosen_item_id), None)
    if chosen is None:
        raise web.HTTPUnprocessableEntity(
            reason=f"chosen_item_id {chosen_item_id!r} is not in the compared offerings"
        )

    bpp_id = chosen["bpp_id"]
    bpp_uri = chosen["bpp_uri"]
    quantity = state.get("intent", {}).get("quantity", 1)

    # ── RBAC operating mode gate ──────────────────────────────────────────────
    # All roles subject to threshold check: ≤ threshold → auto-confirm, > threshold → pending_approval.
    if actor_role in ("requester", "approver", "admin"):
        try:
            order_total = Decimal(str(chosen["price_value"])) * Decimal(quantity)
        except Exception:
            order_total = Decimal("0")
        threshold = Decimal(str(state.get("approval_threshold") or 0))
        if order_total > threshold:
            request_id = state.get("request_id", "")
            if request_id:
                try:
                    async with aiohttp.ClientSession(
                        headers={"Content-Type": "application/json"}
                    ) as _s:
                        await _persist_status(_s, request_id, "pending_approval")
                except Exception as exc:
                    logger.warning("[commit] pending_approval status update failed: %s", exc)
            _pending_approvals[request_id] = {
                "request_id":      request_id,
                "transaction_id":  txn_id,
                "chosen_item_id":  chosen_item_id,
                "actor":           actor,
                "amount_total":    float(order_total),
                "item_description": state.get("intent", {}).get("item", ""),
                "provider_name":   chosen.get("provider_name", ""),
                "created_at":      _now_iso(),
            }
            return web.json_response({
                "status":      "pending_approval",
                "request_id":  request_id,
                "amount_total": float(order_total),
            }, status=202)

    # ── ERP budget gate (M3.1) ────────────────────────────────────────────────
    budget_hold_id: str | None = None
    if ERP_BUDGET_CHECK_ENABLED:
        intent = state.get("intent") or {}
        try:
            unit_price = Decimal(str(chosen["price_value"]))
            requested = unit_price * Decimal(quantity)
        except Exception:
            requested = Decimal("0")
        bc_req = BudgetCheckRequest(
            transaction_id=txn_id,
            cost_center=intent.get("cost_center") or ERP_DEFAULT_COST_CENTER,
            requested_amount=requested,
            currency=chosen.get("price_currency", "INR"),
            category=intent.get("category", "uncategorized"),
            requester_id=request.headers.get("X-Requester-Id", "anonymous"),
        )
        try:
            bc = await _get_erp_client().budget_check(bc_req)
        except Exception as exc:
            logger.error("[budget-gate] required but adapter failed txn=%s err=%s", txn_id, exc)
            return web.json_response(
                {"transaction_id": txn_id, "status": "error",
                 "reason": "erp_unavailable", "detail": str(exc)},
                status=503,
            )
        if not bc.allowed:
            logger.info("[budget-gate] DENIED txn=%s reasons=%s", txn_id, bc.reasons)
            return web.json_response(
                {"transaction_id": txn_id, "status": "rejected",
                 "reason": "budget", "detail": bc.reasons},
                status=409,
            )
        budget_hold_id = bc.hold_id
        if bc.fallback:
            logger.warning("[budget-gate] fail-open txn=%s reasons=%s", txn_id, bc.reasons)
        else:
            logger.info("[budget-gate] approved txn=%s hold=%s", txn_id, budget_hold_id)


    contract_id = str(uuid4())
    items = [{
        "id":             chosen["item_id"],
        "quantity":       quantity,
        "name":           chosen["item_name"],
        "price_value":    chosen["price_value"],
        "price_currency": chosen.get("price_currency", "INR"),
    }]
    messages: list[str] = []
    select_ack = "UNKNOWN"
    payment_terms: dict = {}
    order_id = ""
    order_state = "CREATED"

    try:
        async with aiohttp.ClientSession(
            headers={"Content-Type": "application/json"}
        ) as session:

            # Step 4a: /select
            select_body = {
                "transaction_id": txn_id,
                "bpp_id":         bpp_id,
                "bpp_uri":        bpp_uri,
                "item_id":        chosen["item_id"],
                "item_name":      chosen["item_name"],
                "provider_id":    chosen.get("provider_id", ""),
                "price_value":    chosen["price_value"],
                "price_currency": chosen.get("price_currency", "INR"),
                "quantity":       quantity,
            }
            select_resp = await _post(session, f"{BECKN_BAP_URL}/select", select_body)
            select_ack = select_resp.get("ack", "UNKNOWN")
            messages.append(f"[send_select] ACK={select_ack}")

            # Step 4b: /init
            intent: dict = state.get("intent") or {}
            init_body = {
                "transaction_id": txn_id,
                "contract_id":    contract_id,
                "bpp_id":         bpp_id,
                "bpp_uri":        bpp_uri,
                "items":          items,
                "billing":        _build_billing_info(),
                "fulfillment":    _build_fulfillment_info(intent),
            }
            init_resp = await _post(session, f"{BECKN_BAP_URL}/init", init_body)
            payment_terms = init_resp.get("payment_terms") or {
                "type":         "ON_FULFILLMENT",
                "collected_by": "BPP",
                "currency":     chosen.get("price_currency", "INR"),
                "status":       "NOT-PAID",
            }
            messages.append(f"[send_init] payment_terms set, ack={init_resp.get('ack')}")

            # Step 4c: /confirm
            confirm_body = {
                "transaction_id": txn_id,
                "contract_id":    contract_id,
                "bpp_id":         bpp_id,
                "bpp_uri":        bpp_uri,
                "items":          items,
                "payment_terms":  payment_terms,
            }
            confirm_resp = await _post(session, f"{BECKN_BAP_URL}/confirm", confirm_body)
            order_id = confirm_resp.get("order_id") or f"order-{uuid4().hex[:8]}"
            order_state = confirm_resp.get("order_state") or "CREATED"
            messages.append(f"[send_confirm] order_id={order_id} state={order_state}")

            # ── Persist: order ────────────────────────────────────────────────
            state_score_ids_map: dict[str, str] = state.get("score_ids_map", {})
            state_offering_ids_map: dict[str, str] = state.get("offering_ids_map", {})
            chosen_offering_id = state_offering_ids_map.get(chosen_item_id, "")
            chosen_score_id = state_score_ids_map.get(chosen_offering_id, "")
            committed_request_id = state.get("request_id", "")
            # Absolute delivery ETA = confirm time + the chosen offering's
            # fulfillment_hours. Persisted so the order page can show a real ETA
            # later (the live commit response leaves fulfillment_eta None).
            order_fulfillment_eta: str | None = None
            chosen_hours = chosen.get("fulfillment_hours")
            if chosen_hours is not None:
                try:
                    order_fulfillment_eta = (
                        datetime.now(timezone.utc) + timedelta(hours=int(chosen_hours))
                    ).isoformat()
                except (TypeError, ValueError):
                    order_fulfillment_eta = None
            if chosen_score_id:
                await _persist(session, "/normalize/order", {
                    "score_id":          chosen_score_id,
                    "bpp_uri":           bpp_uri,
                    "item_id":           chosen["item_id"],
                    "quantity":          quantity,
                    "agreed_price":      float(chosen.get("price_value", "0")),
                    "beckn_confirm_ref": order_id,
                    "delivery_terms":    "Standard delivery",
                    "currency":          chosen.get("price_currency", "INR"),
                    "fulfillment_eta":   order_fulfillment_eta,
                    "requester_id":      state.get("requester_id"),
                })
                await _persist_audit(
                    session, "confirm", f"order_confirmed: {order_id}",
                    reasoning_payload={
                        "order_id":      order_id,
                        "contract_id":   contract_id,
                        "bpp_id":        bpp_id,
                        "provider_name": chosen.get("provider_name"),
                        "item_id":       chosen["item_id"],
                        "quantity":      quantity,
                        "agreed_price":  float(chosen.get("price_value", "0")),
                        "currency":      chosen.get("price_currency", "INR"),
                    },
                    request_id=committed_request_id,
                )
                await _persist_status(
                    session, committed_request_id, "confirmed"
                )

        reasoning_steps = [
            {
                "node": "send_select",
                "role": "act",
                "summary": f"/select sent to {chosen['provider_name']} — ACK={select_ack}",
                "details": {
                    "ack_status": select_ack,
                    "bpp_id": bpp_id,
                    "provider_id": chosen.get("provider_id", ""),
                    "contract_id": contract_id,
                },
                "timestamp": _now_iso(),
            },
            {
                "node": "send_init",
                "role": "act",
                "summary": f"/init confirmed — payment {payment_terms.get('type')}/{payment_terms.get('collected_by')}",
                "details": {
                    "contract_id": contract_id,
                    "payment_type": payment_terms.get("type"),
                    "collected_by": payment_terms.get("collected_by"),
                    "currency": payment_terms.get("currency"),
                },
                "timestamp": _now_iso(),
            },
            {
                "node": "send_confirm",
                "role": "act",
                "summary": f"Order confirmed — {order_id} ({order_state})",
                "details": {
                    "order_id": order_id,
                    "order_state": order_state,
                },
                "timestamp": _now_iso(),
            },
            {
                "node": "present_results",
                "role": "observe",
                "summary": (
                    f"Order CONFIRMED — {chosen['item_name']} × {quantity} | "
                    f"₹{chosen['price_value']} {chosen.get('price_currency', 'INR')} | "
                    f"order={order_id} state={order_state}"
                ),
                "details": {},
                "timestamp": _now_iso(),
            },
        ]

        _session_put(txn_id, {
            **state,
            "order_id":         order_id,
            "order_state":      order_state,
            "payment_terms":    payment_terms,
            "bpp_id":           bpp_id,
            "bpp_uri":          bpp_uri,
            "items":            items,
            "contract_id":      contract_id,
            "budget_hold_id":   budget_hold_id,
            "score_ids_map":    state.get("score_ids_map", {}),
            "offering_ids_map": state.get("offering_ids_map", {}),
        })

        # ── ERP outbox enqueue (M3.2) — fire-and-forget ──────────────────────
        if ERP_SYNC_ENABLED and order_id and not state.get("error"):
            try:
                po_payload = build_normalized_po(
                    state={**state, "transaction_id": txn_id},
                    chosen=chosen,
                    intent=state.get("intent") or {},
                    order_id=order_id,
                    contract_id=contract_id,
                    payment_terms=payment_terms,
                    fulfillment_eta=None,
                    budget_hold_id=budget_hold_id,
                    buyer=_build_buyer_dict(),
                )
                # Propagate the X-Mock-Scenario header into payload metadata so
                # the outbox worker (which runs out-of-band) sees it.
                mock_scenario = request.headers.get("X-Mock-Scenario")
                if mock_scenario:
                    po_payload["metadata"] = {
                        **po_payload.get("metadata", {}),
                        "mock_scenario": mock_scenario,
                    }
                asyncio.create_task(_get_erp_client().enqueue_sync(po_payload))
            except Exception as exc:
                logger.warning("[erp-sync] enqueue build failed txn=%s err=%s", txn_id, exc)

        return web.json_response({
            "transaction_id": txn_id,
            "order_id":       order_id,
            "order_state":    order_state,
            "payment_terms":  payment_terms,
            "fulfillment_eta": None,
            "bpp_id":         bpp_id,
            "bpp_uri":        bpp_uri,
            "contract_id":    contract_id,
            "reasoning_steps": reasoning_steps,
            "messages":       messages,
            "status":         "live",
        })

    except (web.HTTPBadRequest, web.HTTPNotFound, web.HTTPUnprocessableEntity):
        raise  # propagate validation errors as-is
    except Exception as exc:
        logger.warning("commit live path failed (%s) — returning mock", exc)
        return _mock_commit_response(txn_id, chosen, state, contract_id)


def _mock_commit_response(
    txn_id: str,
    chosen: dict,
    state: dict,
    contract_id: str,
) -> web.Response:
    """Synthesize a commit result when the Beckn stack is offline."""
    order_id = f"mock-order-{uuid4().hex[:8]}"
    payment_terms = {
        "type":         "ON_FULFILLMENT",
        "collected_by": "BPP",
        "currency":     chosen.get("price_currency", "INR"),
        "status":       "NOT-PAID",
    }
    _session_put(txn_id, {
        **state,
        "order_id":      order_id,
        "order_state":   "CREATED",
        "payment_terms": payment_terms,
        "bpp_id":        chosen["bpp_id"],
        "bpp_uri":       chosen["bpp_uri"],
        "items":         [{
            "id":             chosen["item_id"],
            "quantity":       state.get("intent", {}).get("quantity", 1),
            "name":           chosen["item_name"],
            "price_value":    chosen["price_value"],
            "price_currency": chosen.get("price_currency", "INR"),
        }],
        "contract_id": contract_id,
    })
    return web.json_response({
        "transaction_id": txn_id,
        "order_id":       order_id,
        "order_state":    "CREATED",
        "payment_terms":  payment_terms,
        "fulfillment_eta": None,
        "bpp_id":         chosen["bpp_id"],
        "bpp_uri":        chosen["bpp_uri"],
        "contract_id":    contract_id,
        "reasoning_steps": [],
        "messages":       ["[mock] Beckn stack offline — mock order generated"],
        "status":         "mock",
    })


async def order_status(request: web.Request) -> web.Response:
    """GET /status/{txn_id}/{order_id} — poll order lifecycle.

    Recovers bpp_id/bpp_uri and items from session. Accepts optional
    bpp_id/bpp_uri query params as fallback (same as Bap-1).

    Always returns 200 — the frontend's StatusPoller must not stop on failure.
    """
    txn_id = request.match_info["txn_id"]
    order_id = request.match_info["order_id"]

    state = _session_get(txn_id)
    bpp_id = (state or {}).get("bpp_id") or request.query.get("bpp_id")
    bpp_uri = (state or {}).get("bpp_uri") or request.query.get("bpp_uri")
    stored_items = (state or {}).get("items", [])
    last_state = (state or {}).get("order_state", "CREATED")

    erp_event = _erp_state_for(txn_id)

    if not bpp_id or not bpp_uri:
        return web.json_response({
            "transaction_id": txn_id,
            "order_id":       order_id,
            "state":          last_state,
            "erp_state":      _erp_state_block(erp_event),
            "fulfillment_eta": None,
            "tracking_url":   None,
            "observed_at":    _now_iso(),
            "status":         "mock",
        })

    try:
        async with aiohttp.ClientSession(
            headers={"Content-Type": "application/json"}
        ) as session:
            status_body = {
                "transaction_id": txn_id,
                "order_id":       order_id,
                "bpp_id":         bpp_id,
                "bpp_uri":        bpp_uri,
                "items":          stored_items,
            }
            result = await _post(session, f"{BECKN_BAP_URL}/status", status_body)

            # Persist po lifecycle and audit only when the BPP-reported state
            # differs from what we last saw (avoid spamming on every poll).
            new_state = result.get("state", last_state)
            if new_state and new_state != last_state:
                po_state = _beckn_state_to_po_status(new_state)
                if po_state:
                    await _persist(session, "/normalize/po_status", {
                        "beckn_confirm_ref": order_id,
                        "state":             po_state,
                    })
                    await _persist_audit(
                        session, "confirm",
                        f"order state {last_state} → {new_state}",
                        reasoning_payload={
                            "transaction_id": txn_id,
                            "order_id":       order_id,
                            "previous_state": last_state,
                            "new_state":      new_state,
                            "po_status":      po_state,
                        },
                        request_id=(state or {}).get("request_id"),
                    )
                # Update session so subsequent polls don't re-fire the audit.
                if state is not None:
                    state["order_state"] = new_state

        beckn_state = result.get("state", last_state)
        if erp_event and erp_event.get("state") and erp_event["state"] != beckn_state:
            logger.info("[status] STATE_DISCREPANCY txn=%s beckn=%s erp=%s",
                        txn_id, beckn_state, erp_event["state"])

        return web.json_response({
            "transaction_id": txn_id,
            "order_id":       order_id,
            "state":          beckn_state,                  # Beckn remains canonical
            "erp_state":      _erp_state_block(erp_event),  # informational
            "fulfillment_eta": result.get("fulfillment_eta"),
            "tracking_url":   result.get("tracking_url"),
            "observed_at":    _now_iso(),
            "status":         "live",
        })

    except Exception as exc:
        logger.debug("status poll failed (%s) — returning last known state", exc)
        return web.json_response({
            "transaction_id": txn_id,
            "order_id":       order_id,
            "state":          last_state,
            "erp_state":      _erp_state_block(erp_event),
            "fulfillment_eta": None,
            "tracking_url":   None,
            "observed_at":    _now_iso(),
            "status":         "mock",
        })


def _erp_state_block(event: dict | None) -> dict | None:
    if not event:
        return None
    return {
        "state":            event.get("state"),
        "vendor":           event.get("vendor"),
        "erp_reference_id": event.get("erp_reference_id"),
        "event_ts":         event.get("event_ts"),
        "vendor_event_id":  event.get("vendor_event_id"),
    }


async def discover(request: web.Request) -> web.Response:
    """POST /discover — frontend-compatible endpoint (Steps 2→3→4 only).

    Accepts a pre-parsed BecknIntent body (same format as the confirmed intent
    from the frontend's Step 2). Skips the NL parsing step.

    This endpoint mirrors the Bap-1 monolith's POST /discover so the frontend
    only needs to change BAP_URL from port 8000 to port 8004.

    Body:    BecknIntent fields (item, quantity, location_coordinates, …)
    Returns: { transaction_id, offerings, selected, messages, status }
    """
    try:
        beckn_intent = await request.json()
    except json.JSONDecodeError:
        raise web.HTTPBadRequest(reason="Invalid JSON")

    if not beckn_intent.get("item"):
        raise web.HTTPBadRequest(reason="item is required in BecknIntent body")

    try:
        result = await run_pipeline_from_intent(beckn_intent)
    except aiohttp.ClientError as exc:
        logger.error("Service call failed: %s", exc)
        raise web.HTTPBadGateway(reason="A backend service is temporarily unavailable. Please try again.")
    except Exception as exc:
        logger.error("Pipeline error: %s", exc)
        raise web.HTTPInternalServerError(reason="An unexpected error occurred. Please try again.")

    return web.json_response(result)


async def analytics(request: web.Request) -> web.Response:
    """GET /analytics — proxy to the analytics microservice."""
    period = request.query.get("period", "90d")
    if period not in ("30d", "90d", "180d"):
        period = "90d"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{ANALYTICS_URL}/analytics",
                params={"period": period},
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                body = await resp.json()
                return web.json_response(body, status=resp.status)
    except aiohttp.ClientError as exc:
        logger.warning("Analytics service unreachable: %s", exc)
        raise web.HTTPServiceUnavailable(reason="Analytics service unavailable")


async def order_detail(request: web.Request) -> web.Response:
    """GET /order/{request_id} — proxy to data-normalizer's order read endpoint.

    Lets the frontend render an order whose browser session is gone (e.g. opened
    from the dashboard). Passes through 404 for an unknown request_id.
    """
    request_id = request.match_info["request_id"]
    if not DATA_NORMALIZER_URL:
        raise web.HTTPServiceUnavailable(reason="Persistence service not configured")
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{DATA_NORMALIZER_URL}/order/{request_id}",
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status == 404:
                    return web.json_response({"found": False}, status=404)
                body = await resp.json()
                return web.json_response(body, status=resp.status)
    except aiohttp.ClientError as exc:
        logger.warning("Data-normalizer unreachable for order %s: %s", request_id, exc)
        raise web.HTTPServiceUnavailable(reason="Persistence service unavailable")


async def run(request: web.Request) -> web.Response:
    """POST /run  { "query": "..." } — execute full procurement pipeline."""
    try:
        body = await request.json()
    except json.JSONDecodeError:
        raise web.HTTPBadRequest(reason="Invalid JSON")

    query = body.get("query", "").strip()
    if not query:
        raise web.HTTPBadRequest(reason="query is required")

    try:
        result = await run_pipeline(query)
    except aiohttp.ClientError as exc:
        logger.error("Service call failed: %s", exc)
        raise web.HTTPBadGateway(reason="A backend service is temporarily unavailable. Please try again.")
    except Exception as exc:
        logger.error("Pipeline error: %s", exc)
        raise web.HTTPInternalServerError(reason="An unexpected error occurred. Please try again.")

    return web.json_response(result)


# ── ERP status subscriber (Redis psubscribe to po.status_changed:*) ──────────

async def _erp_status_subscriber_loop(redis) -> None:
    """Long-running task — reads ERP status events off Redis and parks them
    in `_erp_state_cache` keyed by transaction_id. Best-effort: any failure
    logs and continues; never raises into the parent task."""
    pubsub = redis.pubsub()
    try:
        await pubsub.psubscribe("po.status_changed:*")
        logger.info("[erp-subscriber] psubscribed to po.status_changed:*")
        async for msg in pubsub.listen():
            if msg is None or msg.get("type") != "pmessage":
                continue
            try:
                payload = json.loads(msg["data"]) if isinstance(msg["data"], (str, bytes)) else msg["data"]
                txn_id = payload.get("transaction_id")
                if not txn_id:
                    continue
                _erp_state_cache[txn_id] = payload
                _erp_state_times[txn_id] = time.monotonic()
                logger.info("[erp-subscriber] cached state=%s txn=%s vendor=%s",
                            payload.get("state"), txn_id, payload.get("vendor"))
            except Exception as exc:
                logger.warning("[erp-subscriber] malformed message: %s", exc)
    except asyncio.CancelledError:
        logger.info("[erp-subscriber] cancelled")
        raise
    except Exception as exc:
        logger.warning("[erp-subscriber] loop failed: %s", exc)
    finally:
        try:
            await pubsub.punsubscribe("po.status_changed:*")
            await pubsub.aclose()
        except Exception:
            pass


def _erp_state_for(txn_id: str) -> dict | None:
    """Return the cached inbound state, honoring the configurable TTL."""
    payload = _erp_state_cache.get(txn_id)
    if payload is None:
        return None
    if time.monotonic() - _erp_state_times.get(txn_id, 0) > ERP_STATE_CACHE_TTL_SECS:
        _erp_state_cache.pop(txn_id, None)
        _erp_state_times.pop(txn_id, None)
        return None
    return payload


async def _on_startup_erp_subscriber(app: web.Application) -> None:
    if not REDIS_URL:
        logger.info("[erp-subscriber] REDIS_URL not set — skipping (no enrichment)")
        return
    try:
        import redis.asyncio as aioredis  # type: ignore
    except Exception as exc:
        logger.warning("[erp-subscriber] redis lib missing: %s — skipping", exc)
        return
    try:
        r = aioredis.from_url(REDIS_URL, encoding="utf-8", decode_responses=True)
        await r.ping()
    except Exception as exc:
        logger.warning("[erp-subscriber] Redis unreachable (%s) — skipping", exc)
        return
    app["redis"] = r
    app["erp_subscriber_task"] = asyncio.create_task(
        _erp_status_subscriber_loop(r), name="erp-status-subscriber",
    )


async def _on_cleanup_erp_subscriber(app: web.Application) -> None:
    task = app.get("erp_subscriber_task")
    if task is not None:
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass
    r = app.get("redis")
    if r is not None:
        try:
            await r.aclose()
        except Exception:
            pass


async def _proxy_get(url: str) -> web.Response:
    """Forward a GET to an upstream service and relay the response."""
    async with aiohttp.ClientSession() as session:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            body = await resp.json()
            return web.json_response(body, status=resp.status)


async def _proxy_post(url: str, payload: dict) -> web.Response:
    async with aiohttp.ClientSession(
        headers={"Content-Type": "application/json"}
    ) as session:
        async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            body = await resp.json()
            return web.json_response(body, status=resp.status)


async def _proxy_patch(url: str, payload: dict) -> web.Response:
    async with aiohttp.ClientSession(
        headers={"Content-Type": "application/json"}
    ) as session:
        async with session.patch(url, json=payload, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            body = await resp.json()
            return web.json_response(body, status=resp.status)


async def list_users(request: web.Request) -> web.Response:
    """GET /admin/users — proxy to data-normalizer."""
    return await _proxy_get(f"{DATA_NORMALIZER_URL}/admin/users")


async def update_user(request: web.Request) -> web.Response:
    """PATCH /admin/users/{user_id} — proxy to data-normalizer."""
    user_id = request.match_info["user_id"]
    try:
        body = await request.json()
    except json.JSONDecodeError:
        raise web.HTTPBadRequest(reason="Invalid JSON")
    return await _proxy_patch(f"{DATA_NORMALIZER_URL}/admin/users/{user_id}", body)


async def list_approvals(request: web.Request) -> web.Response:
    """GET /approvals — list pending orders from in-memory store."""
    return web.json_response(list(_pending_approvals.values()))


async def decide_approval(request: web.Request) -> web.Response:
    """POST /approvals/{request_id}/decide
    Body: { decision: "approved" | "rejected" }

    Rejected  → mark cancelled in DB, remove from queue.
    Approved  → resume Beckn select→init→confirm; fall back to mock if session expired.
    """
    request_id = request.match_info["request_id"]
    try:
        body = await request.json()
    except json.JSONDecodeError:
        raise web.HTTPBadRequest(reason="Invalid JSON")

    decision = body.get("decision")
    if decision not in ("approved", "rejected"):
        raise web.HTTPBadRequest(reason="decision must be 'approved' or 'rejected'")

    entry = _pending_approvals.get(request_id)
    if not entry:
        raise web.HTTPNotFound(reason=f"No pending approval for request_id {request_id!r}")

    if decision == "rejected":
        async with aiohttp.ClientSession(
            headers={"Content-Type": "application/json"}
        ) as sess:
            await _persist_status(sess, request_id, "cancelled")
        _pending_approvals.pop(request_id, None)
        return web.json_response({"request_id": request_id, "decision": "rejected", "status": "cancelled"})

    # ── Approved: resume Beckn commit ─────────────────────────────────────────
    txn_id       = entry["transaction_id"]
    chosen_item_id = entry["chosen_item_id"]
    state = _session_get(txn_id)

    if state is None:
        # Session expired (> 30 min) — synthesize a confirmed result.
        async with aiohttp.ClientSession(
            headers={"Content-Type": "application/json"}
        ) as sess:
            await _persist_status(sess, request_id, "confirmed")
        _pending_approvals.pop(request_id, None)
        return web.json_response({
            "request_id":  request_id,
            "decision":    "approved",
            "status":      "mock",
            "order_id":    f"approved-{request_id[:8]}",
            "order_state": "CREATED",
            "messages":    ["Session expired — order confirmed administratively"],
        })

    offerings: list[dict] = state.get("offerings", [])
    chosen = next((o for o in offerings if o["item_id"] == chosen_item_id), None)
    if chosen is None:
        _pending_approvals.pop(request_id, None)
        raise web.HTTPUnprocessableEntity(reason="Chosen item no longer in session offerings")

    bpp_id   = chosen["bpp_id"]
    bpp_uri  = chosen["bpp_uri"]
    quantity = state.get("intent", {}).get("quantity", 1)
    contract_id = str(uuid4())
    items = [{
        "id":             chosen["item_id"],
        "quantity":       quantity,
        "name":           chosen["item_name"],
        "price_value":    chosen["price_value"],
        "price_currency": chosen.get("price_currency", "INR"),
    }]

    try:
        async with aiohttp.ClientSession(
            headers={"Content-Type": "application/json"}
        ) as sess:
            intent: dict = state.get("intent") or {}

            select_resp = await _post(sess, f"{BECKN_BAP_URL}/select", {
                "transaction_id": txn_id, "bpp_id": bpp_id, "bpp_uri": bpp_uri,
                "item_id": chosen["item_id"], "item_name": chosen["item_name"],
                "provider_id": chosen.get("provider_id", ""),
                "price_value": chosen["price_value"],
                "price_currency": chosen.get("price_currency", "INR"),
                "quantity": quantity,
            })
            init_resp = await _post(sess, f"{BECKN_BAP_URL}/init", {
                "transaction_id": txn_id, "contract_id": contract_id,
                "bpp_id": bpp_id, "bpp_uri": bpp_uri, "items": items,
                "billing": _build_billing_info(), "fulfillment": _build_fulfillment_info(intent),
            })
            payment_terms = init_resp.get("payment_terms") or {
                "type": "ON_FULFILLMENT", "collected_by": "BPP",
                "currency": chosen.get("price_currency", "INR"), "status": "NOT-PAID",
            }
            confirm_resp = await _post(sess, f"{BECKN_BAP_URL}/confirm", {
                "transaction_id": txn_id, "contract_id": contract_id,
                "bpp_id": bpp_id, "bpp_uri": bpp_uri,
                "items": items, "payment_terms": payment_terms,
            })
            order_id    = confirm_resp.get("order_id") or f"order-{uuid4().hex[:8]}"
            order_state = confirm_resp.get("order_state") or "CREATED"

            await _persist_status(sess, request_id, "confirmed")
            await _persist_audit(
                sess, "approve", "approver_approved",
                reasoning_payload={"order_id": order_id, "approver": body.get("approver_id")},
                request_id=request_id,
            )

        _pending_approvals.pop(request_id, None)
        return web.json_response({
            "request_id":    request_id,
            "decision":      "approved",
            "status":        "live",
            "order_id":      order_id,
            "order_state":   order_state,
            "payment_terms": payment_terms,
            "contract_id":   contract_id,
        })

    except Exception as exc:
        logger.warning("[decide_approval] Beckn commit failed (%s) — mock fallback", exc)
        _pending_approvals.pop(request_id, None)
        async with aiohttp.ClientSession(
            headers={"Content-Type": "application/json"}
        ) as sess:
            await _persist_status(sess, request_id, "confirmed")
        return web.json_response({
            "request_id":  request_id,
            "decision":    "approved",
            "status":      "mock",
            "order_id":    f"mock-approved-{uuid4().hex[:8]}",
            "order_state": "CREATED",
            "messages":    [f"Beckn stack offline — order confirmed administratively: {exc}"],
        })


async def cancel(request: web.Request) -> web.Response:
    """PATCH /cancel — mark a procurement request as cancelled.

    Accepts request_id directly (returned by /compare and stored in the
    frontend session) — no dependency on the orchestrator in-memory session.

    Body:     { "request_id": "<uuid>" }
    Response: { "request_id": "<uuid>", "status": "cancelled" }
    """
    try:
        body = await request.json()
    except json.JSONDecodeError:
        raise web.HTTPBadRequest(reason="Invalid JSON")

    request_id = body.get("request_id", "").strip()
    if not request_id:
        raise web.HTTPBadRequest(reason="request_id is required")

    async with aiohttp.ClientSession(
        headers={"Content-Type": "application/json"}
    ) as session:
        try:
            await _patch_status_strict(session, request_id, "cancelled")
        except Exception as exc:
            logger.error("[/cancel] failed for request_id=%s: %s", request_id, exc)
            return web.json_response(
                {
                    "error": "Could not persist cancellation",
                    "detail": str(exc),
                    "request_id": request_id,
                },
                status=502,
            )
        await _persist_audit(
            session, "override", "user_cancelled",
            reasoning_payload={"reason": "user_cancelled"},
            request_id=request_id,
        )

    return web.json_response({"request_id": request_id, "status": "cancelled"})


# ── App factory ───────────────────────────────────────────────────────────────


def create_app() -> web.Application:
    app = web.Application()
    app.on_startup.append(_on_startup_erp_subscriber)
    app.on_cleanup.append(_on_cleanup_erp_subscriber)
    app.router.add_get("/health",                          health)
    app.router.add_get("/analytics",                       analytics)
    app.router.add_post("/run",                            run)
    app.router.add_post("/parse",                          parse)
    app.router.add_post("/discover",                       discover)
    app.router.add_post("/compare",                        compare)
    app.router.add_post("/commit",                         commit)
    app.router.add_route("PATCH", "/cancel",               cancel)
    app.router.add_get("/status/{txn_id}/{order_id}",      order_status)
    app.router.add_get("/order/{request_id}",              order_detail)
    app.router.add_get("/admin/users",                     list_users)
    app.router.add_route("PATCH", "/admin/users/{user_id}", update_user)
    app.router.add_get("/approvals",                       list_approvals)
    app.router.add_post("/approvals/{request_id}/decide",  decide_approval)
    return app


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    port = int(os.getenv("PORT", "8004"))
    web.run_app(create_app(), host="0.0.0.0", port=port)
