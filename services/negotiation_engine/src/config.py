"""Module-level environment configuration for the Negotiation Engine.

Per the repo convention documented in ``CLAUDE.md``, every service reads
its environment through a single ``config.py`` — no ``os.getenv(...)``
calls live anywhere else in the package. This module uses **Pydantic
Settings v2** (matching the pattern in ``services/beckn-bap-client``)
to load environment variables into a frozen, typed singleton.

Step 4 adds the LangSmith observability variables. The LangChain /
LangGraph runtimes read these *directly* from ``os.environ`` — we do
not pass them through any client object. The values here serve two
purposes:

1. **Validation at startup** — if ``LANGCHAIN_TRACING_V2=true`` is set
   we surface that fact so the operator can confirm tracing is on.
2. **Re-export** — when the env vars are present in the process
   environment, LangGraph's instrumentation picks them up automatically
   and emits a span per node transition, per
   ``04_resilience_and_mlops`` §7.2 (LangSmith).

The four LangSmith variables follow LangChain's canonical names:

* ``LANGCHAIN_TRACING_V2`` — ``"true"`` to enable tracing.
* ``LANGCHAIN_ENDPOINT``  — typically ``https://api.smith.langchain.com``.
* ``LANGCHAIN_API_KEY``   — the LangSmith key (secret).
* ``LANGCHAIN_PROJECT``   — the project name (default: ``procurement-negotiation-prod``).

When ``LANGCHAIN_TRACING_V2`` is set to ``"true"``, LangGraph will:
- Emit a trace span for every node entry/exit.
- Tag the trace with ``thread_id == transaction_id``.
- Stream interrupt + resume events with full state diffs.
"""
from __future__ import annotations

import logging
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)

# Resolve ``.env`` relative to the service root so the config works
# regardless of the caller's working directory. Matches the pattern in
# ``services/beckn-bap-client/src/config.py``.
_ENV_FILE = Path(__file__).resolve().parent.parent / ".env"


class NegotiationConfig(BaseSettings):
    """Immutable snapshot of the engine's environment configuration."""

    # ── OpenAI / LLM (advisory node) ────────────────────────────────────
    openai_api_key: str | None = Field(default=None, alias="OPENAI_API_KEY")
    # Advisory/ambiguous LLM node routes through the local Claude Code proxy.
    # NOTE: this engine is a BRIDGED container, so it reaches the host proxy via
    # host.docker.internal:8012 — which requires a UFW allow rule for
    # docker→host:8012 (analogous to the :11434 rule). `localhost` would point
    # at the container itself. Left None-able so unset key => placeholder path.
    openai_base_url: str | None = Field(
        default="http://host.docker.internal:8012/v1", alias="NEGOTIATION_OPENAI_BASE_URL"
    )
    openai_model: str = Field(default="claude-3-5-sonnet", alias="NEGOTIATION_OPENAI_MODEL")
    openai_timeout_s: float = Field(default=30.0, alias="NEGOTIATION_OPENAI_TIMEOUT_S")
    advisory_max_tokens: int = Field(
        default=512, alias="NEGOTIATION_ADVISORY_MAX_TOKENS"
    )

    # ── Qdrant (agent memory) ───────────────────────────────────────────
    qdrant_url: str | None = Field(default=None, alias="QDRANT_URL")
    qdrant_api_key: str | None = Field(default=None, alias="QDRANT_API_KEY")
    qdrant_collection: str = Field(
        default="negotiation_outcomes", alias="NEGOTIATION_QDRANT_COLLECTION"
    )

    # ── Kafka (audit trail) ─────────────────────────────────────────────
    kafka_bootstrap_servers: str | None = Field(
        default=None, alias="KAFKA_BOOTSTRAP_SERVERS"
    )
    kafka_negotiation_topic: str = Field(
        default="procurement.negotiation.v1", alias="NEGOTIATION_KAFKA_TOPIC"
    )
    kafka_policy_violations_topic: str = Field(
        default="procurement.negotiation.policy_violations.v1",
        alias="NEGOTIATION_KAFKA_POLICY_VIOLATIONS_TOPIC",
    )
    kafka_dlq_topic: str = Field(
        default="procurement.negotiation.dlq.v1", alias="NEGOTIATION_KAFKA_DLQ_TOPIC"
    )
    kafka_client_id: str = Field(
        default="negotiation-engine", alias="NEGOTIATION_KAFKA_CLIENT_ID"
    )

    # ── Redis (async transport) ─────────────────────────────────────────
    redis_url: str = Field(default="redis://localhost:6379/0", alias="REDIS_URL")
    redis_on_select_channel: str = Field(
        default="beckn_on_select_results",
        alias="NEGOTIATION_REDIS_ON_SELECT_CHANNEL",
    )
    redis_hitl_channel_prefix: str = Field(
        default="negotiation_hitl_decisions",
        alias="NEGOTIATION_REDIS_HITL_PREFIX",
    )

    # ── PostgreSQL (LangGraph durable checkpointer) ─────────────────────
    postgres_dsn: str | None = Field(
        default=None, alias="NEGOTIATION_POSTGRES_DSN"
    )

    # ── LangSmith (observability — Step 4) ──────────────────────────────
    #
    # These four variables are LangChain's canonical observability
    # contract. When ``langchain_tracing_v2`` evaluates truthy and an
    # API key is present, the LangGraph runtime emits a trace span per
    # node transition with no additional code on our side. The CONFIG
    # singleton exposes the values for status/debug endpoints; the
    # LangChain SDK itself reads ``os.environ`` directly so the *only*
    # thing required for tracing is that the env vars be set in the
    # process environment before ``langchain``/``langgraph`` are imported.
    langchain_tracing_v2: str = Field(default="false", alias="LANGCHAIN_TRACING_V2")
    langchain_endpoint: str = Field(
        default="https://api.smith.langchain.com",
        alias="LANGCHAIN_ENDPOINT",
    )
    langchain_api_key: str | None = Field(default=None, alias="LANGCHAIN_API_KEY")
    langchain_project: str = Field(
        default="procurement-negotiation-prod", alias="LANGCHAIN_PROJECT"
    )

    # ── FastAPI / runtime ───────────────────────────────────────────────
    api_host: str = Field(default="0.0.0.0", alias="NEGOTIATION_API_HOST")
    api_port: int = Field(default=8004, alias="NEGOTIATION_API_PORT")
    log_level: str = Field(default="INFO", alias="NEGOTIATION_LOG_LEVEL")

    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE),
        extra="ignore",
        populate_by_name=True,
        frozen=True,
    )

    # ── Convenience predicates ──────────────────────────────────────────

    @property
    def tracing_enabled(self) -> bool:
        """Whether LangSmith tracing is fully configured.

        Both the toggle *and* the API key are required — LangSmith
        rejects unauthenticated traces, and silently-dropped traces are
        a worse signal than no tracing at all.
        """
        return self.langchain_tracing_v2.lower() in {"true", "1", "yes"} and bool(
            self.langchain_api_key
        )


#: Package-wide singleton. Re-importing the module re-reads the env.
CONFIG: NegotiationConfig = NegotiationConfig()


if CONFIG.tracing_enabled:
    logger.info(
        "LangSmith tracing ENABLED — project=%s endpoint=%s",
        CONFIG.langchain_project,
        CONFIG.langchain_endpoint,
    )
else:
    logger.info(
        "LangSmith tracing disabled (LANGCHAIN_TRACING_V2=%s, api_key=%s)",
        CONFIG.langchain_tracing_v2,
        "set" if CONFIG.langchain_api_key else "unset",
    )


__all__ = ["CONFIG", "NegotiationConfig"]
