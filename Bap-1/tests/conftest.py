import pytest

from src.beckn.adapter import BecknProtocolAdapter
from src.beckn.callbacks import CallbackCollector
from src.beckn.providers import build_providers
from src.config import BecknConfig

ONIX_URL = "http://mock-onix.test"
BPP_URI = "http://mock-bpp.test"


@pytest.fixture
def beckn_config():
    return BecknConfig(
        bap_id="test-bap",
        bap_uri="http://localhost:8000/beckn",
        onix_url=ONIX_URL,
        domain="nic2004:52110",
        country="IND",
        city="std:080",
        core_version="2.0.0",
        callback_timeout=0.5,
        request_timeout=5,
        buyer_name="Test Buyer",
        buyer_email="test@example.com",
        buyer_phone="+91-0000000000",
        buyer_tax_id="TESTTAXID",
        buyer_address_door="Door 1",
        buyer_address_building="Building Test",
        buyer_address_street="Street Test",
        buyer_address_city="Bangalore",
        buyer_address_state="Karnataka",
        buyer_address_country="IND",
        buyer_address_area_code="560100",
    )


@pytest.fixture
def adapter(beckn_config):
    return BecknProtocolAdapter(beckn_config)


@pytest.fixture
def collector():
    return CallbackCollector(default_timeout=0.5)


@pytest.fixture
def providers(beckn_config):
    return build_providers(beckn_config)
