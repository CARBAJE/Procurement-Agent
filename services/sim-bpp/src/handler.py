"""Simulated unified Beckn v2.0.0 BPP.

Replaces the transaction-only `sandbox-2.0` image with a single service that
answers the FULL Beckn lifecycle — discovery AND transactions — while sitting
behind the onix-bpp adapter. Every response travels the real signed +
schema-validated path:

    BAP → onix-bap (sign + validate) → onix-bpp → sim-bpp /api/webhook/{action}
        → sim-bpp ACK, then async POST onix-bpp/bpp/caller/on_{action}
        → onix-bpp (sign + validate) → onix-bap → BAP /bap/receiver

This is the whole point of the service: if the BAP works against this local
simulation, it works against a real Beckn network — the only difference is
routing (direct URL → DeDi registry lookup) and identity/keys.

Discovery is query-driven: the incoming `intent.textSearch` filters a catalog
loaded from CATALOG_PATH (bind-mounted JSON, re-read per request so edits apply
without a restart). Transactional callbacks echo the inbound Contract — which
already passed onix schema validation — and augment it per action.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from datetime import datetime, timezone
from uuid import uuid4

import aiohttp
from aiohttp import web

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("sim-bpp")

# ── Config (env-driven) ──────────────────────────────────────────────────────
PORT = int(os.getenv("PORT", "3002"))
# onix-bpp caller base — we append /on_{action}. ONIX signs + routes the callback.
ONIX_BPP_CALLER = os.getenv("ONIX_BPP_CALLER", "http://onix-bpp:8082/bpp/caller").rstrip("/")
BPP_ID = os.getenv("BPP_ID", "bpp.example.com")
BPP_URI = os.getenv("BPP_URI", "http://onix-bpp:8082/bpp/receiver")
CATALOG_PATH = os.getenv("CATALOG_PATH", "/app/catalog.json")

# Actions we accept inbound and answer with an on_{action} callback.
TRANSACTIONAL = {"select", "init", "confirm", "status", "track", "update", "cancel", "rate", "support"}


# ── Helpers ──────────────────────────────────────────────────────────────────


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _resp_context(ctx: dict, on_action: str) -> dict:
    """Echo the inbound context, flip to the on_ action, stamp BPP identity.

    Echoing keeps networkId/version/transactionId/messageId intact so onix-bpp's
    router (which keys on networkId) and the BAP's CallbackCollector (which keys
    on transactionId) both resolve correctly.
    """
    return {
        **ctx,
        "action": on_action,
        "bppId": BPP_ID,
        "bppUri": BPP_URI,
        "timestamp": _now(),
    }


def load_catalog() -> list[dict]:
    """Read the catalog seed each call so volume edits apply without a restart."""
    try:
        with open(CATALOG_PATH, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception as exc:  # never throw — discovery must stay resilient
        logger.warning("catalog load failed (%s): %s", CATALOG_PATH, exc)
        return []


# ── Discover ─────────────────────────────────────────────────────────────────


_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _tokenize(text: str) -> set[str]:
    """Lowercase word/number tokens. Token-based (not substring) matching avoids
    false positives like the query token "white" matching "whiteboard"."""
    return set(_TOKEN_RE.findall(text.lower()))


def _item_tokens(item: dict) -> set[str]:
    """Searchable tokens for an item: its name + keywords (NOT the provider name).

    Excluding the provider name avoids over-matching — e.g. "paper" pulling every
    item from a provider called "PaperDirect".
    """
    text = item.get("descriptor", {}).get("name", "") + " " + " ".join(item.get("keywords", []))
    return _tokenize(text)


def _wire_resource(item: dict, provider: dict) -> dict:
    """Project an internal catalog item to a Beckn v2 flat-resource wire object.

    Drops internal-only fields (e.g. `keywords`). Each resource carries its own
    provider + rating — that is what the BAP catalog-normalizer reads from the
    BECKN_V2_FLAT_RESOURCES shape (resource.provider / resource.rating).
    """
    res: dict = {
        "id": item["id"],
        "descriptor": item.get("descriptor", {}),
        "provider": {"id": provider["id"], "descriptor": provider.get("descriptor", {})},
        "price": item.get("price", {}),
    }
    if provider.get("rating") is not None:
        try:
            res["rating"] = {"ratingValue": float(provider["rating"])}
        except (TypeError, ValueError):
            pass
    # Stock → Beckn v2 quantity.available.count
    if item.get("stock") is not None:
        res["quantity"] = {"available": {"count": item["stock"]}}
    # Specs → Beckn v2 tags[] (each spec becomes a tag value)
    specs = item.get("specs") or []
    if specs:
        res["tags"] = [{"descriptor": {"name": "specification"}, "value": s} for s in specs]
    # NOTE: no fulfillment/ETA here on purpose — a real Beckn network resolves
    # delivery ETA at /select or /init, not in the discovery catalog.
    return res


def build_on_discover(ctx: dict, msg: dict) -> dict:
    """Filter the catalog by intent.textSearch and emit a Beckn v2 on_discover.

    Wire shape is `message.catalogs[]` (plural) — one catalog entry per matching
    provider — each `{id, descriptor, provider, resources[]}` in the
    BECKN_V2_FLAT_RESOURCES shape the onix v2.0.0 validator accepts and the BAP
    catalog-normalizer maps. bppId/bppUri travel in the context so subsequent
    select/init/confirm route back through onix-bpp consistently.
    """
    text = (msg.get("intent", {}) or {}).get("textSearch", "") or ""
    catalog = load_catalog()

    # Token sets per item, and the global catalog vocabulary.
    item_tokens = [(prov, it, _item_tokens(it)) for prov in catalog for it in prov.get("items", [])]
    vocab: set[str] = set().union(*(toks for _, _, toks in item_tokens)) if item_tokens else set()

    # Keep only query tokens that exist in the catalog vocabulary, so
    # filler/location/time words (e.g. "Mumbai", "white", "days") don't void the
    # search. An item then matches only if it contains ALL of those tokens (AND)
    # — precise relevance instead of any-token noise.
    query_tokens = _tokenize(text) & vocab

    catalogs: list[dict] = []
    for prov in catalog:
        resources = [
            _wire_resource(it, prov)
            for it in prov.get("items", [])
            if query_tokens <= _item_tokens(it)  # empty query → subset of everything → all
        ]
        if resources:
            prov_descriptor = prov.get("descriptor", {})
            catalogs.append(
                {
                    "id": f"catalog-{prov['id']}",
                    "descriptor": {"name": f"{prov_descriptor.get('name', prov['id'])} Catalog"},
                    "provider": {"id": prov["id"], "descriptor": prov_descriptor},
                    "resources": resources,
                }
            )

    logger.info("discover textSearch=%r → %d catalogs", text, len(catalogs))
    return {"context": _resp_context(ctx, "on_discover"), "message": {"catalogs": catalogs}}


# ── Transactional callbacks ──────────────────────────────────────────────────


def _echo_contract(msg: dict, *, status_code: str | None = None, settlement_status: str | None = None) -> dict:
    """Echo the inbound Contract (already schema-validated) and augment it.

    Echoing guarantees the response Contract is spec-valid; we only add the
    keys each on_ action needs (status, settlements) — all allowed Contract
    properties, so additionalProperties:false stays satisfied.
    """
    contract = dict(msg.get("contract") or {})
    contract.setdefault("id", f"contract-{uuid4().hex[:8]}")
    contract.setdefault("commitments", [])  # required wherever a Contract appears
    if status_code:
        contract["status"] = {"code": status_code}
    if settlement_status and "settlements" not in contract:
        # Settlement.status enum: DRAFT | COMMITTED | COMPLETE
        contract["settlements"] = [
            {
                "id": f"settlement-{uuid4().hex[:8]}",
                "type": "ON_FULFILLMENT",
                "collectedBy": "BPP",
                "currency": "INR",
                "status": settlement_status,
            }
        ]
    return contract


# Per action: (Contract.status.code, settlements[].status)
# Contract.status.code enum: DRAFT | ACTIVE | CANCELLED | COMPLETE  (never "CONFIRMED")
# Settlement.status enum:    DRAFT | COMMITTED | COMPLETE
_TXN_STATUS = {
    "select": ("DRAFT", None),
    "init": (None, "DRAFT"),
    "confirm": ("ACTIVE", "COMMITTED"),
    "status": ("ACTIVE", None),
    "track": ("ACTIVE", None),
    "update": ("ACTIVE", None),
    "cancel": ("CANCELLED", None),
    "rate": (None, None),
    "support": (None, None),
}


def build_transactional(action: str, ctx: dict, msg: dict) -> dict:
    status_code, settlement_status = _TXN_STATUS[action]
    contract = _echo_contract(msg, status_code=status_code, settlement_status=settlement_status)
    return {"context": _resp_context(ctx, f"on_{action}"), "message": {"contract": contract}}


# ── HTTP layer ───────────────────────────────────────────────────────────────


async def _emit_callback(action: str, ctx: dict, msg: dict) -> None:
    """Build the on_{action} body and POST it to onix-bpp's caller (signs + routes).

    Fired via asyncio.create_task so the inbound ACK is never blocked (ADR-0001).
    """
    await asyncio.sleep(0.1)  # let the ACK flush first
    if action == "discover":
        body = build_on_discover(ctx, msg)
    else:
        body = build_transactional(action, ctx, msg)

    url = f"{ONIX_BPP_CALLER}/on_{action}"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=body, headers={"Content-Type": "application/json"}) as resp:
                logger.info("on_%s -> onix-bpp HTTP %d", action, resp.status)
    except Exception as exc:
        logger.error("failed to send on_%s to %s: %s", action, url, exc)


async def webhook(request: web.Request) -> web.Response:
    """POST /api/webhook/{action} — inbound Beckn action from onix-bpp."""
    action = request.match_info["action"]
    if action != "discover" and action not in TRANSACTIONAL:
        return web.json_response({"message": {"ack": {"status": "NACK"}}}, status=404)

    try:
        payload = await request.json()
    except json.JSONDecodeError:
        raise web.HTTPBadRequest(reason="Invalid JSON")

    ctx = payload.get("context", {}) or {}
    msg = payload.get("message", {}) or {}
    logger.info("inbound %s | txn=%s", action, ctx.get("transactionId"))

    asyncio.create_task(_emit_callback(action, ctx, msg))
    return web.json_response({"message": {"ack": {"status": "ACK"}}})


async def health(_: web.Request) -> web.Response:
    return web.json_response({"status": "ok", "service": "sim-bpp", "bpp_id": BPP_ID})


def create_app() -> web.Application:
    app = web.Application()
    app.router.add_get("/api/health", health)
    app.router.add_post("/api/webhook/{action}", webhook)
    return app


if __name__ == "__main__":
    logger.info("sim-bpp starting on :%d | onix-bpp caller=%s | catalog=%s", PORT, ONIX_BPP_CALLER, CATALOG_PATH)
    web.run_app(create_app(), host="0.0.0.0", port=PORT)
