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

import json
import logging
import os
import time
from datetime import datetime, timezone
from uuid import uuid4

import aiohttp
from aiohttp import web

logger = logging.getLogger(__name__)

# ── Service URLs (set via env vars in docker-compose) ─────────────────────────

INTENTION_PARSER_URL     = os.getenv("INTENTION_PARSER_URL",     "http://localhost:8001")
BECKN_BAP_URL            = os.getenv("BECKN_BAP_URL",            "http://localhost:8002")
COMPARATIVE_SCORING_URL  = os.getenv("COMPARATIVE_SCORING_URL",  "http://localhost:8003")

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


async def run_pipeline_from_intent(beckn_intent: dict) -> dict:
    """Execute Steps 2→3→4 of the state machine with a pre-parsed BecknIntent.

    Used by POST /discover (frontend-compatible endpoint) when the NL parse
    step has already happened and the user has confirmed the intent preview.

    Returns the same shape as run_pipeline() but without parse_result.
    """
    messages: list[str] = []

    async with aiohttp.ClientSession(
        headers={"Content-Type": "application/json"}
    ) as session:

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
            "transaction_id": transaction_id,
            "offerings":      offerings,
            "selected":       selected,
            "messages":       messages,
            "status":         "live",
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

        # ── Step 1: Intention Parser Lambda ──────────────────────────────────
        logger.info("Step 1 — Intention Parser")
        parse_result = await _post(
            session, f"{INTENTION_PARSER_URL}/parse", {"query": query}
        )
        messages.append(
            f"[intention-parser] intent={parse_result.get('intent')} "
            f"confidence={parse_result.get('confidence')} "
            f"routed_to={parse_result.get('routed_to')}"
        )

        if parse_result.get("intent") != "procurement":
            return {
                "error": f"Query not recognised as procurement: {query!r}",
                "messages": messages,
                "parse_result": parse_result,
            }

        beckn_intent = parse_result.get("beckn_intent")
        if not beckn_intent:
            return {
                "error": "Intent parser returned no beckn_intent",
                "messages": messages,
                "parse_result": parse_result,
            }

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
            "transaction_id": transaction_id,
            "offerings":      offerings,
            "selected":       selected,
            "messages":       messages,
            "parse_result":   parse_result,
            "discover_result": discover_result,
            "score_result":   score_result,
            "select_result":  select_result,
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
        raise web.HTTPBadGateway(reason=f"Intention parser unreachable: {exc}")
    except Exception as exc:
        logger.error("[parse proxy] Error: %s", exc)
        raise web.HTTPInternalServerError(reason=f"Parse failed: {exc}")


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

    if not body.get("item"):
        raise web.HTTPBadRequest(reason="item is required in BecknIntent body")

    try:
        async with aiohttp.ClientSession(
            headers={"Content-Type": "application/json"}
        ) as session:

            # Step 2: discover
            discover_result = await _post(session, f"{BECKN_BAP_URL}/discover", body)
            transaction_id = discover_result.get("transaction_id") or str(uuid4())
            offerings: list[dict] = discover_result.get("offerings", [])

            if not offerings:
                raise ValueError("No offerings returned from discovery")

            # Step 3: score (rank-only, no select)
            score_result = await _post(
                session, f"{COMPARATIVE_SCORING_URL}/score", {"offerings": offerings}
            )
            selected: dict | None = score_result.get("selected")

        recommended_item_id = selected["item_id"] if selected else None
        messages = [
            f"[discover] txn={transaction_id} found {len(offerings)} offering(s)",
            f"[rank_and_select] recommended {selected['provider_name']!r} ₹{selected['price_value']}"
            if selected else "[rank_and_select] no offering selected",
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
        if selected:
            prices = [float(o["price_value"]) for o in offerings]
            prices_sorted = sorted(prices)
            savings = f"{prices_sorted[1] - prices_sorted[0]:.2f}" if len(prices_sorted) > 1 else None
            reasoning_steps.append({
                "node": "rank_and_select",
                "role": "reason",
                "summary": f"Recommended {selected['provider_name']} — cheapest of {len(offerings)}",
                "details": {
                    "strategy": "price_only",
                    "recommended_item_id": selected["item_id"],
                    "recommended_provider": selected["provider_name"],
                    "recommended_price": selected["price_value"],
                    "savings_vs_next_cheapest": savings,
                    "offering_count": len(offerings),
                },
                "timestamp": _now_iso(),
            })
        else:
            reasoning_steps.append({
                "node": "rank_and_select",
                "role": "reason",
                "summary": "No offerings to rank",
                "details": {},
                "timestamp": _now_iso(),
            })

        _session_put(transaction_id, {
            "transaction_id": transaction_id,
            "offerings": offerings,
            "selected": selected,
            "intent": body,
        })

        return web.json_response({
            "transaction_id":      transaction_id,
            "offerings":           offerings,
            "recommended_item_id": recommended_item_id,
            "scoring":             _build_scoring(offerings, recommended_item_id),
            "reasoning_steps":     reasoning_steps,
            "messages":            messages,
            "status":              "live",
        })

    except Exception as exc:
        logger.warning("compare live path failed (%s) — returning mock", exc)
        return _mock_compare_response()


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
            "order_id":      order_id,
            "order_state":   order_state,
            "payment_terms": payment_terms,
            "bpp_id":        bpp_id,
            "bpp_uri":       bpp_uri,
            "items":         items,
            "contract_id":   contract_id,
        })

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

    if not bpp_id or not bpp_uri:
        return web.json_response({
            "transaction_id": txn_id,
            "order_id":       order_id,
            "state":          last_state,
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

        return web.json_response({
            "transaction_id": txn_id,
            "order_id":       order_id,
            "state":          result.get("state", last_state),
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
            "fulfillment_eta": None,
            "tracking_url":   None,
            "observed_at":    _now_iso(),
            "status":         "mock",
        })


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
        raise web.HTTPBadGateway(reason=f"Upstream service unavailable: {exc}")
    except Exception as exc:
        logger.error("Pipeline error: %s", exc)
        raise web.HTTPInternalServerError(reason=f"Pipeline failed: {exc}")

    return web.json_response(result)


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
        raise web.HTTPBadGateway(reason=f"Upstream service unavailable: {exc}")
    except Exception as exc:
        logger.error("Pipeline error: %s", exc)
        raise web.HTTPInternalServerError(reason=f"Pipeline failed: {exc}")

    return web.json_response(result)


# ── App factory ───────────────────────────────────────────────────────────────


def create_app() -> web.Application:
    app = web.Application()
    app.router.add_get("/health",                          health)
    app.router.add_post("/run",                            run)
    app.router.add_post("/parse",                          parse)
    app.router.add_post("/discover",                       discover)
    app.router.add_post("/compare",                        compare)
    app.router.add_post("/commit",                         commit)
    app.router.add_get("/status/{txn_id}/{order_id}",      order_status)
    return app


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    port = int(os.getenv("PORT", "8004"))
    web.run_app(create_app(), host="0.0.0.0", port=port)
