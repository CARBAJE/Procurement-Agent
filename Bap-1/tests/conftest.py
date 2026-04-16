import pytest

from src.beckn.adapter import BecknProtocolAdapter
from src.beckn.callbacks import CallbackCollector
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
    )


@pytest.fixture
def adapter(beckn_config):
    return BecknProtocolAdapter(beckn_config)


@pytest.fixture
def collector():
    return CallbackCollector(default_timeout=0.5)
