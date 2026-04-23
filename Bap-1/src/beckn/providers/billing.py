"""BillingProvider — swappable source for buyer billing info in /init.

Contract stays stable as the source migrates from config → session → DB.
"""
from __future__ import annotations

from typing import Optional, Protocol

from ...config import BecknConfig
from ..models import Address, BillingInfo


class BillingProvider(Protocol):
    """Returns billing info for an order.

    Implementations must accept an optional `user_id` (future DB/session
    providers key off it) but are not required to use it. Phase 2 ignores it.
    """

    def get_billing(self, *, user_id: Optional[str] = None) -> BillingInfo: ...


class ConfigBillingProvider:
    """Phase 2: billing from BecknConfig / .env (single hardcoded buyer).

    TO SWAP FOR REAL:
      1. Implement a new class matching BillingProvider (e.g.,
         DatabaseBillingProvider that queries the users table).
      2. Change ONE line in providers/__init__.py build_providers().
      3. adapter.py, client.py, nodes.py are untouched.
    """

    def __init__(self, config: BecknConfig) -> None:
        self._config = config

    def get_billing(self, *, user_id: Optional[str] = None) -> BillingInfo:
        c = self._config
        return BillingInfo(
            name=c.buyer_name,
            email=c.buyer_email,
            phone=c.buyer_phone,
            address=Address(
                door=c.buyer_address_door or None,
                building=c.buyer_address_building or None,
                street=c.buyer_address_street or None,
                city=c.buyer_address_city,
                state=c.buyer_address_state or None,
                country=c.buyer_address_country,
                area_code=c.buyer_address_area_code,
            ),
            tax_id=c.buyer_tax_id or None,
        )
