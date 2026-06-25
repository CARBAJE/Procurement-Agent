"""Protocol adapter: OpenAI Chat Completions ⇄ Claude Code stream-json.

Stateless: every request serializes its full ``messages[]`` into one prompt
(system → ``--system-prompt``; the rest → a labeled transcript on stdin).

The Claude stream-json schema is parsed *defensively* — we tolerate both
incremental ``content_block_delta`` text and cumulative ``assistant``/``result``
snapshots, reconciling them into a single growing text and emitting only the
newly-added suffix as each OpenAI chunk.
"""
from __future__ import annotations

import json
import logging
from typing import Any, AsyncGenerator, Optional

from .cli_runner import run_claude_stream
from .config import CONFIG
from .models import (
    ChatCompletion,
    ChatCompletionChunk,
    ChatCompletionRequest,
    Choice,
    ChunkChoice,
    Delta,
    ResponseMessage,
    Usage,
    _rand_id,
)

logger = logging.getLogger("claude_proxy.adapter")

_ROLE_LABEL = {"user": "Human", "assistant": "Assistant", "tool": "Tool"}


def _content_to_text(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):  # OpenAI content parts
        out = []
        for part in content:
            if isinstance(part, dict):
                out.append(part.get("text") or part.get("content") or "")
            else:
                out.append(str(part))
        return "".join(out)
    return str(content)


def serialize_messages(req: ChatCompletionRequest) -> tuple[str, Optional[str]]:
    """→ (prompt for stdin, system_prompt or None)."""
    system_parts = [
        _content_to_text(m.content) for m in req.messages if m.role == "system"
    ]
    system_prompt = "\n\n".join(p for p in system_parts if p).strip() or None

    convo = [m for m in req.messages if m.role != "system"]
    if len(convo) == 1 and convo[0].role == "user":
        prompt = _content_to_text(convo[0].content)
    else:
        lines = []
        for m in convo:
            label = _ROLE_LABEL.get(m.role, m.role.capitalize())
            lines.append(f"{label}: {_content_to_text(m.content)}")
        prompt = "\n\n".join(lines)
    return prompt, system_prompt


def _event_text(obj: dict) -> tuple[str, bool, Optional[dict]]:
    """Return (text, is_snapshot, usage).

    is_snapshot=True → cumulative full text (assistant/result); False → an
    incremental delta to append. usage is captured from the terminal result.
    """
    t = obj.get("type")
    if t == "stream_event":
        ev = obj.get("event") or {}
        if ev.get("type") == "content_block_delta":
            d = ev.get("delta") or {}
            if d.get("type") in ("text_delta", "text"):
                return (d.get("text", "") or "", False, None)
        return ("", False, None)
    if t == "assistant":
        msg = obj.get("message") or {}
        parts = msg.get("content") or []
        txt = "".join(
            p.get("text", "")
            for p in parts
            if isinstance(p, dict) and p.get("type") == "text"
        )
        return (txt, True, None)
    if t == "result":
        return (obj.get("result", "") or "", True, obj.get("usage") or {})
    return ("", False, None)


def _map_usage(usage: Optional[dict], prompt_len: int) -> Usage:
    usage = usage or {}
    pt = int(usage.get("input_tokens") or 0)
    ct = int(usage.get("output_tokens") or 0)
    return Usage(prompt_tokens=pt, completion_tokens=ct, total_tokens=pt + ct)


async def _accumulate(
    req: ChatCompletionRequest,
) -> AsyncGenerator[tuple[str, bool, Optional[dict]], None]:
    """Yield (new_text, is_final, usage) — new_text is the suffix added since
    the last yield; is_final marks the terminal result event."""
    prompt, system_prompt = serialize_messages(req)
    emitted = ""
    full = ""
    final_usage: Optional[dict] = None
    async for obj in run_claude_stream(prompt, system_prompt, req.model):
        text, is_snapshot, usage = _event_text(obj)
        if usage is not None:
            final_usage = usage
        if text:
            if is_snapshot:
                if len(text) > len(full):
                    full = text
            else:
                full += text
            if len(full) > len(emitted):
                new = full[len(emitted):]
                emitted = full
                yield (new, False, None)
    yield ("", True, final_usage)


# ── Streaming (SSE) ──────────────────────────────────────────────────────────


async def stream_chat_completion(
    req: ChatCompletionRequest,
) -> AsyncGenerator[str, None]:
    cid = _rand_id("chatcmpl")
    model = CONFIG.resolve_model(req.model)

    def _sse(chunk: ChatCompletionChunk) -> str:
        return f"data: {chunk.model_dump_json()}\n\n"

    # First chunk announces the assistant role.
    yield _sse(ChatCompletionChunk(
        id=cid, model=model,
        choices=[ChunkChoice(delta=Delta(role="assistant"))],
    ))
    try:
        async for new_text, is_final, _usage in _accumulate(req):
            if is_final:
                break
            if new_text:
                yield _sse(ChatCompletionChunk(
                    id=cid, model=model,
                    choices=[ChunkChoice(delta=Delta(content=new_text))],
                ))
    except Exception as exc:  # surface CLI failures as a final error chunk
        logger.exception("stream failed")
        yield f"data: {json.dumps({'error': {'message': str(exc), 'type': 'cli_error'}})}\n\n"
    # Terminal chunk + sentinel.
    yield _sse(ChatCompletionChunk(
        id=cid, model=model,
        choices=[ChunkChoice(delta=Delta(), finish_reason="stop")],
    ))
    yield "data: [DONE]\n\n"


# ── Synchronous ──────────────────────────────────────────────────────────────


async def build_chat_completion(req: ChatCompletionRequest) -> ChatCompletion:
    model = CONFIG.resolve_model(req.model)
    full = ""
    usage: Optional[dict] = None
    async for new_text, is_final, u in _accumulate(req):
        if is_final:
            usage = u
            break
        full += new_text
    prompt, _ = serialize_messages(req)
    return ChatCompletion(
        model=model,
        choices=[Choice(message=ResponseMessage(content=full), finish_reason="stop")],
        usage=_map_usage(usage, len(prompt)),
    )


__all__ = ["serialize_messages", "stream_chat_completion", "build_chat_completion"]
