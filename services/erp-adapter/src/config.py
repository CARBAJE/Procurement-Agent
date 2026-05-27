"""Configuration for the ERP adapter service.

All settings are read from env vars at startup. The Pydantic Settings model
gives us typed access and one place to extend when new vendor credentials
arrive. Defaults are dev-safe (mock vendor, mock-ERP base URL).
"""
from __future__ import annotations

from typing import List

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # ── Server
    port: int = Field(default=8007, alias="PORT")

    # ── Internal auth (orchestrator → adapter)
    internal_token: str = Field(default="dev-internal-token-CHANGE_ME", alias="ERP_INTERNAL_TOKEN")

    # ── Database
    db_host: str = Field(default="procurement-postgres", alias="DB_HOST")
    db_port: int = Field(default=5432, alias="DB_PORT")
    db_name: str = Field(default="procurement_agent", alias="DB_NAME")
    db_user: str = Field(default="postgres", alias="DB_USER")
    db_password: str = Field(default="postgres123", alias="DB_PASSWORD")

    # ── Redis
    redis_url: str = Field(default="redis://redis:6379", alias="REDIS_URL")

    # ── Vendor selection — "mock" | "sap" | "oracle" | "sap,oracle"
    erp_vendors_raw: str = Field(default="mock", alias="ERP_VENDORS")

    # ── Mock ERP
    mock_base_url: str = Field(default="http://erp-mock:8008", alias="ERP_MOCK_BASE_URL")

    # ── SAP S/4HANA (only used when "sap" ∈ erp_vendors)
    sap_oauth_token_url: str = Field(default="http://erp-mock:8008/sap/oauth2/token", alias="SAP_OAUTH_TOKEN_URL")
    sap_base_url: str = Field(default="http://erp-mock:8008/sap/opu/odata/sap/API_PURCHASEORDER_PROCESS_SRV", alias="SAP_BASE_URL")
    sap_client_id: str = Field(default="mock-sap-client", alias="SAP_CLIENT_ID")
    sap_client_secret: str = Field(default="mock-sap-secret", alias="SAP_CLIENT_SECRET")
    sap_webhook_hmac_secret: str = Field(default="dev-sap-hmac-CHANGE_ME", alias="SAP_WEBHOOK_HMAC_SECRET")
    sap_webhook_hmac_secret_next: str = Field(default="", alias="SAP_WEBHOOK_HMAC_SECRET_NEXT")

    # ── Oracle ERP Cloud (only used when "oracle" ∈ erp_vendors)
    oracle_oauth_token_url: str = Field(default="http://erp-mock:8008/oauth2/v1/token", alias="ORACLE_OAUTH_TOKEN_URL")
    oracle_base_url: str = Field(default="http://erp-mock:8008/fscmRestApi/resources/11.13.18.05", alias="ORACLE_BASE_URL")
    oracle_client_id: str = Field(default="mock-oracle-client", alias="ORACLE_CLIENT_ID")
    oracle_client_secret: str = Field(default="mock-oracle-secret", alias="ORACLE_CLIENT_SECRET")
    oracle_webhook_hmac_secret: str = Field(default="dev-oracle-hmac-CHANGE_ME", alias="ORACLE_WEBHOOK_HMAC_SECRET")
    oracle_webhook_hmac_secret_next: str = Field(default="", alias="ORACLE_WEBHOOK_HMAC_SECRET_NEXT")

    # ── Per-vendor circuit breaker
    breaker_fail_max: int = Field(default=5, alias="BREAKER_FAIL_MAX")
    breaker_reset_timeout_secs: int = Field(default=60, alias="BREAKER_RESET_TIMEOUT_SECS")

    # ── Vendor-shaped budget endpoints (for adapters that aren't routed to
    # the generic /mock/budget/check). Default points at the mock-erp's
    # vendor-shaped paths so the dev loop still works.
    sap_budget_check_url: str = Field(
        default="http://erp-mock:8008/sap/budget/check", alias="SAP_BUDGET_CHECK_URL",
    )
    oracle_budget_check_url: str = Field(
        default="http://erp-mock:8008/oracle/budget/check", alias="ORACLE_BUDGET_CHECK_URL",
    )

    # ── Outbox worker
    worker_concurrency: int = Field(default=10, alias="WORKER_CONCURRENCY")
    # Comma-separated seconds; default '5,30,120,600,3600' = 5 attempts up to 1h.
    worker_backoff_csv: str = Field(default="5,30,120,600,3600", alias="WORKER_BACKOFF_CSV")
    worker_poll_interval_seconds: float = Field(default=2.0, alias="WORKER_POLL_INTERVAL_SECONDS")

    @property
    def worker_backoff(self) -> tuple[float, ...]:
        return tuple(float(x.strip()) for x in self.worker_backoff_csv.split(",") if x.strip())

    # ── Budget check resilience
    budget_check_total_timeout_ms: int = Field(default=800, alias="BUDGET_CHECK_TOTAL_TIMEOUT_MS")

    # ── Logging
    log_payloads: bool = Field(default=False, alias="LOG_PAYLOADS")

    @field_validator("erp_vendors_raw")
    @classmethod
    def _validate_vendors(cls, v: str) -> str:
        allowed = {"mock", "sap", "oracle"}
        parts = [p.strip().lower() for p in v.split(",") if p.strip()]
        bad = [p for p in parts if p not in allowed]
        if bad:
            raise ValueError(f"Unknown ERP vendor(s) {bad}; allowed: {sorted(allowed)}")
        if not parts:
            raise ValueError("ERP_VENDORS must list at least one vendor")
        return ",".join(parts)

    @property
    def erp_vendors(self) -> List[str]:
        return [v.strip() for v in self.erp_vendors_raw.split(",") if v.strip()]
