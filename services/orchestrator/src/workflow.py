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
import base64
import hashlib
import hmac
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
from policy_engine import PolicyEngine  # noqa: E402

logger = logging.getLogger(__name__)

# ── Service URLs (set via env vars in docker-compose) ─────────────────────────

INTENTION_PARSER_URL     = os.getenv("INTENTION_PARSER_URL",     "http://localhost:8001")
BECKN_BAP_URL            = os.getenv("BECKN_BAP_URL",            "http://localhost:8002")
COMPARATIVE_SCORING_URL  = os.getenv("COMPARATIVE_SCORING_URL",  "http://localhost:8003")
DATA_NORMALIZER_URL      = os.getenv("DATA_NORMALIZER_URL",      "http://localhost:8006")
DEMO_GATEWAY_URL         = os.getenv("DEMO_GATEWAY_URL",         "http://localhost:8015")

ANALYTICS_URL = os.getenv("ANALYTICS_URL", "http://localhost:8009")

# ── ERP adapter (synchronous budget gate + outbox sync) ──────────────────────

ERP_ADAPTER_URL            = os.getenv("ERP_ADAPTER_URL",            "http://localhost:8007")
ERP_INTERNAL_TOKEN         = os.getenv("ERP_INTERNAL_TOKEN",         "dev-internal-token-CHANGE_ME")
ERP_BUDGET_CHECK_ENABLED   = os.getenv("ERP_BUDGET_CHECK_ENABLED",   "true").lower() == "true"
ERP_BUDGET_CHECK_REQUIRED  = os.getenv("ERP_BUDGET_CHECK_REQUIRED",  "false").lower() == "true"
ERP_BUDGET_CHECK_TIMEOUT_MS = int(os.getenv("ERP_BUDGET_CHECK_TIMEOUT_MS", "800"))
ERP_SYNC_ENABLED           = os.getenv("ERP_SYNC_ENABLED",           "true").lower() == "true"
ERP_DEFAULT_COST_CENTER    = os.getenv("ERP_DEFAULT_COST_CENTER",    "CC-IND-PROC-01")

# Redis is kept as a legacy fallback. The primary event bus is now Kafka.
REDIS_URL                  = os.getenv("REDIS_URL",                  "")
ERP_STATE_CACHE_TTL_SECS   = int(os.getenv("ERP_STATE_CACHE_TTL_SECS", "3600"))

# ── Kafka (real-time tracking event bus) ──────────────────────────────────────
# Producers: this orchestrator (/status poll + seller webhook), erp-adapter.
# Consumers: this orchestrator (WebSocket broker + ERP enrichment cache),
#            notification-dispatcher (Slack/Teams/Email).
KAFKA_BOOTSTRAP = os.getenv("KAFKA_BOOTSTRAP", "")
KAFKA_TOPIC     = os.getenv("KAFKA_TOPIC",     "po.status.changed")
KAFKA_GROUP_ID  = os.getenv("KAFKA_GROUP_ID",  "orchestrator-ws-broker")

# ── Seller webhook (HMAC-signed push from BPP) ────────────────────────────────
SELLER_WEBHOOK_HMAC_SECRET = os.getenv("SELLER_WEBHOOK_HMAC_SECRET",
                                       "dev-seller-hmac-CHANGE_ME")

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

# ── ERP inbound state cache (populated by the Kafka consumer task) ───────────
# Keyed by transaction_id. Each entry carries the most-recent inbound webhook
# payload from the ERP adapter (state, erp_reference_id, vendor, event_ts, …).
# `/status` reads from this cache to enrich the Beckn response.
_erp_state_cache: dict[str, dict] = {}
_erp_state_times: dict[str, float] = {}

# ── Run ID index (thin side-index into _sessions; not a parallel store) ──────
# Maps run_id → transaction_id so GET /run/{run_id} can look up the session.
# A run_id is generated by run_procurement() and lives as long as the session.
_run_id_index: dict[str, str] = {}

# ── WebSocket registry (real-time tracking) ──────────────────────────────────
# Map transaction_id → list of open WebSocketResponse objects. Updated when
# `/ws/status/{txn_id}` opens/closes. Read by the Kafka consumer when it
# broadcasts events.
_ws_by_txn: dict[str, list["web.WebSocketResponse"]] = {}

# Kafka producer singleton (set in _on_startup_kafka, used by _publish_status_event).
_kafka_producer = None


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


def _run_id_put(run_id: str, txn_id: str) -> None:
    _run_id_index[run_id] = txn_id


def _run_id_get(run_id: str) -> str | None:
    return _run_id_index.get(run_id)


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


_policy_engine = PolicyEngine()


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


async def _persist(
    session: aiohttp.ClientSession,
    path: str,
    body: dict,
    *,
    method: str = "POST",
) -> dict:
    """Send body to Data Normalizer with retries. Never raises — logs on failure.

    Method defaults to POST (used by every /normalize/{request,intent,...}
    endpoint that CREATES). PATCH is used for endpoints that UPDATE existing
    rows — most importantly /normalize/po_status, which the data-normalizer
    only accepts as PATCH (POST returns 405).
    """
    if not DATA_NORMALIZER_URL:
        return {}
    method_upper = method.upper()
    for attempt in range(1, 4):  # 3 attempts
        try:
            request_cm = session.request(
                method_upper,
                f"{DATA_NORMALIZER_URL}{path}",
                json=body,
                timeout=aiohttp.ClientTimeout(total=5),
            )
            async with request_cm as resp:
                if resp.status < 300:
                    return await resp.json()
                logger.warning(
                    "[data-normalizer] %s %s returned HTTP %s (attempt %s/3)",
                    method_upper, path, resp.status, attempt,
                )
        except Exception as exc:
            logger.warning(
                "[data-normalizer] %s %s failed (attempt %s/3): %s",
                method_upper, path, attempt, exc,
            )
        if attempt < 3:
            await asyncio.sleep(attempt)  # 1s, 2s entre reintentos
    logger.warning("[data-normalizer] %s %s gave up after 3 attempts — record lost",
                   method_upper, path)
    return {}


async def _persist_order_record(
    session: aiohttp.ClientSession,
    *,
    score_ids_map: dict,
    offering_ids_map: dict,
    chosen_item_id: str,
    chosen: dict,
    quantity,
    bpp_uri: str,
    beckn_confirm_ref: str,
    requester_id: str | None,
) -> None:
    """POST /normalize/order — write confirmed order to the data normalizer.

    Looks up the score_id from session maps. No-op when score_id is absent
    (e.g. mock run where comparison never ran). Never raises.
    """
    chosen_offering_id = offering_ids_map.get(chosen_item_id, "")
    score_id = score_ids_map.get(chosen_offering_id, "")
    if not score_id:
        logger.debug(
            "[_persist_order_record] no score_id for item_id=%s — skipping /normalize/order",
            chosen_item_id,
        )
        return
    fulfillment_eta: str | None = None
    try:
        hrs = int(chosen.get("fulfillment_hours") or 0)
        if hrs:
            fulfillment_eta = (
                datetime.now(timezone.utc) + timedelta(hours=hrs)
            ).isoformat()
    except (TypeError, ValueError):
        pass
    await _persist(session, "/normalize/order", {
        "score_id":          score_id,
        "bpp_uri":           bpp_uri,
        "item_id":           chosen["item_id"],
        "quantity":          int(quantity),
        "agreed_price":      float(chosen.get("price_value", "0")),
        "beckn_confirm_ref": beckn_confirm_ref,
        "delivery_terms":    "Standard delivery",
        "currency":          chosen.get("price_currency", "INR"),
        "fulfillment_eta":   fulfillment_eta,
        "requester_id":      requester_id,
    })


async def _run_autonomous_negotiation(
    offering: dict,
    intent: dict,
) -> float | None:
    """Drive the negotiation loop autonomously against the LangGraph gateway.

    Mirrors the useNegotiation.ts browser loop entirely on the backend:
      1. POST /api/demo/negotiate   → kickoff, get thread_id
      2. Poll GET  /…/{thread_id}   → wait for awaiting_supplier or final_outcome
      3. POST /…/{thread_id}/supplier-respond  → advance the supplier LLM turn
      4. Repeat until done or max_rounds exhausted

    Returns the settled unit price as a float on success, None on any failure
    (gateway unreachable, timeout, rejection, LLM error). Callers treat None as
    "use the original quoted price" — no new fallback behaviour introduced.
    """
    if not DEMO_GATEWAY_URL:
        return None

    list_price = float(offering.get("price_value", 0) or 0)
    if list_price <= 0:
        return None

    target_price = round(list_price * 0.82)  # 18% below list, inside the 20% guardrail
    hours = offering.get("fulfillment_hours") or intent.get("delivery_timeline") or 336
    delivery_date = (
        datetime.now(timezone.utc) + timedelta(hours=int(hours))
    ).date().isoformat()

    payload = {
        "supplier_id":              offering.get("provider_id", ""),
        "supplier_name":            offering.get("provider_name", ""),
        "item":                     offering.get("item_name", intent.get("item", "")),
        "quantity":                 int(intent.get("quantity", 1)),
        "target_price":             target_price,
        "list_price":               list_price,
        "requested_delivery_date":  delivery_date,
        "max_rounds":               3,
        "category":                 offering.get("category", ""),
    }

    _POLL_INTERVAL  = 1.0   # seconds between polls
    _MAX_POLLS      = 120   # 2-minute outer budget (LLM supplier turns can be slow)
    _LLM_TIMEOUT    = 180   # supplier-respond may block on a local LLM for ~60-90 s

    try:
        # Short timeout for fast requests (kickoff, poll); long timeout for the
        # LLM supplier-respond call (set per-request below).
        fast = aiohttp.ClientTimeout(total=15)
        slow = aiohttp.ClientTimeout(total=_LLM_TIMEOUT)

        async with aiohttp.ClientSession(
            headers={"Content-Type": "application/json"},
        ) as sess:
            # 1. Kickoff
            async with sess.post(
                f"{DEMO_GATEWAY_URL}/api/demo/negotiate", json=payload, timeout=fast,
            ) as resp:
                if resp.status not in (200, 201, 202):
                    logger.warning(
                        "[auto-negotiate] kickoff returned HTTP %s", resp.status,
                    )
                    return None
                data = await resp.json()

            thread_id = data.get("thread_id")
            if not thread_id:
                logger.warning("[auto-negotiate] no thread_id in kickoff response")
                return None

            logger.info("[auto-negotiate] kickoff ok thread=%s", thread_id)

            # 2+3. Poll / supplier-respond loop.
            # Snapshot fields (from gateway NegotiationSnapshot):
            #   awaiting_supplier: bool  — True when the buyer has parked on a counter
            #   final_outcome: str|null  — set when negotiation concludes
            # Supplier-respond result fields (SupplierRespondResult):
            #   done: bool               — True when negotiation concluded this turn
            #   agreed_price: float|null — settled price when done=True & accepted
            for _ in range(_MAX_POLLS):
                await asyncio.sleep(_POLL_INTERVAL)
                async with sess.get(
                    f"{DEMO_GATEWAY_URL}/api/demo/negotiate/{thread_id}",
                    timeout=fast,
                ) as resp:
                    if resp.status != 200:
                        logger.warning(
                            "[auto-negotiate] poll returned HTTP %s", resp.status,
                        )
                        return None
                    snap = await resp.json()

                final_outcome    = snap.get("final_outcome")
                awaiting_supplier = snap.get("awaiting_supplier", False)

                # Engine concluded on its own (e.g. buyer capped out or accepted)
                if final_outcome:
                    logger.info(
                        "[auto-negotiate] engine final_outcome=%s thread=%s",
                        final_outcome, thread_id,
                    )
                    if final_outcome == "accepted":
                        history = snap.get("history") or []
                        if history:
                            last = history[-1]
                            price = (
                                last.get("supplier_price")
                                or last.get("buyer_price_offer")
                            )
                            if price is not None:
                                return float(price)
                    return None

                # Buyer is parked — ask the supplier LLM to respond
                if awaiting_supplier:
                    async with sess.post(
                        f"{DEMO_GATEWAY_URL}/api/demo/negotiate/{thread_id}/supplier-respond",
                        json={},
                        timeout=slow,   # LLM inference can take 60-90 s
                    ) as sr:
                        if sr.status not in (200, 201, 202):
                            logger.warning(
                                "[auto-negotiate] supplier-respond HTTP %s", sr.status,
                            )
                            return None
                        sr_data = await sr.json()

                    if sr_data.get("done"):
                        agreed = sr_data.get("agreed_price")
                        if agreed is not None and float(agreed) > 0:
                            logger.info(
                                "[auto-negotiate] deal accepted thread=%s price=%s",
                                thread_id, agreed,
                            )
                            return float(agreed)
                        logger.info(
                            "[auto-negotiate] no deal thread=%s outcome=%s",
                            thread_id, sr_data.get("final_outcome"),
                        )
                        return None
                    # Not done yet — re-poll after buyer computes next counter

            logger.warning("[auto-negotiate] timed out after %s polls", _MAX_POLLS)
            return None

    except Exception as exc:
        logger.warning("[auto-negotiate] error: %s", exc)
        return None


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


class NoOfferingsFound(Exception):
    """Raised by _compare_phase when discovery returns no offerings.

    Allows compare() and run_procurement() to return different shaped responses
    for the empty case without duplicating the early-return logic.
    """
    def __init__(self, transaction_id: str, request_id: str) -> None:
        super().__init__("no offerings returned from discovery")
        self.transaction_id = transaction_id
        self.request_id = request_id


async def _compare_phase(
    session: aiohttp.ClientSession,
    body: dict,
    actor: dict | None,
    raw_query: str,
) -> dict:
    """Core discover + score phase, shared by compare() and run_procurement().

    Handles DB persistence, scoring, and reasoning-step construction.
    Does NOT call _session_put — callers add extra fields before storing.

    Returns a dict with:
        transaction_id, request_id, requester_id, approval_threshold,
        offerings, selected, recommended_item_id, scoring_block,
        reasoning_steps, messages, beckn_intent_id, query_id,
        offering_ids_map, score_ids_map

    Raises NoOfferingsFound when discovery returns no offerings (after
    cancelling the DB row). Re-raises all other exceptions after cancelling
    the DB row (so orphan rows never linger in draft/discovering states).
    """
    request_id = ""
    try:
        # ── Persist request + intent BEFORE external calls ───────────────────
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
            await _persist_status(session, request_id, "discovering")

        # ── Step 2: discover ──────────────────────────────────────────────────
        discover_result = await _post(session, f"{BECKN_BAP_URL}/discover", body)
        transaction_id = discover_result.get("transaction_id") or str(uuid4())
        offerings: list[dict] = discover_result.get("offerings", [])

        if not offerings:
            if request_id:
                await _persist_audit(
                    session, "discover", "no_offerings_found",
                    reasoning_payload={"item": body.get("item")},
                    request_id=request_id,
                )
                await _persist_status(session, request_id, "cancelled")
            raise NoOfferingsFound(transaction_id, request_id)

        # ── Persist discovery + advance status to 'scoring' ──────────────────
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

        # ── Step 3: score (rank-only, no select) ─────────────────────────────
        score_result = await _post(
            session, f"{COMPARATIVE_SCORING_URL}/score", {"offerings": offerings}
        )
        selected: dict | None = score_result.get("selected")
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

        reasoning_steps: list[dict] = [
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
            scoring_block = _build_ml_scoring(offerings, adapter_scoring, recommended_item_id)
            ranked_provider = {o["item_id"]: o["provider_name"] for o in offerings}
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

        # ── Persist scoring + final status ────────────────────────────────────
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
                    (o["price_value"] for o in offerings if o["item_id"] == item_id), "0",
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
            recommended_category = (
                (selected or {}).get("category")
                or (offerings[0].get("category") if offerings else None)
            )
            await _persist_status(
                session, request_id, "negotiating", category=recommended_category
            )

        return {
            "transaction_id":    transaction_id,
            "request_id":        request_id,
            "requester_id":      requester_id,
            "approval_threshold": approval_threshold,
            "offerings":         offerings,
            "selected":          selected,
            "recommended_item_id": recommended_item_id,
            "scoring_block":     scoring_block,
            "reasoning_steps":   reasoning_steps,
            "messages":          messages,
            "beckn_intent_id":   beckn_intent_id,
            "query_id":          query_id,
            "offering_ids_map":  offering_ids_map,
            "score_ids_map":     score_ids_map,
        }

    except NoOfferingsFound:
        raise  # pass through unchanged
    except Exception:
        if request_id:
            try:
                await _persist_status(session, request_id, "cancelled")
            except Exception:
                pass
        raise


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

    raw_query = (body.pop("raw_query", None) or "").strip()
    actor = body.pop("actor", None)

    if not body.get("item"):
        raise web.HTTPBadRequest(reason="item is required in BecknIntent body")

    try:
        async with aiohttp.ClientSession(
            headers={"Content-Type": "application/json"}
        ) as session:
            try:
                result = await _compare_phase(session, body, actor, raw_query)
            except NoOfferingsFound as e:
                return web.json_response({
                    "transaction_id":      e.transaction_id,
                    "request_id":          e.request_id,
                    "offerings":           [],
                    "recommended_item_id": None,
                    "scoring":             {"recommended_item_id": None, "criteria": [], "ranking": []},
                    "reasoning_steps":     [],
                    "messages":            ["No offerings returned from the supplier network"],
                    "status":              "live",
                })

            _session_put(result["transaction_id"], {
                "transaction_id":     result["transaction_id"],
                "offerings":          result["offerings"],
                "selected":           result["selected"],
                "intent":             body,
                "request_id":         result["request_id"],
                "requester_id":       result["requester_id"],
                "approval_threshold": result["approval_threshold"],
                "beckn_intent_id":    result["beckn_intent_id"],
                "query_id":           result["query_id"],
                "offering_ids_map":   result["offering_ids_map"],
                "score_ids_map":      result["score_ids_map"],
            })

        return web.json_response({
            "transaction_id":      result["transaction_id"],
            "request_id":          result["request_id"],
            "offerings":           result["offerings"],
            "recommended_item_id": result["recommended_item_id"],
            "scoring":             result["scoring_block"],
            "reasoning_steps":     result["reasoning_steps"],
            "messages":            result["messages"],
            "status":              "live",
        })

    except Exception as exc:
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


async def _execute_beckn_commit(
    sess: aiohttp.ClientSession,
    *,
    txn_id: str,
    chosen: dict,
    intent: dict,
    contract_id: str,
) -> dict:
    """Execute Beckn select → init → confirm.

    Shared by decide_approval(), decide_run(), and run_procurement() (auto_commit).
    Handles only Beckn protocol calls — DB persistence is the caller's responsibility.

    Returns:
        {bpp_id, bpp_uri, items, order_id, order_state, payment_terms,
         select_ack, messages, reasoning_steps}
    Raises on any Beckn call failure (caller decides mock vs. hard error).
    """
    bpp_id = chosen["bpp_id"]
    bpp_uri = chosen["bpp_uri"]
    try:
        quantity = int(intent.get("quantity", 1))
    except (TypeError, ValueError):
        quantity = 1
    items = [{
        "id":             chosen["item_id"],
        "quantity":       quantity,
        "name":           chosen["item_name"],
        "price_value":    chosen["price_value"],
        "price_currency": chosen.get("price_currency", "INR"),
    }]
    messages: list[str] = []

    # Step 4a: /select
    select_resp = await _post(sess, f"{BECKN_BAP_URL}/select", {
        "transaction_id": txn_id,
        "bpp_id":         bpp_id,
        "bpp_uri":        bpp_uri,
        "item_id":        chosen["item_id"],
        "item_name":      chosen["item_name"],
        "provider_id":    chosen.get("provider_id", ""),
        "price_value":    chosen["price_value"],
        "price_currency": chosen.get("price_currency", "INR"),
        "quantity":       quantity,
    })
    select_ack = select_resp.get("ack", "UNKNOWN")
    messages.append(f"[send_select] ACK={select_ack}")

    # Step 4b: /init
    init_resp = await _post(sess, f"{BECKN_BAP_URL}/init", {
        "transaction_id": txn_id,
        "contract_id":    contract_id,
        "bpp_id":         bpp_id,
        "bpp_uri":        bpp_uri,
        "items":          items,
        "billing":        _build_billing_info(),
        "fulfillment":    _build_fulfillment_info(intent),
    })
    payment_terms = init_resp.get("payment_terms") or {
        "type":         "ON_FULFILLMENT",
        "collected_by": "BPP",
        "currency":     chosen.get("price_currency", "INR"),
        "status":       "NOT-PAID",
    }
    messages.append(f"[send_init] payment_terms set, ack={init_resp.get('ack')}")

    # Step 4c: /confirm
    confirm_resp = await _post(sess, f"{BECKN_BAP_URL}/confirm", {
        "transaction_id": txn_id,
        "contract_id":    contract_id,
        "bpp_id":         bpp_id,
        "bpp_uri":        bpp_uri,
        "items":          items,
        "payment_terms":  payment_terms,
    })
    order_id    = confirm_resp.get("order_id")    or f"order-{uuid4().hex[:8]}"
    order_state = confirm_resp.get("order_state") or "CREATED"
    messages.append(f"[send_confirm] order_id={order_id} state={order_state}")

    provider_label = chosen.get("provider_name", chosen.get("bpp_id", ""))
    reasoning_steps = [
        {
            "node": "send_select",
            "role": "act",
            "summary": f"/select sent to {provider_label} — ACK={select_ack}",
            "details": {
                "ack_status":  select_ack,
                "bpp_id":      bpp_id,
                "provider_id": chosen.get("provider_id", ""),
                "contract_id": contract_id,
            },
            "timestamp": _now_iso(),
        },
        {
            "node": "send_init",
            "role": "act",
            "summary": (
                f"/init confirmed — payment "
                f"{payment_terms.get('type')}/{payment_terms.get('collected_by')}"
            ),
            "details": {
                "contract_id":  contract_id,
                "payment_type": payment_terms.get("type"),
                "collected_by": payment_terms.get("collected_by"),
                "currency":     payment_terms.get("currency"),
            },
            "timestamp": _now_iso(),
        },
        {
            "node": "send_confirm",
            "role": "act",
            "summary": f"Order confirmed — {order_id} ({order_state})",
            "details": {"order_id": order_id, "order_state": order_state},
            "timestamp": _now_iso(),
        },
        {
            "node": "present_results",
            "role": "observe",
            "summary": (
                f"Order CONFIRMED — {chosen.get('item_name', '')} × {quantity} | "
                f"₹{chosen['price_value']} {chosen.get('price_currency', 'INR')} | "
                f"order={order_id} state={order_state}"
            ),
            "details": {},
            "timestamp": _now_iso(),
        },
    ]

    return {
        "bpp_id":          bpp_id,
        "bpp_uri":         bpp_uri,
        "items":           items,
        "order_id":        order_id,
        "order_state":     order_state,
        "payment_terms":   payment_terms,
        "select_ack":      select_ack,
        "messages":        messages,
        "reasoning_steps": reasoning_steps,
    }


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
                    }, method="PATCH")
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
                    # Publish to Kafka — the WS broker forwards to the dashboard
                    # and the notification-dispatcher fires Slack/Teams/Email.
                    await _publish_status_event({
                        "transaction_id": txn_id,
                        "order_id":       order_id,
                        "state":          new_state,
                        "previous_state": last_state,
                        "po_status":      po_state,
                        "observed_at":    _now_iso(),
                        "source":         "beckn_poll",
                    })
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


async def _run_pipeline_handler(request: web.Request) -> web.Response:
    """POST /run-pipeline  { "query": "..." } — legacy CLI-style full pipeline.
    Kept for internal testing; not registered on the public /run route.
    """
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


# ── Kafka producer + consumer (real-time tracking) ────────────────────────────


async def _publish_status_event(payload: dict) -> None:
    """Fire-and-forget publish to Kafka `po.status.changed`. Never raises.

    Called by the /status poll loop and the seller webhook. Subscribers:
      • this orchestrator (WebSocket broker + ERP enrichment cache)
      • notification-dispatcher (Slack/Teams/Email)
    """
    if _kafka_producer is None:
        logger.debug("[kafka] producer not initialised — skipping publish")
        return
    try:
        await _kafka_producer.send_and_wait(
            KAFKA_TOPIC,
            value=json.dumps(payload).encode("utf-8"),
        )
        logger.info("[kafka] published state=%s txn=%s source=%s",
                    payload.get("state"), payload.get("transaction_id"),
                    payload.get("source"))
    except Exception as exc:
        logger.warning("[kafka] publish failed: %s", exc)


async def _kafka_status_consumer_loop(consumer) -> None:
    """Long-running task — reads `po.status.changed` events and (a) updates
    the local ERP cache, (b) broadcasts to all WebSocket clients subscribed
    to the txn_id. Best-effort: any failure logs and continues.
    """
    try:
        async for msg in consumer:
            try:
                payload = json.loads(msg.value.decode("utf-8"))
                txn_id = payload.get("transaction_id")
                if not txn_id:
                    continue

                # (a) Update local cache so `/status` enrichment keeps working
                _erp_state_cache[txn_id] = payload
                _erp_state_times[txn_id] = time.monotonic()

                # (b) Broadcast to every WS client subscribed to this txn
                conns = list(_ws_by_txn.get(txn_id, []))
                dead = []
                for ws in conns:
                    if ws.closed:
                        dead.append(ws)
                        continue
                    try:
                        await ws.send_json(payload)
                    except (ConnectionResetError, RuntimeError):
                        dead.append(ws)
                if dead:
                    survivors = [w for w in _ws_by_txn.get(txn_id, []) if w not in dead]
                    if survivors:
                        _ws_by_txn[txn_id] = survivors
                    else:
                        _ws_by_txn.pop(txn_id, None)
                logger.info("[kafka] forwarded state=%s txn=%s to %d ws client(s)",
                            payload.get("state"), txn_id, len(conns) - len(dead))
            except Exception as exc:
                logger.warning("[kafka] malformed message: %s", exc)
    except asyncio.CancelledError:
        logger.info("[kafka] consumer cancelled")
        raise
    except Exception as exc:
        logger.warning("[kafka] consumer loop failed: %s", exc)


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


async def _on_startup_kafka(app: web.Application) -> None:
    """Start the Kafka producer + consumer. Degrades silently if unavailable —
    the polling fallback in the frontend will continue to work."""
    if not KAFKA_BOOTSTRAP:
        logger.info("[kafka] KAFKA_BOOTSTRAP not set — skipping (no real-time)")
        return
    try:
        from aiokafka import AIOKafkaProducer, AIOKafkaConsumer  # type: ignore
    except ImportError as exc:
        logger.warning("[kafka] aiokafka not installed: %s — skipping", exc)
        return

    global _kafka_producer
    try:
        producer = AIOKafkaProducer(bootstrap_servers=KAFKA_BOOTSTRAP)
        await producer.start()
        _kafka_producer = producer
        app["kafka_producer"] = producer
        logger.info("[kafka] producer connected to %s", KAFKA_BOOTSTRAP)
    except Exception as exc:
        logger.warning("[kafka] producer init failed: %s — skipping producer", exc)
        _kafka_producer = None

    try:
        consumer = AIOKafkaConsumer(
            KAFKA_TOPIC,
            bootstrap_servers=KAFKA_BOOTSTRAP,
            group_id=KAFKA_GROUP_ID,
            auto_offset_reset="latest",
            enable_auto_commit=True,
        )
        await consumer.start()
        app["kafka_consumer"] = consumer
        app["kafka_consumer_task"] = asyncio.create_task(
            _kafka_status_consumer_loop(consumer), name="kafka-status-consumer",
        )
        logger.info("[kafka] consumer subscribed to %s (group=%s)",
                    KAFKA_TOPIC, KAFKA_GROUP_ID)
    except Exception as exc:
        logger.warning("[kafka] consumer init failed: %s — skipping consumer", exc)


async def _on_cleanup_kafka(app: web.Application) -> None:
    """Cancel consumer task and stop producer + consumer cleanly."""
    global _kafka_producer
    task = app.get("kafka_consumer_task")
    if task is not None:
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass
    consumer = app.get("kafka_consumer")
    if consumer is not None:
        try:
            await consumer.stop()
        except Exception:
            pass
    producer = app.get("kafka_producer")
    if producer is not None:
        try:
            await producer.stop()
        except Exception:
            pass
    _kafka_producer = None


# ── WebSocket endpoint ───────────────────────────────────────────────────────


async def ws_status(request: web.Request) -> web.WebSocketResponse:
    """GET /ws/status/{txn_id} — live order status push.

    On open: sends an initial snapshot from the in-memory session + ERP cache.
    Afterwards: every `po.status.changed` event for this txn is forwarded by
    the Kafka consumer. Client messages are ignored (read-only channel).
    """
    txn_id = request.match_info["txn_id"]
    ws = web.WebSocketResponse(heartbeat=30)
    await ws.prepare(request)

    _ws_by_txn.setdefault(txn_id, []).append(ws)
    logger.info("[ws] connected txn=%s (clients=%d)",
                txn_id, len(_ws_by_txn[txn_id]))

    try:
        # Initial snapshot from whatever we already know.
        session_state = _session_get(txn_id) or {}
        erp_state = _erp_state_for(txn_id)
        await ws.send_json({
            "transaction_id": txn_id,
            "order_id":       session_state.get("order_id"),
            "state":          session_state.get("order_state"),
            "erp_state":      _erp_state_block(erp_state) if erp_state else None,
            "observed_at":    _now_iso(),
            "source":         "initial_snapshot",
        })

        # Hold the connection open. Broadcasts come from the Kafka consumer.
        async for msg in ws:
            if msg.type == web.WSMsgType.ERROR:
                logger.warning("[ws] error txn=%s: %s", txn_id, ws.exception())
                break
            # Drop any client-sent payload; clients are read-only.
    finally:
        conns = _ws_by_txn.get(txn_id, [])
        if ws in conns:
            conns.remove(ws)
        if not conns:
            _ws_by_txn.pop(txn_id, None)
        logger.info("[ws] disconnected txn=%s (remaining=%d)", txn_id, len(conns))
    return ws


# ── Seller webhook endpoint ──────────────────────────────────────────────────


async def seller_status_webhook(request: web.Request) -> web.Response:
    """POST /webhooks/seller/status — BPP pushes a state change directly.

    Authenticated via HMAC SHA-256 signature in the `X-Signature` header
    (base64-encoded). On success: persists via `/normalize/po_status`, fires
    an audit event, and publishes to Kafka so the WS broker + notification
    dispatcher fan out.

    Body: { "transaction_id": "...", "order_id": "...", "beckn_state": "SHIPPED" }
    """
    raw_body = await request.read()

    # Validate HMAC signature
    sig_header = request.headers.get("X-Signature", "")
    expected_sig = base64.b64encode(
        hmac.new(SELLER_WEBHOOK_HMAC_SECRET.encode("utf-8"),
                 raw_body, hashlib.sha256).digest()
    ).decode("ascii")
    if not sig_header or not hmac.compare_digest(sig_header, expected_sig):
        logger.warning("[seller-webhook] HMAC mismatch (got=%r)", sig_header[:20])
        return web.json_response({"error": "invalid signature"}, status=401)

    try:
        body = json.loads(raw_body.decode("utf-8"))
    except json.JSONDecodeError:
        return web.json_response({"error": "invalid JSON"}, status=400)

    txn_id      = (body.get("transaction_id") or "").strip()
    order_id    = (body.get("order_id")       or "").strip()
    beckn_state = (body.get("beckn_state")    or "").strip().upper()

    if not txn_id or not order_id or not beckn_state:
        return web.json_response(
            {"error": "transaction_id, order_id and beckn_state are required"},
            status=400,
        )

    po_state = _beckn_state_to_po_status(beckn_state)
    if po_state is None:
        return web.json_response(
            {"error": f"unsupported beckn_state '{beckn_state}'"},
            status=400,
        )

    # Persist + audit (fire-and-forget on persist failure)
    async with aiohttp.ClientSession(
        headers={"Content-Type": "application/json"}
    ) as session:
        await _persist(session, "/normalize/po_status", {
            "beckn_confirm_ref": order_id,
            "state":             po_state,
        }, method="PATCH")
        await _persist_audit(
            session, "confirm",
            f"seller webhook → {beckn_state} (po_status={po_state})",
            reasoning_payload={
                "transaction_id": txn_id,
                "order_id":       order_id,
                "beckn_state":    beckn_state,
                "po_status":      po_state,
                "source":         "seller_webhook",
            },
        )

    # Publish to Kafka — WS broker + notification dispatcher fan out from here
    await _publish_status_event({
        "transaction_id": txn_id,
        "order_id":       order_id,
        "state":          beckn_state,
        "po_status":      po_state,
        "observed_at":    _now_iso(),
        "source":         "seller_webhook",
    })

    return web.json_response({
        "transaction_id": txn_id,
        "order_id":       order_id,
        "state":          beckn_state,
    })


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

    contract_id = str(uuid4())
    try:
        async with aiohttp.ClientSession(
            headers={"Content-Type": "application/json"}
        ) as sess:
            cr = await _execute_beckn_commit(
                sess,
                txn_id=txn_id,
                chosen=chosen,
                intent=state.get("intent") or {},
                contract_id=contract_id,
            )
            order_id    = cr["order_id"]
            order_state = cr["order_state"]
            payment_terms = cr["payment_terms"]

            await _persist_status(sess, request_id, "confirmed")
            await _persist_audit(
                sess, "approve", "approver_approved",
                reasoning_payload={"order_id": order_id, "approver": body.get("approver_id")},
                request_id=request_id,
            )
            await _persist_order_record(
                sess,
                score_ids_map=state.get("score_ids_map", {}),
                offering_ids_map=state.get("offering_ids_map", {}),
                chosen_item_id=chosen_item_id,
                chosen=chosen,
                quantity=state.get("intent", {}).get("quantity", 1),
                bpp_uri=cr["bpp_uri"],
                beckn_confirm_ref=order_id,
                requester_id=state.get("requester_id"),
            )

        _pending_approvals.pop(request_id, None)
        # Update the /run session stage so GET /run/{run_id} reflects "confirmed".
        _session_put(txn_id, {
            **state,
            "stage":          "confirmed",
            "order_id":       order_id,
            "order_state":    order_state,
            "payment_terms":  payment_terms,
            "contract_id":    contract_id,
            "bpp_id":         cr["bpp_id"],
            "bpp_uri":        cr["bpp_uri"],
        })
        run_id = state.get("run_id")
        return web.json_response({
            "request_id":    request_id,
            "run_id":        run_id,
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
        mock_order_id = f"mock-approved-{uuid4().hex[:8]}"
        # Update session stage even on mock path so GET /run/{run_id} is consistent.
        _session_put(txn_id, {
            **state,
            "stage":       "confirmed",
            "order_id":    mock_order_id,
            "order_state": "CREATED",
        })
        async with aiohttp.ClientSession(
            headers={"Content-Type": "application/json"}
        ) as sess:
            await _persist_status(sess, request_id, "confirmed")
        run_id = state.get("run_id")
        return web.json_response({
            "request_id":  request_id,
            "run_id":      run_id,
            "decision":    "approved",
            "status":      "mock",
            "order_id":    mock_order_id,
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


# ── Orchestrated /run state machine ──────────────────────────────────────────


async def run_procurement(request: web.Request) -> web.Response:
    """POST /run — unified orchestration entry point.

    Accepts a BecknIntent body + execution_mode + actor. Runs discovery +
    scoring, evaluates enterprise policy via PolicyEngine, and dispatches to
    the initial workflow stage determined by the resolved policy.

    execution_mode: "advisory" | "hitl" | "autonomous"  (default: advisory)

    Response (200):
        { run_id, transaction_id, request_id, stage, execution_mode,
          offerings, recommended_item_id, scoring, reasoning_steps,
          messages, decision, status }
    Response (202) when stage == "awaiting_rbac_approval":
        { run_id, stage, request_id, amount_total, explanation, decision }
    Response (200) when stage == "confirmed" (autonomous + within limits):
        { run_id, stage, order_id, order_state, … }
    """
    try:
        body = await request.json()
    except json.JSONDecodeError:
        raise web.HTTPBadRequest(reason="Invalid JSON")

    raw_query      = (body.pop("raw_query",      None) or "").strip()
    actor          = body.pop("actor",           None)
    execution_mode = (body.pop("execution_mode", None) or "advisory").lower()

    if execution_mode not in ("advisory", "hitl", "autonomous"):
        raise web.HTTPBadRequest(
            reason="execution_mode must be 'advisory', 'hitl', or 'autonomous'"
        )
    if not body.get("item"):
        raise web.HTTPBadRequest(reason="item is required in BecknIntent body")

    run_id = f"run-{uuid4().hex[:12]}"

    try:
        async with aiohttp.ClientSession(
            headers={"Content-Type": "application/json"}
        ) as session:
            try:
                result = await _compare_phase(session, body, actor, raw_query)
            except NoOfferingsFound as e:
                return web.json_response({
                    "run_id":         run_id,
                    "stage":          "no_offerings",
                    "transaction_id": e.transaction_id,
                    "request_id":     e.request_id,
                    "offerings":      [],
                    "messages":       ["No offerings returned from the supplier network"],
                    "status":         "live",
                })

            # Compute order total before ERP evaluation (needed for both the
            # policy gate and the autonomous RBAC pre-check in PolicyEngine).
            recommended = next(
                (o for o in result["offerings"]
                 if o["item_id"] == result["recommended_item_id"]),
                result["offerings"][0] if result["offerings"] else None,
            )
            try:
                quantity_val = body.get("quantity") or 1
                order_total_eval = (
                    Decimal(str(recommended["price_value"])) * Decimal(str(quantity_val))
                    if recommended else Decimal("0")
                )
            except Exception:
                order_total_eval = Decimal("0")

            # ERP policy evaluation — fail-open; PolicyEngine receives a neutral
            # envelope (fallback=True) when the ERP adapter is unavailable.
            erp_client = _get_erp_client()
            if erp_client is not None:
                from erp.client import PolicyEvaluateRequest as _ErpPolicyReq  # noqa: PLC0415
                erp_envelope: dict | None = await erp_client.policy_evaluate(_ErpPolicyReq(
                    transaction_id=result["transaction_id"],
                    cost_center=(actor or {}).get("cost_center") or "default",
                    order_total=order_total_eval,
                    currency="INR",
                    category=str(body.get("item") or "uncategorized"),
                    requester_id=(
                        (actor or {}).get("keycloak_id")
                        or (actor or {}).get("email")
                        or "anonymous"
                    ),
                    provider_ids=[o["provider_id"] for o in result["offerings"]],
                    item_ids=[o["item_id"] for o in result["offerings"]],
                ))
            else:
                erp_envelope = None

            # ── PolicyEngine: sole source of all procurement policy logic ─────
            decision = _policy_engine.evaluate(
                execution_mode=execution_mode,
                erp_envelope=erp_envelope,
                offerings=result["offerings"],
                ml_recommended_item_id=result["recommended_item_id"],
                order_total=order_total_eval,
                approval_threshold=Decimal(str(result["approval_threshold"])),
            )

            # ── Store session (workflow-augmented: run_id, mode, stage, decision)
            _session_put(result["transaction_id"], {
                "transaction_id":     result["transaction_id"],
                "run_id":             run_id,
                "execution_mode":     execution_mode,
                "stage":              decision.next_stage,
                "offerings":          result["offerings"],
                "selected":           result["selected"],
                "intent":             body,
                "request_id":         result["request_id"],
                "requester_id":       result["requester_id"],
                "approval_threshold": result["approval_threshold"],
                "beckn_intent_id":    result["beckn_intent_id"],
                "query_id":           result["query_id"],
                "offering_ids_map":   result["offering_ids_map"],
                "score_ids_map":      result["score_ids_map"],
                "erp_policy":         erp_envelope,
                "decision":           decision.to_dict(),
            })
            _run_id_put(run_id, result["transaction_id"])

            # ── State machine — branches ONLY on decision.next_stage ──────────
            # No business rules below this line.

            if decision.next_stage in ("awaiting_selection", "awaiting_approval"):
                return web.json_response({
                    "run_id":              run_id,
                    "transaction_id":      result["transaction_id"],
                    "request_id":          result["request_id"],
                    "stage":               decision.next_stage,
                    "execution_mode":      execution_mode,
                    "offerings":           result["offerings"],
                    "recommended_item_id": decision.final_item_id,
                    "scoring":             result["scoring_block"],
                    "reasoning_steps":     result["reasoning_steps"],
                    "messages":            result["messages"],
                    "decision":            decision.to_dict(),
                    "status":              "live",
                })

            if decision.next_stage == "awaiting_rbac_approval":
                req_id = result["request_id"]
                _pending_approvals[req_id] = {
                    "run_id":           run_id,
                    "request_id":       req_id,
                    "transaction_id":   result["transaction_id"],
                    "chosen_item_id":   decision.final_item_id,
                    "actor":            actor or {},
                    "amount_total":     float(order_total_eval),
                    "item_description": body.get("item", ""),
                    "provider_name":    decision.final_provider_name or "",
                    "created_at":       _now_iso(),
                }
                await _persist_status(session, req_id, "pending_approval")
                return web.json_response({
                    "run_id":       run_id,
                    "stage":        "awaiting_rbac_approval",
                    "request_id":   req_id,
                    "amount_total": float(order_total_eval),
                    "explanation":  decision.explanation,
                    "decision":     decision.to_dict(),
                }, status=202)

            # auto_commit: execute Beckn commit inline
            if not recommended:
                return web.json_response(
                    {"error": "auto_commit requested but no offering available"},
                    status=500,
                )
            contract_id = str(uuid4())
            is_mock = False

            # Autonomous negotiation: PolicyEngine instructs us to attempt a
            # price negotiation before committing.  On success we override the
            # quoted price in a local copy of the offering; on failure (service
            # down, timeout, rejection) we fall through to the original price —
            # the existing mock-fallback path handles the rest unchanged.
            chosen_for_commit = recommended
            negotiation_settled_price: float | None = None
            if decision.requires_negotiation:
                original_price_str = recommended.get("price_value", "0")
                settled_price = await _run_autonomous_negotiation(recommended, body)
                if settled_price is not None:
                    chosen_for_commit = {**recommended, "price_value": str(settled_price)}
                    negotiation_settled_price = settled_price
                    try:
                        orig = float(original_price_str)
                        savings_pct = (orig - settled_price) / orig * 100 if orig > 0 else 0
                        result["messages"].append(
                            f"[auto-negotiate] settled at ₹{settled_price:.2f} "
                            f"(was ₹{orig:.2f}, saved {savings_pct:.1f}%)"
                        )
                    except (TypeError, ValueError):
                        result["messages"].append(
                            f"[auto-negotiate] settled at ₹{settled_price:.2f}"
                        )
                    logger.info(
                        "[auto_commit] negotiated price %s → %s for txn=%s",
                        original_price_str, settled_price,
                        result["transaction_id"],
                    )
                else:
                    result["messages"].append(
                        f"[auto-negotiate] no deal reached — committed at catalog price ₹{original_price_str}"
                    )
                    logger.info(
                        "[auto_commit] negotiation failed/skipped, original price=%s txn=%s",
                        original_price_str, result["transaction_id"],
                    )

            try:
                cr = await _execute_beckn_commit(
                    session,
                    txn_id=result["transaction_id"],
                    chosen=chosen_for_commit,
                    intent=body,
                    contract_id=contract_id,
                )
                await _persist_status(session, result["request_id"], "confirmed")
                await _persist_audit(
                    session, "confirm",
                    f"auto_commit order_confirmed: {cr['order_id']}",
                    reasoning_payload={
                        "order_id":    cr["order_id"],
                        "run_id":      run_id,
                        "mode":        execution_mode,
                        "item_id":     recommended["item_id"],
                    },
                    request_id=result["request_id"],
                )
                await _persist_order_record(
                    session,
                    score_ids_map=result.get("score_ids_map", {}),
                    offering_ids_map=result.get("offering_ids_map", {}),
                    chosen_item_id=chosen_for_commit["item_id"],
                    chosen=chosen_for_commit,
                    quantity=body.get("quantity", 1),
                    bpp_uri=cr["bpp_uri"],
                    beckn_confirm_ref=cr["order_id"],
                    requester_id=result.get("requester_id"),
                )
            except Exception as exc:
                logger.warning("[run/auto_commit] Beckn commit failed (%s) — mock", exc)
                cr = {
                    "order_id":       f"mock-run-{uuid4().hex[:8]}",
                    "order_state":    "CREATED",
                    "payment_terms":  {
                        "type": "ON_FULFILLMENT", "collected_by": "BPP",
                        "currency": recommended.get("price_currency", "INR"),
                        "status": "NOT-PAID",
                    },
                    "bpp_id":         recommended["bpp_id"],
                    "bpp_uri":        recommended["bpp_uri"],
                    "messages":       [f"[mock] Beckn stack offline: {exc}"],
                    "reasoning_steps": [],
                }
                is_mock = True

            _session_put(result["transaction_id"], {
                **(_session_get(result["transaction_id"]) or {}),
                "stage":        "confirmed",
                "order_id":     cr["order_id"],
                "order_state":  cr["order_state"],
                "payment_terms": cr["payment_terms"],
                "contract_id":  contract_id,
                "bpp_id":       cr["bpp_id"],
                "bpp_uri":      cr["bpp_uri"],
            })

            if ERP_SYNC_ENABLED and cr.get("order_id") and not is_mock:
                try:
                    po_payload = build_normalized_po(
                        state={**result, "transaction_id": result["transaction_id"]},
                        chosen=recommended,
                        intent=body,
                        order_id=cr["order_id"],
                        contract_id=contract_id,
                        payment_terms=cr["payment_terms"],
                        fulfillment_eta=None,
                        budget_hold_id=None,
                        buyer=_build_buyer_dict(),
                    )
                    asyncio.create_task(_get_erp_client().enqueue_sync(po_payload))
                except Exception as exc:
                    logger.warning("[run/erp-sync] build failed txn=%s err=%s",
                                   result["transaction_id"], exc)

            return web.json_response({
                "run_id":                   run_id,
                "transaction_id":           result["transaction_id"],
                "request_id":               result["request_id"],
                "stage":                    "confirmed",
                "execution_mode":           execution_mode,
                "order_id":                 cr["order_id"],
                "order_state":              cr["order_state"],
                "payment_terms":            cr["payment_terms"],
                "contract_id":              contract_id,
                "bpp_id":                   cr["bpp_id"],
                "bpp_uri":                  cr["bpp_uri"],
                "reasoning_steps":          result["reasoning_steps"] + cr.get("reasoning_steps", []),
                "messages":                 result["messages"] + cr.get("messages", []),
                "decision":                 decision.to_dict(),
                "status":                   "mock" if is_mock else "live",
                # Included so the frontend can build an order-page session without
                # a DB round-trip and display the negotiated price badge.
                "offerings":                result.get("offerings", []),
                "recommended_item_id":      recommended.get("item_id"),
                "negotiation_settled_price": negotiation_settled_price,
            })

    except (web.HTTPBadRequest,):
        raise
    except Exception as exc:
        logger.error("[run_procurement] failed (%s) — returning error", exc)
        return web.json_response(
            {"error": "Supplier network unavailable",
             "detail": "Could not complete procurement run. Please try again."},
            status=502,
        )


async def get_run(request: web.Request) -> web.Response:
    """GET /run/{run_id} — current stage and state for a procurement run.

    Response: { run_id, transaction_id, request_id, stage, execution_mode,
                decision, offerings, recommended_item_id, order_id, order_state }
    """
    run_id = request.match_info["run_id"]
    txn_id = _run_id_get(run_id)
    if txn_id is None:
        raise web.HTTPNotFound(reason=f"Unknown run_id: {run_id!r}")

    state = _session_get(txn_id)
    if state is None:
        raise web.HTTPGone(reason=f"Run {run_id!r} session expired (> 30 min)")

    stored_decision = state.get("decision") or {}
    return web.json_response({
        "run_id":              run_id,
        "transaction_id":      txn_id,
        "request_id":          state.get("request_id", ""),
        "stage":               state.get("stage", "unknown"),
        "execution_mode":      state.get("execution_mode"),
        "decision":            stored_decision,
        "offerings":           state.get("offerings", []),
        "recommended_item_id": stored_decision.get("final_item_id"),
        "order_id":            state.get("order_id"),
        "order_state":         state.get("order_state"),
    })


async def decide_run(request: web.Request) -> web.Response:
    """POST /run/{run_id}/decide — advance a run after a human decision.

    For advisory (stage=awaiting_selection): body must include chosen_item_id.
    For hitl (stage=awaiting_approval): body.decision="proceed" confirms the
    agent's recommendation; "reject" cancels.

    Body:
        { decision: "proceed" | "reject",
          chosen_item_id?: str,      # required for awaiting_selection
          approver_id?: str }

    Response (200): { run_id, stage: "confirmed", order_id, … }
    Response (202): { run_id, stage: "awaiting_rbac_approval", amount_total }
    """
    run_id = request.match_info["run_id"]
    try:
        body = await request.json()
    except json.JSONDecodeError:
        raise web.HTTPBadRequest(reason="Invalid JSON")

    decision_str = body.get("decision")
    if decision_str not in ("proceed", "reject"):
        raise web.HTTPBadRequest(reason="decision must be 'proceed' or 'reject'")

    txn_id = _run_id_get(run_id)
    if txn_id is None:
        raise web.HTTPNotFound(reason=f"Unknown run_id: {run_id!r}")

    state = _session_get(txn_id)
    if state is None:
        raise web.HTTPGone(reason=f"Run {run_id!r} session expired (> 30 min)")

    request_id = state.get("request_id", "")

    if decision_str == "reject":
        # PolicyEngine decides the next stage on rejection.
        # HITL: transition to awaiting_selection (re-use existing offerings).
        # Others: cancel.
        rejection_stage = _policy_engine.on_rejection(state.get("execution_mode", "advisory"))

        if rejection_stage == "awaiting_selection":
            _session_put(txn_id, {**state, "stage": "awaiting_selection"})
            return web.json_response({
                "run_id":         run_id,
                "stage":          "awaiting_selection",
                "transaction_id": txn_id,
                "request_id":     request_id,
                "offerings":      state.get("offerings", []),
                "message":        "Recommendation rejected. Please select a supplier from the list.",
            })

        async with aiohttp.ClientSession(
            headers={"Content-Type": "application/json"}
        ) as sess:
            await _persist_status(sess, request_id, "cancelled")
            await _persist_audit(
                sess, "override", "user_rejected_run",
                reasoning_payload={"run_id": run_id},
                request_id=request_id,
            )
        _session_put(txn_id, {**state, "stage": "rejected"})
        return web.json_response({"run_id": run_id, "stage": "rejected"})

    # ── Resolve chosen_item_id based on current stage ─────────────────────────
    stage      = state.get("stage", "")
    offerings  = state.get("offerings", [])

    if stage == "awaiting_selection":
        chosen_item_id = body.get("chosen_item_id")
        if not chosen_item_id:
            raise web.HTTPBadRequest(
                reason="chosen_item_id is required for awaiting_selection stage"
            )
    elif stage == "awaiting_approval":
        stored_decision = state.get("decision", {})
        chosen_item_id = (
            stored_decision.get("final_item_id") or body.get("chosen_item_id")
        )
        if not chosen_item_id:
            raise web.HTTPBadRequest(
                reason="No item to approve — decision.final_item_id missing from session"
            )
    else:
        raise web.HTTPConflict(
            reason=f"Run {run_id!r} is in stage {stage!r} and cannot be decided"
        )

    chosen = next((o for o in offerings if o["item_id"] == chosen_item_id), None)
    if chosen is None:
        raise web.HTTPUnprocessableEntity(
            reason=f"chosen_item_id {chosen_item_id!r} not in offerings"
        )

    # ── Pre-commit gate: PolicyEngine decides whether to commit or escalate ───
    # No business rules in this handler — only reads commit_decision.proceed.
    try:
        quantity_val = state.get("intent", {}).get("quantity", 1)
        order_total = (
            Decimal(str(chosen["price_value"])) * Decimal(str(quantity_val))
        )
    except Exception:
        order_total = Decimal("0")

    commit_decision = _policy_engine.evaluate_commit(
        order_total=order_total,
        approval_threshold=Decimal(str(state.get("approval_threshold") or 0)),
        erp_envelope=state.get("erp_policy"),
    )

    if not commit_decision.proceed:
        _pending_approvals[request_id] = {
            "run_id":           run_id,
            "request_id":       request_id,
            "transaction_id":   txn_id,
            "chosen_item_id":   chosen_item_id,
            "actor":            body.get("actor", {}),
            "amount_total":     float(order_total),
            "item_description": state.get("intent", {}).get("item", ""),
            "provider_name":    chosen.get("provider_name", ""),
            "created_at":       _now_iso(),
        }
        async with aiohttp.ClientSession(
            headers={"Content-Type": "application/json"}
        ) as sess:
            await _persist_status(sess, request_id, "pending_approval")
        _session_put(txn_id, {
            **state,
            "stage":           commit_decision.next_stage,
            "chosen_item_id":  chosen_item_id,
        })
        return web.json_response({
            "run_id":       run_id,
            "stage":        commit_decision.next_stage,
            "amount_total": float(order_total),
            "explanation":  commit_decision.explanation,
        }, status=202)

    # ── Execute Beckn commit ──────────────────────────────────────────────────
    # If the user negotiated a price before approving (HITL flow), apply it.
    negotiated_price_raw = body.get("negotiated_price")
    chosen_for_commit = chosen
    if negotiated_price_raw is not None:
        try:
            negotiated_price = float(negotiated_price_raw)
            if negotiated_price > 0:
                chosen_for_commit = {**chosen, "price_value": str(negotiated_price)}
                logger.info(
                    "[decide_run] using negotiated price %s for item=%s",
                    negotiated_price, chosen.get("item_id"),
                )
        except (TypeError, ValueError):
            pass  # malformed value — fall through to original price

    contract_id = str(uuid4())
    is_mock = False
    try:
        async with aiohttp.ClientSession(
            headers={"Content-Type": "application/json"}
        ) as sess:
            cr = await _execute_beckn_commit(
                sess,
                txn_id=txn_id,
                chosen=chosen_for_commit,
                intent=state.get("intent") or {},
                contract_id=contract_id,
            )
            await _persist_status(sess, request_id, "confirmed")
            await _persist_audit(
                sess, "confirm", f"decide_run order_confirmed: {cr['order_id']}",
                reasoning_payload={
                    "order_id":      cr["order_id"],
                    "run_id":        run_id,
                    "chosen_item_id": chosen_item_id,
                    "approver_id":   body.get("approver_id"),
                },
                request_id=request_id,
            )
            await _persist_order_record(
                sess,
                score_ids_map=state.get("score_ids_map", {}),
                offering_ids_map=state.get("offering_ids_map", {}),
                chosen_item_id=chosen_item_id,
                chosen=chosen_for_commit,
                quantity=quantity_val,
                bpp_uri=cr["bpp_uri"],
                beckn_confirm_ref=cr["order_id"],
                requester_id=state.get("requester_id"),
            )
    except Exception as exc:
        logger.warning("[decide_run] Beckn commit failed (%s) — mock fallback", exc)
        cr = {
            "order_id":       f"mock-run-{uuid4().hex[:8]}",
            "order_state":    "CREATED",
            "payment_terms":  {
                "type": "ON_FULFILLMENT", "collected_by": "BPP",
                "currency": chosen.get("price_currency", "INR"), "status": "NOT-PAID",
            },
            "bpp_id":         chosen["bpp_id"],
            "bpp_uri":        chosen["bpp_uri"],
            "messages":       [f"[mock] Beckn stack offline: {exc}"],
            "reasoning_steps": [],
        }
        is_mock = True

    _session_put(txn_id, {
        **state,
        "stage":          "confirmed",
        "chosen_item_id": chosen_item_id,
        "order_id":       cr["order_id"],
        "order_state":    cr["order_state"],
        "payment_terms":  cr["payment_terms"],
        "contract_id":    contract_id,
        "bpp_id":         cr["bpp_id"],
        "bpp_uri":        cr["bpp_uri"],
    })

    if ERP_SYNC_ENABLED and cr.get("order_id") and not is_mock:
        try:
            po_payload = build_normalized_po(
                state={**state, "transaction_id": txn_id},
                chosen=chosen,
                intent=state.get("intent") or {},
                order_id=cr["order_id"],
                contract_id=contract_id,
                payment_terms=cr["payment_terms"],
                fulfillment_eta=None,
                budget_hold_id=None,
                buyer=_build_buyer_dict(),
            )
            asyncio.create_task(_get_erp_client().enqueue_sync(po_payload))
        except Exception as exc:
            logger.warning("[decide_run/erp-sync] build failed txn=%s err=%s", txn_id, exc)

    return web.json_response({
        "run_id":          run_id,
        "transaction_id":  txn_id,
        "request_id":      request_id,
        "stage":           "confirmed",
        "order_id":        cr["order_id"],
        "order_state":     cr["order_state"],
        "payment_terms":   cr["payment_terms"],
        "contract_id":     contract_id,
        "bpp_id":          cr["bpp_id"],
        "bpp_uri":         cr["bpp_uri"],
        "reasoning_steps": cr.get("reasoning_steps", []),
        "messages":        cr.get("messages", []),
        "status":          "mock" if is_mock else "live",
    })


# ── App factory ───────────────────────────────────────────────────────────────


def create_app() -> web.Application:
    app = web.Application()
    app.on_startup.append(_on_startup_kafka)
    app.on_cleanup.append(_on_cleanup_kafka)
    app.router.add_get("/health",                          health)
    app.router.add_get("/analytics",                       analytics)
    # ── Orchestrated /run state machine (replaces legacy /run handler) ───────
    app.router.add_post("/run",                            run_procurement)
    app.router.add_get("/run/{run_id}",                    get_run)
    app.router.add_post("/run/{run_id}/decide",            decide_run)
    # ── Backward-compatible single-step endpoints ─────────────────────────────
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
    # Real-time tracking
    app.router.add_get("/ws/status/{txn_id}",              ws_status)
    app.router.add_post("/webhooks/seller/status",         seller_status_webhook)
    return app


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    port = int(os.getenv("PORT", "8004"))
    web.run_app(create_app(), host="0.0.0.0", port=port)
