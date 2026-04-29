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

    catalog_normalizer_url: str = Field(
        default="http://localhost:8005",
        alias="CATALOG_NORMALIZER_URL",
    )

    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE),
        extra="ignore",
        populate_by_name=True,
    )
