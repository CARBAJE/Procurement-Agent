"""instructor-patched AsyncOpenAI clients.

Two clients are maintained:
  _json_client  — instructor.Mode.JSON  for Stage 1 (intent) and Stage 2 (beckn extraction)
  _tools_client — instructor.Mode.TOOLS for Stage 3 MCP reasoning (tool-call format)

Both point to the local Ollama server.
"""
from __future__ import annotations

import instructor
from openai import AsyncOpenAI

from .config import OLLAMA_URL

_json_client: instructor.AsyncInstructor | None = None
_tools_client: instructor.AsyncInstructor | None = None


def get_json_client() -> instructor.AsyncInstructor:
    global _json_client
    if _json_client is None:
        _json_client = instructor.from_openai(
            AsyncOpenAI(base_url=OLLAMA_URL, api_key="ollama"),
            mode=instructor.Mode.JSON,
        )
    return _json_client


def get_tools_client() -> instructor.AsyncInstructor:
    global _tools_client
    if _tools_client is None:
        _tools_client = instructor.from_openai(
            AsyncOpenAI(base_url=OLLAMA_URL, api_key="ollama"),
            mode=instructor.Mode.TOOLS,
        )
    return _tools_client
