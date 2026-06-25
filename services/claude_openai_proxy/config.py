"""Configuration for the Claude Code → OpenAI-compatible proxy.

Env-driven (Pydantic Settings v2). Everything is overridable via environment
variables; sane local-dev defaults are baked in. Security-sensitive values
(the proxy bearer key) MUST come from the environment.
"""
from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="CLAUDE_PROXY_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ── Binding (loopback only — this proxy runs as the host user's Claude) ──
    host: str = Field(default="127.0.0.1", alias="CLAUDE_PROXY_HOST")
    port: int = Field(default=8012, alias="CLAUDE_PROXY_PORT")

    # ── Auth: required Bearer token. If empty, auth is DISABLED (logged warn). ──
    key: str = Field(default="", alias="CLAUDE_PROXY_KEY")

    # ── Claude Code CLI ──────────────────────────────────────────────────────
    binary_path: str = Field(
        default="/home/carbaje/.local/bin/claude", alias="CLAUDE_PROXY_BINARY_PATH"
    )
    default_model: str = Field(default="sonnet", alias="CLAUDE_PROXY_DEFAULT_MODEL")
    permission_mode: str = Field(default="default", alias="CLAUDE_PROXY_PERMISSION_MODE")
    include_partial: bool = Field(default=True, alias="CLAUDE_PROXY_INCLUDE_PARTIAL")

    # Pure-chat: explicitly deny every acting/IO tool so a prompt can never
    # trigger an interactive permission gate (which would hang -p mode).
    disable_tools: bool = Field(default=True, alias="CLAUDE_PROXY_DISABLE_TOOLS")
    disallowed_tools: list[str] = Field(
        default_factory=lambda: [
            "Bash", "Edit", "Write", "Read", "Glob", "Grep", "MultiEdit",
            "NotebookEdit", "WebFetch", "WebSearch", "Task", "TodoWrite",
        ]
    )

    # ── Runtime guards ───────────────────────────────────────────────────────
    max_concurrency: int = Field(default=2, alias="CLAUDE_PROXY_MAX_CONCURRENCY")
    #: Hard ceiling: if the CLI emits no new line for this long, the subprocess
    #: is killed. This is the real anti-hang guarantee.
    timeout_s: float = Field(default=120.0, alias="CLAUDE_PROXY_TIMEOUT_S")

    #: OpenAI model name → Claude Code --model. Unknown names fall back to
    #: default_model; any name already starting with "claude" passes through.
    model_map: dict[str, str] = Field(
        default_factory=lambda: {
            "gpt-4o": "sonnet",
            "gpt-4o-mini": "haiku",
            "gpt-4-turbo": "sonnet",
            "gpt-4": "opus",
            "gpt-3.5-turbo": "haiku",
            "claude-3-5-sonnet": "sonnet",
            "claude-3-5-haiku": "haiku",
            "opus": "opus",
            "sonnet": "sonnet",
            "haiku": "haiku",
        }
    )

    def resolve_model(self, requested: str | None) -> str:
        if not requested:
            return self.default_model
        if requested in self.model_map:
            return self.model_map[requested]
        if requested.lower().startswith("claude"):
            return requested  # pass-through explicit claude id
        return self.default_model


CONFIG = Settings()

__all__ = ["CONFIG", "Settings"]
