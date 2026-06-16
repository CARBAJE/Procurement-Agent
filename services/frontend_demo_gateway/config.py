"""Env-driven configuration for the Frontend Demo Gateway.

Single module-level ``CONFIG`` singleton (repo convention — no scattered
``os.getenv`` calls elsewhere). Two concerns live here:

1. **Supplier Agent / Ollama** — the gateway hosts a *real* LLM supplier
   counter-party (``supplier_agent.SupplierAgent``) that talks to a local
   Ollama daemon through its OpenAI-compatible API. The base URL, API key
   (Ollama ignores it but the OpenAI SDK requires a non-empty string), and
   model are all read here — **never hardcoded** in the agent.
2. **Live wiring** — the gateway proxies negotiation kickoff/poll to the
   real Negotiation Engine (``:8004``) and publishes supplier responses to
   the Redis channel the engine's broker subscribes to
   (``beckn_on_select_results``), resuming the parked LangGraph thread.

All values are overridable via environment / ``.env``.
"""
from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ── Ollama / Supplier Agent ──────────────────────────────────────────
    # NOTE: the gateway runs as a HOST uvicorn process, so ``localhost`` here
    # reaches the host Ollama daemon directly (the in-network ollama container
    # is only needed by dockerised services). qwen3:8b is the supplier brain.
    ollama_base_url: str = Field(
        default="http://localhost:11434/v1", alias="OLLAMA_BASE_URL"
    )
    ollama_api_key: str = Field(default="ollama", alias="OLLAMA_API_KEY")
    supplier_model: str = Field(default="qwen3:8b", alias="SUPPLIER_MODEL")

    #: Below this fractional discount off list price the supplier accepts
    #: outright (its negotiation "reservation point"). Pure-config knob the
    #: deterministic fallback uses when the LLM output is unusable.
    supplier_acceptable_discount_floor: float = Field(
        default=0.08, alias="SUPPLIER_ACCEPTABLE_DISCOUNT_FLOOR"
    )
    supplier_max_rounds: int = Field(default=3, alias="SUPPLIER_MAX_ROUNDS")
    supplier_temperature: float = Field(default=0.4, alias="SUPPLIER_TEMPERATURE")
    supplier_timeout_s: float = Field(default=60.0, alias="SUPPLIER_TIMEOUT_S")

    # ── Live wiring (proxy + broker) ─────────────────────────────────────
    negotiation_engine_url: str = Field(
        default="http://localhost:8004", alias="NEGOTIATION_ENGINE_URL"
    )
    redis_url: str = Field(default="redis://localhost:6379/0", alias="REDIS_URL")
    #: Must match ``negotiation_engine.config.CONFIG.redis_on_select_channel``
    #: so the engine's OnSelectListener resumes the parked thread.
    redis_on_select_channel: str = Field(
        default="beckn_on_select_results", alias="REDIS_ON_SELECT_CHANNEL"
    )
    engine_timeout_s: float = Field(default=15.0, alias="ENGINE_TIMEOUT_S")

    log_level: str = Field(default="INFO", alias="FRONTEND_DEMO_GATEWAY_LOG_LEVEL")


CONFIG = Settings()

__all__ = ["CONFIG", "Settings"]
