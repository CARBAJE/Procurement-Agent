"""Unit + integration tests for the multi-network discovery service.

Three headline scenarios from the implementation brief:

* **Scenario A** — all networks respond perfectly; aggregation produces
  the full unioned/deduplicated catalog.
* **Scenario B** — Network A times out; Network B responds; the service
  returns ``degraded=true`` with Network B's items and a structured
  failure entry for Network A.
* **Scenario C** — every network fails (timeout + connection refused);
  the service returns an empty ``items`` list and structured failures
  for every network, *without* raising.

Supporting tests pin:

* Deduplication by normalised tax-id + name signature.
* Geographic-proximity deduplication when tax-ids are absent.
* Circuit breaker trip on N consecutive failures.
* :func:`src.resilience.default_network_caller` Beckn-payload parser.
* The FastAPI ``POST /search/multi-network`` endpoint surface.

All tests use **dependency injection** — a fake :class:`NetworkCaller`
that returns canned items, raises, or sleeps past the timeout.
``aiohttp`` is never actually called.
"""
from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable, Mapping

import aiohttp
import pytest
from fastapi.testclient import TestClient

from src.aggregator import ResultAggregator, _haversine_km, _normalize_tax_id, _normalize_text
from src.coordinator import MultiNetworkCoordinator
from src.models import (
    AggregatedItem,
    CatalogItem,
    IntentPayload,
    NetworkFailure,
    NetworkGateway,
    NetworkResult,
    NetworkStatus,
)
from src.resilience import (
    CircuitBreaker,
    CircuitState,
    ResilienceManager,
    default_network_caller,
)


# ─────────────────────────────────────────────────────────────────────────
# Fake infrastructure
# ─────────────────────────────────────────────────────────────────────────


#: Script action types accepted by FakeNetworkCaller.
Action = list[CatalogItem] | BaseException | str


class FakeNetworkCaller:
    """Configurable async network caller.

    The ``scripts`` dict maps gateway name to one of:

    * ``list[CatalogItem]`` — return these items normally.
    * ``BaseException`` — raise this exception when called.
    * ``"timeout"`` — sleep past the gateway's ``timeout_s``.
    * ``"timeout_long"`` — sleep effectively forever.

    Records every invocation in ``call_log`` for ordering assertions.
    """

    def __init__(self, scripts: Mapping[str, Action]) -> None:
        self.scripts = dict(scripts)
        self.call_log: list[str] = []

    async def __call__(
        self,
        gateway: NetworkGateway,
        intent: dict[str, Any],
        session: Any,
    ) -> list[CatalogItem]:
        self.call_log.append(gateway.name)
        action = self.scripts.get(gateway.name)
        if action == "timeout":
            # Sleep ≥ 2× gateway timeout so wait_for fires reliably.
            await asyncio.sleep(gateway.timeout_s * 3 + 0.1)
            return []
        if action == "timeout_long":
            await asyncio.sleep(60.0)
            return []
        if isinstance(action, BaseException):
            raise action
        if isinstance(action, list):
            return action
        return []


def _gw(name: str, timeout_s: float = 0.1) -> NetworkGateway:
    """Build a NetworkGateway with a tight timeout (fast tests)."""
    return NetworkGateway(
        name=name, base_url=f"http://{name}.local", timeout_s=timeout_s
    )


def _item(
    *,
    name: str = "cat6 cable",
    price: float = 100.0,
    provider: str = "bpp_x",
    item_id: str | None = None,
    tax_id: str | None = "GST123",
    currency: str = "INR",
    delivery_hours: int | None = 72,
    quantity_available: int | None = 100,
    gps: str | None = None,
) -> CatalogItem:
    """Build a CatalogItem fixture with sensible defaults."""
    return CatalogItem(
        provider_id=provider,
        item_id=item_id or f"{provider}-{name.replace(' ', '-')}",
        name=name,
        price=price,
        currency=currency,
        delivery_hours=delivery_hours,
        quantity_available=quantity_available,
        tax_id=tax_id,
        location_coordinates=gps,
    )


def _build_coordinator(
    gateways: list[NetworkGateway],
    *,
    scripts: Mapping[str, Action] | None = None,
    failure_threshold: int = 3,
    recovery_timeout_s: float = 30.0,
) -> tuple[MultiNetworkCoordinator, FakeNetworkCaller]:
    """Compose a coordinator wired to a FakeNetworkCaller for unit tests."""
    caller = FakeNetworkCaller(scripts or {})
    resilience = ResilienceManager(
        gateways,
        failure_threshold=failure_threshold,
        recovery_timeout_s=recovery_timeout_s,
        network_caller=caller,
    )
    aggregator = ResultAggregator(geo_proximity_km=0.5)
    # The FakeNetworkCaller ignores the session, so any non-None object
    # satisfies the runtime check.
    sentinel_session: Any = object()
    coordinator = MultiNetworkCoordinator(
        gateways,
        resilience=resilience,
        aggregator=aggregator,
        session=sentinel_session,
    )
    return coordinator, caller


# ─────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────


@pytest.fixture
def gateways() -> list[NetworkGateway]:
    return [_gw("network_a"), _gw("network_b")]


@pytest.fixture
def intent() -> IntentPayload:
    return IntentPayload(item_name="cat6 cable", quantity=10)


# ─────────────────────────────────────────────────────────────────────────
# Scenario A — all networks respond
# ─────────────────────────────────────────────────────────────────────────


async def test_scenario_a_all_networks_respond_with_distinct_items(
    gateways: list[NetworkGateway], intent: IntentPayload
) -> None:
    """Both networks return items with **different** suppliers — no dedup,
    full aggregation."""
    coord, caller = _build_coordinator(
        gateways,
        scripts={
            "network_a": [_item(provider="bpp_acme", tax_id="GST-A-001")],
            "network_b": [_item(provider="bpp_brick", tax_id="GST-B-002")],
        },
    )
    result = await coord.search(intent)

    assert result.degraded is False
    assert sorted(result.responded_networks) == ["network_a", "network_b"]
    assert result.failed_networks == []
    assert len(result.items) == 2
    # Both networks were called.
    assert sorted(caller.call_log) == ["network_a", "network_b"]
    # Per-network latency populated for every network.
    assert set(result.per_network_latency_ms) == {"network_a", "network_b"}


async def test_scenario_a_aggregation_deduplicates_same_supplier(
    gateways: list[NetworkGateway], intent: IntentPayload
) -> None:
    """Same supplier (same tax-id, same name) listed on both networks
    collapses into one AggregatedItem with both networks in ``sources``."""
    coord, _ = _build_coordinator(
        gateways,
        scripts={
            "network_a": [_item(price=100.0, provider="bpp_acme_A", tax_id="GST-X")],
            "network_b": [_item(price=95.0, provider="bpp_acme_B", tax_id="gst-x ")],
        },
    )
    result = await coord.search(intent)

    assert result.degraded is False
    assert len(result.items) == 1
    item = result.items[0]
    assert sorted(item.sources) == ["network_a", "network_b"]
    # The lower-priced entry wins as canonical.
    assert item.price == 95.0
    assert len(item.duplicate_keys) == 2


# ─────────────────────────────────────────────────────────────────────────
# Scenario B — Network A times out, Network B succeeds
# ─────────────────────────────────────────────────────────────────────────


async def test_scenario_b_network_a_times_out_b_succeeds(
    gateways: list[NetworkGateway], intent: IntentPayload
) -> None:
    """Graceful degradation: Network A timeout doesn't block Network B's items."""
    coord, caller = _build_coordinator(
        gateways,
        scripts={
            "network_a": "timeout",
            "network_b": [_item(provider="bpp_brick", tax_id="GST-B-002", price=95.0)],
        },
    )
    result = await coord.search(intent)

    assert result.degraded is True
    assert result.responded_networks == ["network_b"]
    assert len(result.failed_networks) == 1
    failure = result.failed_networks[0]
    assert failure.network == "network_a"
    assert failure.status == NetworkStatus.TIMEOUT
    assert "Timeout" in (failure.error or "")
    # Network B's items must be present.
    assert len(result.items) == 1
    assert result.items[0].provider_id == "bpp_brick"
    assert "network_b" in result.items[0].sources
    # Sanity: both networks were still attempted.
    assert sorted(caller.call_log) == ["network_a", "network_b"]


async def test_scenario_b_does_not_block_on_slowest_network(
    gateways: list[NetworkGateway], intent: IntentPayload
) -> None:
    """Wall-clock should be ≈ slowest network's timeout, NOT 60 s.

    Verifies the fan-out is genuinely concurrent and the per-network
    timeout bounds the slowest task.
    """
    # network_a sleeps 60 s without a timeout; network_b returns fast.
    coord, _ = _build_coordinator(
        gateways,
        scripts={
            "network_a": "timeout_long",
            "network_b": [_item()],
        },
    )
    import time as _time

    t0 = _time.monotonic()
    result = await coord.search(intent)
    elapsed_s = _time.monotonic() - t0

    # network_a's timeout is 0.1 s; the whole fan-out must finish in
    # well under 2 seconds even with CI jitter.
    assert elapsed_s < 2.0, f"Fan-out took {elapsed_s:.2f}s — concurrency broken"
    assert result.degraded is True


# ─────────────────────────────────────────────────────────────────────────
# Scenario C — all networks fail
# ─────────────────────────────────────────────────────────────────────────


async def test_scenario_c_all_networks_fail_returns_empty_response(
    gateways: list[NetworkGateway], intent: IntentPayload
) -> None:
    """When everything fails, the service emits a structured empty result —
    never raises."""
    coord, _ = _build_coordinator(
        gateways,
        scripts={
            "network_a": "timeout",
            "network_b": ConnectionError("ECONNREFUSED"),
        },
    )
    result = await coord.search(intent)

    assert result.degraded is True
    assert result.responded_networks == []
    assert len(result.failed_networks) == 2
    assert result.items == []

    failed_by_name = {f.network: f for f in result.failed_networks}
    assert failed_by_name["network_a"].status == NetworkStatus.TIMEOUT
    assert failed_by_name["network_b"].status == NetworkStatus.CONNECTION_REFUSED


async def test_scenario_c_mixed_failure_types(
    intent: IntentPayload,
) -> None:
    """Three networks, three different failure types — each is correctly typed."""
    gateways = [_gw("net_a"), _gw("net_b"), _gw("net_c")]
    coord, _ = _build_coordinator(
        gateways,
        scripts={
            "net_a": "timeout",
            "net_b": ConnectionError("ECONNREFUSED"),
            "net_c": aiohttp.ClientResponseError(
                request_info=None,  # type: ignore[arg-type]
                history=(),
                status=503,
                message="Service Unavailable",
            ),
        },
    )
    result = await coord.search(intent)

    statuses = {f.network: f.status for f in result.failed_networks}
    assert statuses["net_a"] == NetworkStatus.TIMEOUT
    assert statuses["net_b"] == NetworkStatus.CONNECTION_REFUSED
    assert statuses["net_c"] == NetworkStatus.UPSTREAM_5XX


# ─────────────────────────────────────────────────────────────────────────
# Deduplication
# ─────────────────────────────────────────────────────────────────────────


async def test_dedup_by_tax_id_survives_whitespace_and_case(
    gateways: list[NetworkGateway], intent: IntentPayload
) -> None:
    """Tax-id normalisation: ``" gst-123 "`` and ``"GST123"`` are the same."""
    coord, _ = _build_coordinator(
        gateways,
        scripts={
            "network_a": [_item(provider="bpp_a", tax_id=" gst-123 ", price=100.0)],
            "network_b": [_item(provider="bpp_b", tax_id="GST123", price=98.0)],
        },
    )
    result = await coord.search(intent)
    assert len(result.items) == 1
    assert sorted(result.items[0].sources) == ["network_a", "network_b"]


async def test_dedup_by_geographic_proximity_when_tax_id_missing(
    gateways: list[NetworkGateway], intent: IntentPayload
) -> None:
    """Same item name, no tax_id, GPS within 0.5 km → merged."""
    coord, _ = _build_coordinator(
        gateways,
        scripts={
            "network_a": [
                _item(provider="bpp_a", tax_id=None, gps="12.9716,77.5946", price=50.0)
            ],
            "network_b": [
                # ~120 metres away — well within the 0.5 km threshold.
                _item(provider="bpp_b", tax_id=None, gps="12.9720,77.5953", price=48.0)
            ],
        },
    )
    result = await coord.search(intent)
    assert len(result.items) == 1
    assert sorted(result.items[0].sources) == ["network_a", "network_b"]


async def test_no_dedup_when_locations_far_apart(
    gateways: list[NetworkGateway], intent: IntentPayload
) -> None:
    """Same name, no tax_id, GPS far apart → kept separate."""
    coord, _ = _build_coordinator(
        gateways,
        scripts={
            "network_a": [
                _item(provider="bpp_a", tax_id=None, gps="12.9716,77.5946", price=50.0)
            ],
            "network_b": [
                # Mumbai → ~840 km from Bangalore.
                _item(provider="bpp_b", tax_id=None, gps="19.0760,72.8777", price=48.0)
            ],
        },
    )
    result = await coord.search(intent)
    assert len(result.items) == 2


async def test_different_currencies_never_dedup(
    gateways: list[NetworkGateway], intent: IntentPayload
) -> None:
    """Same supplier + name across currencies → distinct items."""
    coord, _ = _build_coordinator(
        gateways,
        scripts={
            "network_a": [_item(provider="bpp_a", tax_id="GST-X", currency="INR")],
            "network_b": [_item(provider="bpp_a", tax_id="GST-X", currency="USD")],
        },
    )
    result = await coord.search(intent)
    assert len(result.items) == 2
    currencies = {i.currency for i in result.items}
    assert currencies == {"INR", "USD"}


# ─────────────────────────────────────────────────────────────────────────
# Circuit breaker
# ─────────────────────────────────────────────────────────────────────────


async def test_circuit_breaker_trips_after_consecutive_failures() -> None:
    """N failures → OPEN → next call fast-fails without invoking the network."""
    gw = _gw("flaky", timeout_s=0.1)
    coord, caller = _build_coordinator(
        [gw],
        scripts={"flaky": "timeout"},
        failure_threshold=2,
        recovery_timeout_s=60.0,
    )
    intent = IntentPayload(item_name="x")

    # Drive the breaker to OPEN: two consecutive timeouts.
    for _ in range(2):
        result = await coord.search(intent)
        assert result.failed_networks[0].status == NetworkStatus.TIMEOUT

    # Third call should be fast-failed by the breaker — the FakeCaller's
    # call_log should NOT grow because the resilience layer short-circuits.
    pre_count = len(caller.call_log)
    result = await coord.search(intent)
    post_count = len(caller.call_log)

    assert post_count == pre_count, "Breaker did not short-circuit the call"
    assert result.failed_networks[0].status == NetworkStatus.CIRCUIT_OPEN


async def test_circuit_breaker_success_clears_failure_count() -> None:
    """Recovering after a failure resets the counter — no trip on next failure."""
    breaker = CircuitBreaker(failure_threshold=3, recovery_timeout_s=1.0)
    await breaker.record_failure()
    await breaker.record_failure()
    assert breaker.state == CircuitState.CLOSED
    await breaker.record_success()
    assert breaker.failure_count == 0
    # A single failure now is not enough to trip.
    await breaker.record_failure()
    assert breaker.state == CircuitState.CLOSED


async def test_circuit_breaker_half_open_probe_failure_reopens() -> None:
    """HALF_OPEN probe failure trips back to OPEN immediately."""
    breaker = CircuitBreaker(failure_threshold=1, recovery_timeout_s=0.01)
    await breaker.record_failure()
    assert breaker.state == CircuitState.OPEN

    # Sleep past recovery_timeout_s; first allow_request flips to HALF_OPEN.
    await asyncio.sleep(0.05)
    assert await breaker.allow_request() is True
    assert breaker.state == CircuitState.HALF_OPEN

    # Probe fails — back to OPEN.
    await breaker.record_failure()
    assert breaker.state == CircuitState.OPEN


# ─────────────────────────────────────────────────────────────────────────
# default_network_caller — Beckn payload parsing
# ─────────────────────────────────────────────────────────────────────────


def test_default_network_caller_parses_beckn_catalog_shape() -> None:
    """Round-trip a Beckn ``/on_search`` envelope through the parser."""
    from src.resilience import _parse_beckn_catalog

    body = {
        "message": {
            "catalog": {
                "providers": [
                    {
                        "id": "bpp_acme",
                        "descriptor": {"tax_id": "GST-A-001"},
                        "items": [
                            {
                                "id": "item_1",
                                "descriptor": {"name": "Cat6 Cable"},
                                "price": {"value": "100.50", "currency": "INR"},
                                "quantity": {"available": {"count": 500}},
                                "location": {"gps": "12.9716,77.5946"},
                            }
                        ],
                    }
                ]
            }
        }
    }
    items = _parse_beckn_catalog(body, "network_a")
    assert len(items) == 1
    item = items[0]
    assert item.provider_id == "bpp_acme"
    assert item.item_id == "item_1"
    assert item.name == "Cat6 Cable"
    assert item.price == 100.5
    assert item.tax_id == "GST-A-001"
    assert item.location_coordinates == "12.9716,77.5946"


def test_default_network_caller_tolerates_malformed_items() -> None:
    """Malformed item dicts are skipped, not raised."""
    from src.resilience import _parse_beckn_catalog

    body = {
        "message": {
            "catalog": {
                "providers": [
                    {
                        "id": "bpp_acme",
                        "items": [
                            "not-a-dict",
                            {"id": "ok", "descriptor": {"name": "OK"}, "price": {"value": 1}},
                        ],
                    }
                ]
            }
        }
    }
    items = _parse_beckn_catalog(body, "network_a")
    assert len(items) == 1
    assert items[0].name == "OK"


# ─────────────────────────────────────────────────────────────────────────
# Normalisation helpers (pure)
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "raw, expected",
    [
        (" Cat-6  Cable ", "cat 6 cable"),
        ("Café", "cafe"),
        (None, ""),
        ("", ""),
        ("ALREADY_NORMALISED", "already_normalised"),
    ],
)
def test_normalize_text(raw: str | None, expected: str) -> None:
    assert _normalize_text(raw) == expected


@pytest.mark.parametrize(
    "raw, expected",
    [
        (" gst-123 ", "GST123"),
        ("GST-29ABCDE1234F1Z5", "GST29ABCDE1234F1Z5"),
        (None, ""),
        ("", ""),
    ],
)
def test_normalize_tax_id(raw: str | None, expected: str) -> None:
    assert _normalize_tax_id(raw) == expected


def test_haversine_within_500m() -> None:
    a = (12.9716, 77.5946)  # Bangalore landmark
    b = (12.9720, 77.5953)  # ~80 m away
    assert _haversine_km(a, b) < 0.5


def test_haversine_far_apart() -> None:
    a = (12.9716, 77.5946)  # Bangalore
    b = (19.0760, 72.8777)  # Mumbai
    assert 800.0 < _haversine_km(a, b) < 900.0


# ─────────────────────────────────────────────────────────────────────────
# Coordinator wiring guards
# ─────────────────────────────────────────────────────────────────────────


def test_coordinator_rejects_empty_gateway_list() -> None:
    """At least one gateway must be configured."""
    with pytest.raises(ValueError, match="At least one"):
        MultiNetworkCoordinator(
            [],
            resilience=ResilienceManager([]),
            aggregator=ResultAggregator(),
            session=object(),  # type: ignore[arg-type]
        )


async def test_coordinator_raises_without_session(
    gateways: list[NetworkGateway], intent: IntentPayload
) -> None:
    """Used outside ``async with`` and without an injected session → RuntimeError."""
    coord = MultiNetworkCoordinator(
        gateways,
        resilience=ResilienceManager(gateways),
        aggregator=ResultAggregator(),
        session=None,
    )
    with pytest.raises(RuntimeError, match="no aiohttp session"):
        await coord.search(intent)


# ─────────────────────────────────────────────────────────────────────────
# FastAPI endpoint
# ─────────────────────────────────────────────────────────────────────────


def test_healthz_returns_ok() -> None:
    """Liveness probe is unconditional."""
    from src.main import app

    with TestClient(app) as client:
        response = client.get("/healthz")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}


def test_readyz_lists_default_gateways() -> None:
    """Default config ships two networks — /readyz must surface them."""
    from src.main import app

    with TestClient(app) as client:
        response = client.get("/readyz")
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ready"
        assert body["gateway_count"] >= 2
        names = {g["name"] for g in body["gateways"]}
        assert {"network_a", "network_b"} <= names


def test_post_search_multi_network_returns_degraded_when_no_real_backend(
    mocker: Any,
) -> None:
    """Hit the live endpoint with the default config — both gateways unreachable.

    Verifies the API surface: 200 OK + degraded=true + empty items + two
    failure entries. Uses ``pytest-mock``'s ``mocker`` fixture to confirm
    the default ``aiohttp`` session was never patched out (sanity).
    """
    from src.main import app

    with TestClient(app) as client:
        payload = {"item_name": "cat6 cable", "quantity": 5}
        response = client.post("/search/multi-network", json=payload)
        assert response.status_code == 200, response.text
        body = response.json()
        # No real networks running at network-a.local — both fail.
        assert body["degraded"] is True
        assert body["items"] == []
        assert len(body["failed_networks"]) >= 2
        # Sanity on the failure shape.
        for failure in body["failed_networks"]:
            assert "network" in failure
            assert "status" in failure
            assert failure["status"] in {
                "timeout",
                "connection_refused",
                "upstream_5xx",
                "upstream_4xx",
                "invalid_response",
                "unknown_error",
                "circuit_open",
            }


def test_post_search_multi_network_validates_payload() -> None:
    """Pydantic rejects malformed intent payloads."""
    from src.main import app

    with TestClient(app) as client:
        # Missing required item_name.
        response = client.post("/search/multi-network", json={"quantity": 5})
        assert response.status_code == 422


# ─────────────────────────────────────────────────────────────────────────
# Aggregator unit-level edge cases
# ─────────────────────────────────────────────────────────────────────────


def test_aggregator_with_no_results_returns_empty() -> None:
    agg = ResultAggregator()
    items, ok, failures = agg.aggregate([])
    assert items == []
    assert ok == []
    assert failures == []


def test_aggregator_drops_failed_results() -> None:
    """Only OK results contribute to items; failures pass through structurally."""
    agg = ResultAggregator()
    results = [
        NetworkResult(network="a", status=NetworkStatus.OK, items=[_item()]),
        NetworkResult(network="b", status=NetworkStatus.TIMEOUT, error="x"),
    ]
    items, ok, failures = agg.aggregate(results)
    assert len(items) == 1
    assert [r.network for r in ok] == ["a"]
    assert len(failures) == 1
    assert failures[0].network == "b"
