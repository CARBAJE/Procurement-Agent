"""Module-level environment configuration for the Discovery Engine.

Follows the repo convention of a single ``config.py`` per service
loaded via Pydantic Settings v2 (matches ``negotiation_engine`` and
``beckn-bap-client``).

The list of Beckn networks the engine fans out to is supplied as a
JSON string in ``DISCOVERY_NETWORKS_JSON`` — convenient for both
docker-compose ``environment:`` entries and Kubernetes ConfigMaps.
Two sensible localhost defaults ship out of the box so a fresh
checkout can run ``uvicorn src.main:app`` without configuration.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from .models import NetworkGateway

logger = logging.getLogger(__name__)

_ENV_FILE = Path(__file__).resolve().parent.parent / ".env"

#: Default two-network JSON used when ``DISCOVERY_NETWORKS_JSON`` is unset.
#: Distinct ports so a single Beckn sandbox running multiple registries on
#: localhost is the canonical dev setup.
_DEFAULT_NETWORKS_JSON: str = json.dumps(
    [
        {"name": "network_a", "base_url": "http://network-a.local:8080", "timeout_s": 8.0},
        {"name": "network_b", "base_url": "http://network-b.local:8080", "timeout_s": 8.0},
    ]
)


class DiscoveryConfig(BaseSettings):
    """Immutable snapshot of the engine's environment configuration."""

    # ── Network list ────────────────────────────────────────────────────
    networks_json: str = Field(
        default=_DEFAULT_NETWORKS_JSON,
        alias="DISCOVERY_NETWORKS_JSON",
        description="JSON-encoded list of NetworkGateway objects.",
    )

    # ── Per-network defaults (used when a network entry omits the field) ─
    default_timeout_s: float = Field(
        default=8.0, alias="DISCOVERY_DEFAULT_TIMEOUT_S", gt=0.0
    )

    # ── Circuit breaker tuning ──────────────────────────────────────────
    circuit_failure_threshold: int = Field(
        default=3, alias="DISCOVERY_CB_FAILURE_THRESHOLD", ge=1
    )
    circuit_recovery_timeout_s: float = Field(
        default=30.0, alias="DISCOVERY_CB_RECOVERY_TIMEOUT_S", gt=0.0
    )

    # ── Aggregator tuning ───────────────────────────────────────────────
    geo_proximity_km: float = Field(
        default=0.5,
        alias="DISCOVERY_GEO_PROXIMITY_KM",
        ge=0.0,
        description=(
            "Maximum great-circle distance between two items with the same "
            "name/currency to be treated as a geographic duplicate."
        ),
    )

    # ── HTTP runtime ────────────────────────────────────────────────────
    http_connector_limit: int = Field(
        default=64, alias="DISCOVERY_HTTP_CONNECTOR_LIMIT", ge=1
    )
    http_outer_timeout_s: float = Field(
        default=60.0,
        alias="DISCOVERY_HTTP_OUTER_TIMEOUT_S",
        description="Belt-and-braces outer ceiling on the aiohttp ClientSession.",
    )

    # ── FastAPI / runtime ───────────────────────────────────────────────
    api_host: str = Field(default="0.0.0.0", alias="DISCOVERY_API_HOST")
    api_port: int = Field(default=8006, alias="DISCOVERY_API_PORT")
    log_level: str = Field(default="INFO", alias="DISCOVERY_LOG_LEVEL")

    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE),
        extra="ignore",
        populate_by_name=True,
        frozen=True,
    )

    # ── Convenience accessor ────────────────────────────────────────────

    @property
    def gateways(self) -> list[NetworkGateway]:
        """Parse the networks JSON into a list of :class:`NetworkGateway`.

        Returns an empty list (and logs a warning) on malformed JSON or
        invalid gateway entries so a typo in the deployment manifest
        produces a noisy but non-crashing service.
        """
        try:
            raw = json.loads(self.networks_json)
        except json.JSONDecodeError as exc:
            logger.error("DISCOVERY_NETWORKS_JSON is not valid JSON: %s", exc)
            return []
        if not isinstance(raw, list):
            logger.error("DISCOVERY_NETWORKS_JSON must be a JSON array of objects")
            return []

        gateways: list[NetworkGateway] = []
        for idx, entry in enumerate(raw):
            if not isinstance(entry, dict):
                logger.warning("Skipping non-dict gateway entry at index %d", idx)
                continue
            entry.setdefault("timeout_s", self.default_timeout_s)
            try:
                gateways.append(NetworkGateway(**entry))
            except Exception as exc:  # noqa: BLE001 - pydantic ValidationError + others
                logger.warning(
                    "Skipping invalid gateway entry %s at index %d: %s",
                    entry.get("name", "<unnamed>"), idx, exc,
                )
        return gateways


CONFIG: DiscoveryConfig = DiscoveryConfig()


__all__ = ["CONFIG", "DiscoveryConfig"]
