"""Swappable providers for order-lifecycle inputs.

The adapter/client/nodes never touch .env, DB, or session directly. They
receive already-constructed BillingInfo / FulfillmentInfo / PaymentTerms
objects from a ProviderBundle. To change the source, change ONE line in
build_providers() — nothing else.
"""
from __future__ import annotations

from dataclasses import dataclass

from ...config import BecknConfig
from .billing import BillingProvider, ConfigBillingProvider
from .fulfillment import ConfigFulfillmentProvider, FulfillmentProvider
from .payment import CODPaymentProvider, PaymentProvider, build_cod_provider

__all__ = [
    "BillingProvider",
    "ConfigBillingProvider",
    "FulfillmentProvider",
    "ConfigFulfillmentProvider",
    "PaymentProvider",
    "CODPaymentProvider",
    "ProviderBundle",
    "build_providers",
]


@dataclass(frozen=True)
class ProviderBundle:
    """Single container passed to ProcurementAgent / nodes."""

    billing: BillingProvider
    fulfillment: FulfillmentProvider
    payment: PaymentProvider


def build_providers(config: BecknConfig) -> ProviderBundle:
    """Single swap point for provider wiring.

    Phase 2 (current):
        billing    ← ConfigBillingProvider  (reads .env)
        fulfillment ← ConfigFulfillmentProvider  (reads .env + intent coords)
        payment    ← CODPaymentProvider  (cash on delivery)

    Phase 3+ migration (example):
        billing    ← DatabaseBillingProvider(db_pool)
        fulfillment ← SessionFulfillmentProvider(session)
        payment    ← UPIPaymentProvider(upi_gateway)

    Each provider is completely independent — you can swap one without
    touching the others, adapter, client, or nodes.
    """
    return ProviderBundle(
        billing=ConfigBillingProvider(config),
        fulfillment=ConfigFulfillmentProvider(config),
        payment=build_cod_provider(config),
    )
