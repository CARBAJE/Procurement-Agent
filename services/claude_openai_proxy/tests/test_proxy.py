"""Functional integration tests for the Claude Code OpenAI proxy.

Drives the running proxy with the official ``openai`` client, exercising both
the synchronous (`stream=False`) and streaming (`stream=True`) paths. Skips
gracefully if the proxy isn't reachable so it never hard-fails in CI without a
live server + Claude Code auth.

Run (with the proxy already up on :8012):
    CLAUDE_PROXY_KEY=your-local-proxy-key \
      pytest services/claude_openai_proxy/tests/test_proxy.py -v -s
"""
from __future__ import annotations

import os

import httpx
import pytest
from openai import OpenAI

BASE_URL = os.getenv("PROXY_BASE_URL", "http://127.0.0.1:8012/v1")
API_KEY = os.getenv("CLAUDE_PROXY_KEY", "your-local-proxy-key")
MODEL = os.getenv("PROXY_TEST_MODEL", "gpt-4o-mini")  # → mapped to haiku


def _proxy_up() -> bool:
    try:
        root = BASE_URL.rsplit("/v1", 1)[0]
        return httpx.get(f"{root}/healthz", timeout=3).status_code == 200
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _proxy_up(), reason="proxy not running on :8012")


@pytest.fixture(scope="module")
def client() -> OpenAI:
    return OpenAI(base_url=BASE_URL, api_key=API_KEY, timeout=180)


def test_models_endpoint(client: OpenAI) -> None:
    models = client.models.list()
    ids = {m.id for m in models.data}
    assert "gpt-4o-mini" in ids


def test_chat_completion_sync(client: OpenAI) -> None:
    resp = client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "user", "content": "Reply with exactly one word: PONG"}],
        stream=False,
    )
    assert resp.object == "chat.completion"
    assert resp.choices, "no choices returned"
    content = resp.choices[0].message.content or ""
    assert content.strip(), "empty assistant content"
    assert resp.choices[0].finish_reason == "stop"


def test_chat_completion_stream(client: OpenAI) -> None:
    stream = client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "user", "content": "Count from 1 to 3, comma separated."}],
        stream=True,
    )
    chunks = 0
    collected = ""
    for chunk in stream:
        chunks += 1
        delta = chunk.choices[0].delta.content if chunk.choices else None
        if delta:
            collected += delta
    assert chunks > 0, "no SSE chunks received"
    assert collected.strip(), "no streamed content"


def test_unauthorized_rejected() -> None:
    """A wrong Bearer key must be rejected (only meaningful when auth is on)."""
    bad = OpenAI(base_url=BASE_URL, api_key="definitely-wrong-key", timeout=10)
    try:
        bad.chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": "hi"}],
        )
    except Exception as exc:  # openai.AuthenticationError (401) when key is set
        assert "401" in str(exc) or "invalid" in str(exc).lower()
    else:
        pytest.skip("auth disabled (no CLAUDE_PROXY_KEY on the server)")
