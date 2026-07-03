"""instructor-patched AsyncOpenAI clients.

Two clients are maintained:
  _json_client  — instructor.Mode.JSON  for Stage 1 (intent) and Stage 2 (beckn extraction)
  _tools_client — instructor.Mode.TOOLS for Stage 3 MCP reasoning (tool-call format)

Both point to the local Ollama server — and ONLY to Ollama.

HARD ARCHITECTURAL LOCK: the intent parser is the system's data-ingestion door.
Its structured-extraction contract (Instructor/Pydantic) is validated against a
local model and MUST NEVER be routed through the Claude Code proxy (:8012). The
guard below refuses any proxy endpoint even if OLLAMA_URL is misconfigured, and
the API key is pinned to the Ollama sentinel (CLAUDE_PROXY_KEY is ignored).
"""
from __future__ import annotations

import instructor
from openai import AsyncOpenAI

from .config import OLLAMA_URL

_json_client: instructor.AsyncInstructor | None = None
_tools_client: instructor.AsyncInstructor | None = None

#: The Claude proxy port. The parser must never target it.
_FORBIDDEN_PROXY_PORT = "8012"


def _ollama_only(url: str) -> str:
    """Return ``url`` iff it is a local Ollama endpoint; else refuse hard.

    Belt-and-braces enforcement so a stray ``OLLAMA_URL=…:8012`` can never route
    the data-ingestion parser through the cognitive-layer Claude proxy.
    """
    if _FORBIDDEN_PROXY_PORT in url:
        raise RuntimeError(
            f"nl_intent_parser is Ollama-locked — refusing Claude-proxy endpoint {url!r}. "
            "Point OLLAMA_URL at a local Ollama server (…:11434/v1)."
        )
    return url


def get_json_client() -> instructor.AsyncInstructor:
    global _json_client
    if _json_client is None:
        _json_client = instructor.from_openai(
            AsyncOpenAI(base_url=_ollama_only(OLLAMA_URL), api_key="ollama"),
            mode=instructor.Mode.JSON,
        )
    return _json_client


def get_tools_client() -> instructor.AsyncInstructor:
    global _tools_client
    if _tools_client is None:
        _tools_client = instructor.from_openai(
            AsyncOpenAI(base_url=_ollama_only(OLLAMA_URL), api_key="ollama"),
            mode=instructor.Mode.TOOLS,
        )
    return _tools_client
