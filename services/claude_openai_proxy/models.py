"""Pydantic v2 schemas mirroring the OpenAI Chat Completions wire shapes.

Only the fields a typical client sends/reads are modeled; unsupported sampling
knobs (temperature, top_p, …) are accepted via ``extra="allow"`` on the request
and then ignored (the Claude Code CLI exposes no sampling controls).
"""
from __future__ import annotations

import time
import uuid
from typing import Any, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field


def _rand_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex}"


# ── Request ──────────────────────────────────────────────────────────────────


class ChatMessage(BaseModel):
    model_config = ConfigDict(extra="allow")
    role: str
    # OpenAI allows string or a list of content parts; we accept both.
    content: Union[str, list[dict[str, Any]], None] = None
    name: Optional[str] = None


class ChatCompletionRequest(BaseModel):
    # extra="allow" → temperature/top_p/max_tokens/etc. are accepted and ignored.
    model_config = ConfigDict(extra="allow")
    model: Optional[str] = None
    messages: list[ChatMessage]
    stream: bool = False


# ── Shared sub-objects ───────────────────────────────────────────────────────


class Usage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class ResponseMessage(BaseModel):
    role: Literal["assistant"] = "assistant"
    content: str = ""


# ── Synchronous response (stream=false) ──────────────────────────────────────


class Choice(BaseModel):
    index: int = 0
    message: ResponseMessage
    finish_reason: Optional[str] = "stop"


class ChatCompletion(BaseModel):
    id: str = Field(default_factory=lambda: _rand_id("chatcmpl"))
    object: Literal["chat.completion"] = "chat.completion"
    created: int = Field(default_factory=lambda: int(time.time()))
    model: str
    choices: list[Choice]
    usage: Usage = Field(default_factory=Usage)


# ── Streaming response (stream=true) ─────────────────────────────────────────


class Delta(BaseModel):
    role: Optional[Literal["assistant"]] = None
    content: Optional[str] = None


class ChunkChoice(BaseModel):
    index: int = 0
    delta: Delta
    finish_reason: Optional[str] = None


class ChatCompletionChunk(BaseModel):
    id: str
    object: Literal["chat.completion.chunk"] = "chat.completion.chunk"
    created: int = Field(default_factory=lambda: int(time.time()))
    model: str
    choices: list[ChunkChoice]


# ── /v1/models ───────────────────────────────────────────────────────────────


class ModelCard(BaseModel):
    id: str
    object: Literal["model"] = "model"
    created: int = Field(default_factory=lambda: int(time.time()))
    owned_by: str = "claude-code-proxy"


class ModelList(BaseModel):
    object: Literal["list"] = "list"
    data: list[ModelCard]


__all__ = [
    "ChatMessage", "ChatCompletionRequest", "Usage", "ResponseMessage",
    "Choice", "ChatCompletion", "Delta", "ChunkChoice", "ChatCompletionChunk",
    "ModelCard", "ModelList", "_rand_id",
]
