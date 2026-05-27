"""Minimal env config for the mock ERP."""
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class MockConfig:
    port: int
    scenario: str
    webhook_target_url: str
    webhook_delay_seconds: float
    sap_hmac_secret: str
    oracle_hmac_secret: str


def from_env() -> MockConfig:
    return MockConfig(
        port=int(os.getenv("PORT", "8008")),
        scenario=os.getenv("MOCK_SCENARIO", "happy"),
        webhook_target_url=os.getenv("WEBHOOK_TARGET_URL", "http://erp-adapter:8007"),
        webhook_delay_seconds=float(os.getenv("WEBHOOK_DELAY_SECONDS", "2")),
        sap_hmac_secret=os.getenv("SAP_WEBHOOK_HMAC_SECRET", "dev-sap-hmac-CHANGE_ME"),
        oracle_hmac_secret=os.getenv("ORACLE_WEBHOOK_HMAC_SECRET", "dev-oracle-hmac-CHANGE_ME"),
    )
