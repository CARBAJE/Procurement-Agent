"""Async HTTP client for the Beckn BAP Client service — Redis Pub/Sub edition.

Beckn v2 discovery is inherently asynchronous: the BAP Client fires POST /discover
to the ONIX adapter, which routes to BPPs; results arrive later at the BAP Client's
/on_discover webhook.  A naive "wait for the HTTP response" design deadlocks under
load because the HTTP connection stays open while the callback round-trip completes.

Decoupling via Redis Pub/Sub:
  1. probe_bap_network generates a unique transaction_id (UUIDv4) and subscribes
     to Redis channel ``beckn_results:{transaction_id}`` *before* making the HTTP
     request — no subscribe/publish race condition is possible.
  2. The HTTP POST /discover is fired as a concurrent asyncio task.
  3. handler.py's /on_discover route publishes the full on_discover callback
     payload to that channel as soon as ONIX delivers it.
  4. probe_bap_network reads from the channel (≤ REDIS_RESULT_TIMEOUT seconds),
     extracts items, and returns.  On timeout it returns an empty result.

"Never Throw" contract is preserved: all exceptions are caught and surfaced
as (False, [], elapsed_ms).  All Redis connections use async context managers.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import uuid
from typing import Optional

import httpx
import redis.asyncio as aioredis

from config import settings

logger = logging.getLogger(__name__)

REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379")
REDIS_RESULT_TIMEOUT: float = float(os.getenv("REDIS_RESULT_TIMEOUT", "15"))


# ── Payload builder ───────────────────────────────────────────────────────────


def _build_payload(
    item_name: str,
    descriptions: list[str],
    domain: str,
    version: str,
    location: Optional[str],
    transaction_id: str,
) -> dict:
    # Matches BecknIntent (shared.models) field-for-field, plus transaction_id
    # at the top level so handler.py can propagate it into the Beckn context.
    # quantity=1: sensible default for catalog discovery.
    # delivery_timeline=None: Optional[int] with a >0 validator — 0 would raise.
    # budget_constraints=None: not applicable for a catalog search probe.
    # domain / version are not BecknIntent fields; kept in signature for call-site
    # symmetry with the sidecar's search_bpp_catalog tool arguments.
    return {
        "item": item_name,
        "descriptions": descriptions,
        "quantity": 1,
        "location_coordinates": location,
        "delivery_timeline": None,
        "budget_constraints": None,
        "transaction_id": transaction_id,   # propagated into Beckn context by handler.py
    }


# ── Item extractor — on_discover callback payload format ─────────────────────


def _extract_items_from_callback(data: dict) -> list[dict]:
    """Pull (item_name, bpp_id, bpp_uri) triples from an on_discover callback.

    The Redis message is the raw Beckn on_discover webhook payload published
    by handler.py's /on_discover route:

        {
          "context": {"transactionId": "...", "bppId": "...", "bppUri": "..."},
          "message": {
            "catalogs": [
              {
                "bppId": "...", "bppUri": "...",
                "resources": [{"descriptor": {"name": "..."}, ...}]
              }
            ]
          }
        }

    Falls back to the legacy ``message.catalog.items[]`` shape for
    compatibility with non-standard BPP implementations.  Returns an empty
    list rather than raising on any parse error.
    """
    items: list[dict] = []
    try:
        ctx = data.get("context", {})
        message = data.get("message", {})

        # Beckn v2 on_discover: message.catalogs[]
        catalogs: list[dict] = message.get("catalogs", [])
        # Legacy fallback: message.catalog{}
        if not catalogs and message.get("catalog"):
            catalogs = [message["catalog"]]

        for catalog in catalogs:
            bpp_id: str = (
                catalog.get("bppId")
                or catalog.get("bpp_id")
                or ctx.get("bppId", "")
            )
            bpp_uri: str = (
                catalog.get("bppUri")
                or catalog.get("bpp_uri")
                or ctx.get("bppUri", "")
            )
            # Beckn v2 uses "resources"; legacy adapters may use "items"
            resources: list[dict] = catalog.get("resources") or catalog.get("items") or []
            for resource in resources:
                name: str = resource.get("descriptor", {}).get("name", "")
                if name:
                    items.append({"item_name": name, "bpp_id": bpp_id, "bpp_uri": bpp_uri})
    except Exception as exc:
        logger.warning("Failed to parse on_discover callback: %s", exc)
    return items


# ── Main probe function ───────────────────────────────────────────────────────


async def probe_bap_network(
    item_name: str,
    descriptions: list[str],
    domain: str,
    version: str,
    location: Optional[str] = None,
) -> tuple[bool, list[dict], int]:
    """Probe the ONIX network via Redis Pub/Sub and return (success, raw_items, latency_ms).

    Flow:
      1. Generate a unique transaction_id (UUIDv4).
      2. Subscribe to Redis channel ``beckn_results:{transaction_id}`` *before*
         firing the HTTP request — eliminates the subscribe/publish race.
      3. Fire POST /discover as a concurrent asyncio task.
      4. Await the Redis channel for up to REDIS_RESULT_TIMEOUT seconds.
      5. Parse on_discover callback items from the Redis message.
      6. Cancel the HTTP task (result already in Redis) and return.

    On any failure — Redis unreachable, BAP timeout, parse error — returns
    (False, [], elapsed_ms) without raising.
    """
    transaction_id = str(uuid.uuid4())
    channel = f"beckn_results:{transaction_id}"
    payload = _build_payload(item_name, descriptions, domain, version, location, transaction_id)
    headers = {
        "Authorization": f"Bearer {settings.bap_api_key}",
        "Content-Type": "application/json",
    }
    start = time.monotonic()

    try:
        async with aioredis.from_url(REDIS_URL) as r:
            async with r.pubsub() as pubsub:
                await pubsub.subscribe(channel)
                logger.debug(
                    "Subscribed to Redis channel %s (item=%s domain=%s)",
                    channel, item_name, domain,
                )

                # Fire the HTTP request concurrently so the event loop can
                # process the incoming Redis message while the BAP Client runs.
                async def _fire_http() -> None:
                    async with httpx.AsyncClient(timeout=settings.mcp_bap_timeout) as client:
                        try:
                            resp = await client.post(
                                f"{settings.bap_client_url}/discover",
                                json=payload,
                                headers=headers,
                            )
                            resp.raise_for_status()
                            logger.debug(
                                "BAP /discover accepted (txn=%s HTTP=%d)",
                                transaction_id, resp.status_code,
                            )
                        except httpx.TimeoutException:
                            logger.warning(
                                "BAP Client timed out (txn=%s limit=%.1fs)",
                                transaction_id, settings.mcp_bap_timeout,
                            )
                        except Exception as exc:
                            logger.warning(
                                "BAP /discover failed (txn=%s): %s",
                                transaction_id, exc,
                            )

                http_task = asyncio.create_task(_fire_http())

                async def _wait_for_redis_message() -> dict:
                    """Block on pubsub.listen() until a 'message' type event arrives."""
                    async for message in pubsub.listen():
                        if message["type"] == "message":
                            return json.loads(message["data"])
                    return {}  # unreachable; satisfies type checker

                try:
                    callback_payload = await asyncio.wait_for(
                        _wait_for_redis_message(),
                        timeout=REDIS_RESULT_TIMEOUT,
                    )
                except asyncio.TimeoutError:
                    latency_ms = int((time.monotonic() - start) * 1000)
                    logger.warning(
                        "Redis wait timed out after %dms (txn=%s limit=%.1fs)",
                        latency_ms, transaction_id, REDIS_RESULT_TIMEOUT,
                    )
                    return False, [], latency_ms
                finally:
                    # Always cancel the HTTP task — either we got the Redis result
                    # or we timed out; either way the task is no longer needed.
                    if not http_task.done():
                        http_task.cancel()
                        try:
                            await http_task
                        except (asyncio.CancelledError, Exception):
                            pass

                items = _extract_items_from_callback(callback_payload)
                latency_ms = int((time.monotonic() - start) * 1000)
                logger.debug(
                    "BAP probe: %d items in %dms (item=%s domain=%s txn=%s)",
                    len(items), latency_ms, item_name, domain, transaction_id,
                )
                return bool(items), items, latency_ms

    except Exception as exc:
        latency_ms = int((time.monotonic() - start) * 1000)
        logger.error("Unexpected error probing BAP network: %s", exc)
        return False, [], latency_ms
