"""Resolve ERP_VENDORS to a single ERPAdapter (single or multi)."""
from __future__ import annotations

from aiohttp import ClientSession

from adapters.base import ERPAdapter, VendorPermanentError
from adapters.fanout import MultiVendorAdapter
from adapters.mock import MockERPAdapter
from adapters.oracle import OracleERPCloudAdapter
from adapters.sap import SAPS4HanaAdapter
from config import Settings
from resilience import BreakerRegistry


def build_adapter(settings: Settings, http: ClientSession) -> ERPAdapter:
    # Single registry, breakers built lazily per vendor. Excluding
    # VendorPermanentError keeps "bad payload" from tripping the breaker.
    breakers = BreakerRegistry(
        fail_max=settings.breaker_fail_max,
        reset_timeout=settings.breaker_reset_timeout_secs,
        excluded=(VendorPermanentError,),
    )

    instances: list[ERPAdapter] = []
    for v in settings.erp_vendors:
        if v == "mock":
            instances.append(MockERPAdapter(
                settings.mock_base_url, http,
                breaker=breakers.for_vendor("mock"),
            ))
        elif v == "sap":
            instances.append(SAPS4HanaAdapter(
                base_url=settings.sap_base_url,
                token_url=settings.sap_oauth_token_url,
                client_id=settings.sap_client_id,
                client_secret=settings.sap_client_secret,
                budget_check_url=settings.sap_budget_check_url,
                http=http,
                breaker=breakers.for_vendor("sap"),
            ))
        elif v == "oracle":
            instances.append(OracleERPCloudAdapter(
                base_url=settings.oracle_base_url,
                token_url=settings.oracle_oauth_token_url,
                client_id=settings.oracle_client_id,
                client_secret=settings.oracle_client_secret,
                budget_check_url=settings.oracle_budget_check_url,
                http=http,
                breaker=breakers.for_vendor("oracle"),
            ))
        else:
            raise ValueError(f"unsupported vendor in ERP_VENDORS: {v!r}")

    if len(instances) == 1:
        return instances[0]
    return MultiVendorAdapter(instances)
