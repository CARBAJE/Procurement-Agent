"""MCP Sidecar — search_bpp_catalog tool over SSE transport.

Transport: MCP SSE (spec 2024-11-05) via mcp.server.fastmcp.FastMCP.
  GET  /sse        → SSE stream; first event is "endpoint" with POST URL
  POST /messages/  → JSON-RPC 2.0 tools/call dispatcher

Tool: search_bpp_catalog
  Validates arguments, probes the Beckn BAP Client (/discover), ranks
  results by semantic similarity to item_name, and returns a clean
  {"found", "items", "probe_latency_ms"} dict.

"Never throw" contract: all failures are returned as found=False.
Stateless: no caching.  Every call hits the BAP network.

Run:
    BAP_API_KEY=<key> python server.py
    BAP_API_KEY=<key> uvicorn server:app --host 0.0.0.0 --port 3000
"""
from __future__ import annotations

import logging
from typing import Optional

import uvicorn
from mcp.server.fastmcp import FastMCP

from bap_client import probe_bap_network
from config import settings
from ranking import rank_and_filter_items

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)

# ── MCP server ────────────────────────────────────────────────────────────────

mcp = FastMCP(
    "beckn-mcp-sidecar",
    instructions=(
        "Search the live Beckn ONIX network for BPP catalog entries matching "
        "a procurement item description. Returns ranked results with BPP identifiers."
    ),
)


# ── Tool ─────────────────────────────────────────────────────────────────────


@mcp.tool()
async def search_bpp_catalog(
    item_name: str,
    descriptions: list[str],
    domain: str,
    version: str,
    location: Optional[str] = None,
) -> dict:
    """Search the live ONIX Beckn network for a BPP catalog entry.

    Returns {"found": bool, "items": [...], "probe_latency_ms": int}.
    Never raises — all failures surface as found=False.
    """
    # Input validation — return immediately without hitting BAP
    if not item_name.strip():
        logger.warning("search_bpp_catalog called with blank item_name")
        return {"found": False, "items": [], "probe_latency_ms": 0}
    if not domain.strip():
        logger.warning("search_bpp_catalog called with blank domain")
        return {"found": False, "items": [], "probe_latency_ms": 0}
    if not version.strip():
        logger.warning("search_bpp_catalog called with blank version")
        return {"found": False, "items": [], "probe_latency_ms": 0}

    try:
        success, raw_items, latency_ms = await probe_bap_network(
            item_name=item_name,
            descriptions=descriptions,
            domain=domain,
            version=version,
            location=location,
        )

        if not success:
            return {"found": False, "items": [], "probe_latency_ms": latency_ms}

        filtered = await rank_and_filter_items(item_name, raw_items)

        return {
            "found": bool(filtered),
            "items": [
                {
                    "item_name": item["item_name"],
                    "bpp_id": item["bpp_id"],
                    "bpp_uri": item["bpp_uri"],
                }
                for item in filtered
            ],
            "probe_latency_ms": latency_ms,
        }

    except Exception as exc:
        # Last-resort catch — ensures the "never throw" contract is honoured
        # even if probe_bap_network or rank_and_filter_items have a bug.
        logger.error("Unhandled exception in search_bpp_catalog: %s", exc, exc_info=True)
        return {"found": False, "items": [], "probe_latency_ms": 0}


# ── ASGI app (for uvicorn server:app) ────────────────────────────────────────

app = mcp.sse_app()

# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logger.info(
        "Starting MCP Sidecar on :%d  BAP=%s  timeout=%.1fs  min_sim=%.2f",
        settings.port,
        settings.bap_client_url,
        settings.mcp_bap_timeout,
        settings.ranking_min_similarity,
    )
    uvicorn.run(app, host="0.0.0.0", port=settings.port, log_level="info")
