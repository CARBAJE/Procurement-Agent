"""FastAPI app exposing Claude Code as an OpenAI-compatible API (loopback only).

Routes:
  GET  /healthz                 — liveness (no auth)
  GET  /v1/models               — advertise the mapped model list
  POST /v1/chat/completions     — sync (ChatCompletion) or SSE stream

Security: binds 127.0.0.1 and enforces a Bearer token (CLAUDE_PROXY_KEY) on
/v1/* via middleware. If no key is configured, auth is disabled with a warning.
"""
from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse
from starlette.middleware.base import BaseHTTPMiddleware

from . import adapter
from .config import CONFIG
from .models import ChatCompletionRequest, ModelCard, ModelList

logging.basicConfig(level="INFO", format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger("claude_proxy")


class BearerAuthMiddleware(BaseHTTPMiddleware):
    """Require ``Authorization: Bearer <CLAUDE_PROXY_KEY>`` on protected paths."""

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if path.startswith("/v1") and CONFIG.key:
            header = request.headers.get("authorization", "")
            token = header[7:].strip() if header.lower().startswith("bearer ") else ""
            if token != CONFIG.key:
                return JSONResponse(
                    status_code=401,
                    content={"error": {
                        "message": "Invalid or missing API key.",
                        "type": "invalid_request_error", "code": "invalid_api_key",
                    }},
                )
        return await call_next(request)


app = FastAPI(
    title="Claude Code OpenAI Proxy",
    description="OpenAI-compatible (/v1/chat/completions) wrapper over the local Claude Code CLI.",
    version="1.0.0",
)
app.add_middleware(BearerAuthMiddleware)


@app.on_event("startup")
async def _startup() -> None:
    if not CONFIG.key:
        logger.warning("CLAUDE_PROXY_KEY is empty — auth DISABLED (dev only).")
    logger.info(
        "ready on http://%s:%d  binary=%s  default_model=%s  max_concurrency=%d",
        CONFIG.host, CONFIG.port, CONFIG.binary_path, CONFIG.default_model,
        CONFIG.max_concurrency,
    )


@app.get("/healthz", tags=["ops"])
async def healthz() -> dict:
    return {"status": "ok", "binary": CONFIG.binary_path}


@app.get("/v1/models", tags=["openai"])
async def list_models() -> ModelList:
    ids = sorted(set(CONFIG.model_map.keys()))
    return ModelList(data=[ModelCard(id=mid) for mid in ids])


@app.post("/v1/chat/completions", tags=["openai"])
async def chat_completions(req: ChatCompletionRequest):
    if not req.messages:
        return JSONResponse(
            status_code=400,
            content={"error": {"message": "`messages` must not be empty.",
                               "type": "invalid_request_error"}},
        )
    if req.stream:
        return StreamingResponse(
            adapter.stream_chat_completion(req),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )
    try:
        result = await adapter.build_chat_completion(req)
    except Exception as exc:  # CLI failure → OpenAI-shaped 502
        logger.exception("completion failed")
        return JSONResponse(
            status_code=502,
            content={"error": {"message": str(exc), "type": "cli_error"}},
        )
    return JSONResponse(content=result.model_dump())


__all__ = ["app"]
