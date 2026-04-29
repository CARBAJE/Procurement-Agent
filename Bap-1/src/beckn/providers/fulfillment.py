"""FulfillmentProvider — swappable source for delivery info in /init."""
from __future__ import annotations

from typing import Optional, Protocol

from shared.models import BecknIntent

from ...config import BecknConfig
from ..models import Address, FulfillmentInfo


class FulfillmentProvider(Protocol):
    """Returns fulfillment (delivery) info for an order.

    Accepts the intent so providers can derive coordinates and the delivery
    deadline from the user's request.
    """

    def get_fulfillment(
        self,
        *,
        intent: BecknIntent,
        user_id: Optional[str] = None,
    ) -> FulfillmentInfo: ...


class ConfigFulfillmentProvider:
    """Phase 2: fulfillment from BecknConfig / .env.

    By default the delivery address mirrors billing (same office). When the
    intent provides lat/lon, those override the config default — the user
    explicitly asked for a different drop-off.

    TO SWAP FOR REAL:
      Return FulfillmentInfo from a different source (user profile,
      explicit form field, etc.). Keep the signature identical.
    """

    def __init__(self, config: BecknConfig) -> None:
        self._config = config

    def get_fulfillment(
        self,
        *,
        intent: BecknIntent,
        user_id: Optional[str] = None,
    ) -> FulfillmentInfo:
        c = self._config

        # Prefer the intent's coordinates (user asked for a specific place);
        # fall back to a reasonable default for the configured city.
        end_location = intent.location_coordinates or "12.9716,77.5946"

        end_address = Address(
            door=c.buyer_address_door or None,
            building=c.buyer_address_building or None,
            street=c.buyer_address_street or None,
            city=c.buyer_address_city,
            state=c.buyer_address_state or None,
            country=c.buyer_address_country,
            area_code=c.buyer_address_area_code,
        )

        # Delivery contact defaults to the billing contact if not overridden.
        contact_name = c.delivery_contact_name or c.buyer_name
        contact_phone = c.delivery_contact_phone or c.buyer_phone

        return FulfillmentInfo(
            type="Delivery",
            end_location=end_location,
            end_address=end_address,
            contact_name=contact_name,
            contact_phone=contact_phone,
            delivery_timeline=intent.delivery_timeline,
        )
