"""Environment-driven configuration for the MCP Sidecar.

All secrets (BAP_API_KEY) must be injected at runtime via a Secrets Manager
or a .env file that is excluded from version control.  The sidecar will refuse
to start if BAP_API_KEY is absent from the environment.
"""
from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Network
    port: int = 3000

    # BAP Client
    bap_client_url: str = "http://localhost:8002"
    bap_api_key: str  # required — no default; fail-fast at boot if missing

    # Timeouts
    mcp_bap_timeout: float = 3.0  # seconds; enforced on the POST /discover call

    # Semantic ranking
    ranking_min_similarity: float = 0.30  # items below this threshold are filtered out


settings = Settings()
