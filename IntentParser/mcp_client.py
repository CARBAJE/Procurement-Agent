"""MCP SSE client for the co-located search_bpp_catalog sidecar.

Uses the official `mcp` Python SDK to perform the mandatory MCP initialize
handshake before issuing a tools/call request, eliminating the
"Received request before initialization was complete" protocol error that
occurred with the previous raw-SSE / aiohttp implementation.

Protocol flow (per MCP SSE spec 2024-11-05):
  sse_client()     → opens SSE stream, negotiates endpoint URL
  session.initialize() → sends initialize / initialized handshake
  session.call_tool()  → sends tools/call, reads result
"""
from __future__ import annotations

import asyncio
import json
import logging
import time

from mcp.client.session import ClientSession
from mcp.client.sse import sse_client

from .config import BECKN_DOMAIN, BECKN_VERSION, MCP_PROBE_TIMEOUT, MCP_SSE_URL

logger = logging.getLogger(__name__)


class MCPSidecarClient:
    """Single-shot MCP tool caller over SSE transport.

    Each call opens a fresh SSE connection, completes the MCP initialize
    handshake, executes the tool, and closes the connection.  This is safe
    for the low-frequency probe pattern (P2 path, triggered only on CACHE_MISS).
    """

    def __init__(
        self,
        sse_url: str = MCP_SSE_URL,
        timeout: float = MCP_PROBE_TIMEOUT,
    ) -> None:
        self._sse_url = sse_url
        self._timeout = timeout

    async def call_tool(self, name: str, arguments: dict) -> dict:
        """Initialize an MCP session and call a tool; return the result dict.

        The entire connection + handshake + call is wrapped in
        asyncio.wait_for to enforce self._timeout as a hard ceiling.

        Raises:
            TimeoutError: if the operation exceeds self._timeout seconds.
            RuntimeError: for any other transport or protocol error.
        """
        async def _connect_and_call() -> dict:
            async with sse_client(self._sse_url) as streams:
                async with ClientSession(streams[0], streams[1]) as session:
                    await session.initialize()
                    logger.debug("MCP session initialized; calling tool %s", name)
                    result = await session.call_tool(name, arguments=arguments)
                    # FastMCP wraps dict return values as JSON text in content[0].text
                    if result.content and result.content[0].type == "text":
                        return json.loads(result.content[0].text)
                    return {}

        try:
            return await asyncio.wait_for(_connect_and_call(), timeout=self._timeout)
        except asyncio.TimeoutError:
            raise TimeoutError(
                f"MCP sidecar did not respond within {self._timeout}s "
                f"(tool={name}, url={self._sse_url})"
            )
        except Exception as exc:
            raise RuntimeError(str(exc)) from exc

    async def search_bpp_catalog(
        self,
        item_name: str,
        descriptions: list[str],
        location: str | None = None,
        domain: str = BECKN_DOMAIN,
        version: str = BECKN_VERSION,
    ) -> dict:
        """Call search_bpp_catalog and return the tool result dict.

        Returns: {"found": bool, "items": [...], "probe_latency_ms": int}
        """
        t0 = time.monotonic()
        arguments: dict = {
            "item_name": item_name,
            "descriptions": descriptions,
            "domain": domain,
            "version": version,
        }
        if location:
            arguments["location"] = location

        try:
            result = await self.call_tool("search_bpp_catalog", arguments)
        except (TimeoutError, RuntimeError) as exc:
            logger.warning("MCP search_bpp_catalog failed: %s", exc)
            return {"found": False, "items": [], "probe_latency_ms": 0}

        latency_ms = int((time.monotonic() - t0) * 1000)
        result.setdefault("probe_latency_ms", latency_ms)
        return result


# Module-level singleton — created lazily
_default_client: MCPSidecarClient | None = None


def get_mcp_client() -> MCPSidecarClient:
    global _default_client
    if _default_client is None:
        _default_client = MCPSidecarClient()
    return _default_client
