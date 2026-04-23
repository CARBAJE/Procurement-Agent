from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Resolve .env relative to this file so BecknConfig works regardless of the
# working directory the caller uses (e.g. `python Bap-1/run.py` from parent).
_ENV_FILE = Path(__file__).parent.parent / ".env"


class BecknConfig(BaseSettings):
    bap_id: str = Field(default="bap.example.com", alias="BAP_ID")
    bap_uri: str = Field(default="http://localhost:8000/beckn", alias="BAP_URI")

    # beckn-onix Go adapter — handles ED25519 signing, schema validation, routing
    onix_url: str = Field(default="http://localhost:8081", alias="ONIX_URL")

    domain: str = Field(default="nic2004:52110", alias="DOMAIN")
    country: str = Field(default="IND", alias="COUNTRY")
    city: str = Field(default="std:080", alias="CITY")
    core_version: str = Field(default="2.0.0", alias="CORE_VERSION")
    request_timeout: int = Field(default=30, alias="REQUEST_TIMEOUT")
    # Used for async callbacks (on_select, on_init, on_confirm, on_status)
    callback_timeout: float = Field(default=10.0, alias="CALLBACK_TIMEOUT")

    # ── Buyer billing (Phase 2 stub — read by ConfigBillingProvider) ──────────
    # Swap to DatabaseBillingProvider in providers/__init__.py when the users
    # table is wired into the runtime. These fields do not need to be touched
    # in adapter/client/nodes — they only flow through the provider.
    buyer_name: str = Field(
        default="Infosys Limited - Procurement Desk",
        alias="BUYER_NAME",
    )
    buyer_email: str = Field(
        default="procurement@infosys.com",
        alias="BUYER_EMAIL",
    )
    buyer_phone: str = Field(default="+91-80-28520261", alias="BUYER_PHONE")
    buyer_tax_id: str = Field(default="29AAACI4741L1ZN", alias="BUYER_TAX_ID")

    buyer_address_door: str = Field(default="Tower A", alias="BUYER_ADDRESS_DOOR")
    buyer_address_building: str = Field(
        default="Infosys Campus",
        alias="BUYER_ADDRESS_BUILDING",
    )
    buyer_address_street: str = Field(
        default="Electronic City Phase 1",
        alias="BUYER_ADDRESS_STREET",
    )
    buyer_address_city: str = Field(default="Bangalore", alias="BUYER_ADDRESS_CITY")
    buyer_address_state: str = Field(default="Karnataka", alias="BUYER_ADDRESS_STATE")
    buyer_address_country: str = Field(default="IND", alias="BUYER_ADDRESS_COUNTRY")
    buyer_address_area_code: str = Field(
        default="560100",
        alias="BUYER_ADDRESS_AREA_CODE",
    )

    # ── Default delivery fulfillment (Phase 2 stub) ───────────────────────────
    # Read by ConfigFulfillmentProvider. By default, delivery goes to the same
    # address as billing; override with DELIVERY_* env vars for a different
    # delivery location.
    delivery_same_as_billing: bool = Field(
        default=True,
        alias="DELIVERY_SAME_AS_BILLING",
    )
    delivery_contact_name: str = Field(
        default="",
        alias="DELIVERY_CONTACT_NAME",
    )
    delivery_contact_phone: str = Field(
        default="",
        alias="DELIVERY_CONTACT_PHONE",
    )

    # ── Default payment method (Phase 2 stub) ─────────────────────────────────
    # Read by CODPaymentProvider. Beckn v2 payment types:
    #   ON_ORDER | ON_FULFILLMENT (COD) | POST_FULFILLMENT (invoice/NET-30)
    default_payment_type: str = Field(
        default="ON_FULFILLMENT",
        alias="DEFAULT_PAYMENT_TYPE",
    )
    default_payment_collector: str = Field(
        default="BPP",
        alias="DEFAULT_PAYMENT_COLLECTOR",
    )

    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE),
        extra="ignore",
        populate_by_name=True,
    )
