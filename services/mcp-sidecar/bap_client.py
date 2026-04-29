"""Async HTTP client for the Beckn BAP Client service.

Constructs a POST /discover payload that matches the BAP Client's internal
BecknIntent schema (shared.models.BecknIntent) — not a raw Beckn protocol
envelope.  Returns a clean (success, items, latency_ms) tuple.  All
transport-level exceptions are caught here so callers never need to handle
httpx errors.
"""
from __future__ import annotations

import logging
import time
from typing import Optional

import httpx

from config import settings

logger = logging.getLogger(__name__)


def _build_payload(
    item_name: str,
    descriptions: list[str],
    domain: str,
    version: str,
    location: Optional[str],
) -> dict:
    # Matches BecknIntent (shared.models) field-for-field.
    # quantity=1: sensible default for catalog discovery (no specific quantity needed).
    # delivery_timeline=None: Optional[int] with a >0 validator — 0 would raise;
    #   discovery does not constrain delivery window.
    # budget_constraints=None: not applicable for a catalog search probe.
    # domain / version are not part of BecknIntent; they remain unused here but
    #   are kept in the signature to preserve the probe_bap_network call site.
    return {
        "item": item_name,
        "descriptions": descriptions,
        "quantity": 1,
        "location_coordinates": location,
        "delivery_timeline": None,
        "budget_constraints": None,
    }


def _extract_items(data: dict) -> list[dict]:
    """Pull (item_name, bpp_id, bpp_uri) triples from an ONIX aggregated response.

    The BAP Client is responsible for populating bpp_id / bpp_uri in the context
    block of each per-BPP response.  If the response structure differs, an empty
    list is returned rather than crashing.
    """
    items: list[dict] = []
    try:
        catalog = data.get("catalog", {})
        raw_items = catalog.get("items", [])
        bpp_id: str = data.get("context", {}).get("bpp_id", "")
        bpp_uri: str = data.get("context", {}).get("bpp_uri", "")
        for raw in raw_items:
            name: str = raw.get("descriptor", {}).get("name", "")
            if name:
                items.append({"item_name": name, "bpp_id": bpp_id, "bpp_uri": bpp_uri})
    except Exception as exc:
        logger.warning("Failed to parse ONIX response body: %s", exc)
    return items


async def probe_bap_network(
    item_name: str,
    descriptions: list[str],
    domain: str,
    version: str,
    location: Optional[str] = None,
) -> tuple[bool, list[dict], int]:
    """POST to BAP Client /discover and return (success, raw_items, latency_ms).

    The timeout is enforced by httpx.AsyncClient (settings.mcp_bap_timeout seconds).
    All exceptions are caught and returned as (False, [], elapsed_ms).
    """
    payload = _build_payload(item_name, descriptions, domain, version, location)
    headers = {
        "Authorization": f"Bearer {settings.bap_api_key}",
        "Content-Type": "application/json",
    }
    start = time.monotonic()

    try:
        async with httpx.AsyncClient(timeout=settings.mcp_bap_timeout) as client:
            resp = await client.post(
                f"{settings.bap_client_url}/discover",
                json=payload,
                headers=headers,
            )
            resp.raise_for_status()
            items = _extract_items(resp.json())
            latency_ms = int((time.monotonic() - start) * 1000)
            logger.debug(
                "BAP probe: %d items in %dms (item=%s domain=%s)",
                len(items), latency_ms, item_name, domain,
            )
            return bool(items), items, latency_ms

    except httpx.TimeoutException:
        latency_ms = int((time.monotonic() - start) * 1000)
        logger.warning(
            "BAP Client timed out after %dms (limit=%.1fs)",
            latency_ms, settings.mcp_bap_timeout,
        )
        return False, [], latency_ms

    except httpx.RequestError as exc:
        latency_ms = int((time.monotonic() - start) * 1000)
        logger.warning("BAP Client unreachable: %s", exc)
        return False, [], latency_ms

    except Exception as exc:
        latency_ms = int((time.monotonic() - start) * 1000)
        logger.error("Unexpected error probing BAP network: %s", exc)
        return False, [], latency_ms
