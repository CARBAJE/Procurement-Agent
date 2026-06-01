"""E2E API tests — FastAPI ``/negotiate`` entrypoint.

Uses :class:`fastapi.testclient.TestClient` to exercise the full
HTTP layer plus the LangGraph runtime end-to-end. The TestClient
runs the FastAPI app inside an ``httpx`` shim and triggers the
:func:`src.main.lifespan` hook on context entry — so these tests
also pin the lifespan startup path (graph compile + broker task
spawn, both tolerant of a missing Redis instance).

Assertions:

* ``POST /negotiate`` returns **202 Accepted** with a valid ``thread_id``.
* The graph parks at ``wait_for_async_callback`` for transactional
  categories — ``paused_at`` in the response surfaces the node name.
* Advisory categories (e.g. IT equipment) terminate synchronously
  inside the request and return a ``final_outcome`` instead.
* The ``GET /negotiate/{txn}`` inspector returns the checkpointed
  state for a session that was just started.
* ``GET /healthz`` and ``GET /readyz`` work.

The TestClient is constructed once per test inside a ``with`` block
so each test gets a fresh lifespan + graph + (graceful) broker task.
"""
from __future__ import annotations

import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient

from src.main import app


# ── Fixtures ──────────────────────────────────────────────────────────────


@pytest.fixture
def client() -> Any:
    """Yield a TestClient that has fully gone through lifespan startup."""
    with TestClient(app) as c:
        yield c


def _commodity_payload(transaction_id: str | None = None) -> dict:
    """A canonical commodity-category request body that drives the graph to
    the ``wait_for_async_callback`` interrupt."""
    body: dict = {
        "category": "commodity",
        "ranked_offers": [
            {
                "provider_id": "bpp_acme",
                "item_id": "cable-cat6",
                "price": 100.0,
                "currency": "INR",
                "delivery_hours": 72,
                "quantity": 10,
                "score": 0.91,
                "round_received": 0,
            }
        ],
        "policy": {"budget_unit_price": 90.0, "hitl_gap_pct": 0.15},
        "max_rounds": 3,
    }
    if transaction_id is not None:
        body["transaction_id"] = transaction_id
    return body


def _advisory_payload(transaction_id: str | None = None) -> dict:
    """An advisory (IT equipment) request that finalises synchronously."""
    body: dict = {
        "category": "it_equipment",
        "ranked_offers": [
            {
                "provider_id": "bpp_lenovo",
                "item_id": "laptop-tp-x1",
                "price": 50000.0,
                "currency": "INR",
                "delivery_hours": 168,
                "quantity": 5,
                "score": 0.88,
                "round_received": 0,
            }
        ],
        "policy": {"budget_unit_price": 45000.0},
    }
    if transaction_id is not None:
        body["transaction_id"] = transaction_id
    return body


# ── Ops endpoints ────────────────────────────────────────────────────────


def test_healthz_returns_ok(client: TestClient) -> None:
    """Liveness probe is unconditional."""
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readyz_reports_graph_state(client: TestClient) -> None:
    """Readiness probe confirms the LangGraph was compiled in the lifespan."""
    response = client.get("/readyz")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    # The remaining keys describe the runtime — values depend on env
    # configuration but the keys must be present for ops dashboards.
    assert "tracing_enabled" in body
    assert "langchain_project" in body
    assert "kafka_configured" in body
    assert "postgres_configured" in body


# ── /negotiate happy path ────────────────────────────────────────────────


def test_negotiate_returns_202_with_thread_id(client: TestClient) -> None:
    """The headline assertion from the implementation brief."""
    response = client.post("/negotiate", json=_commodity_payload())
    assert response.status_code == 202, response.text

    body = response.json()
    assert body["status"] == "accepted"
    assert isinstance(body["thread_id"], str)
    assert body["thread_id"].startswith("txn-")
    # No final outcome yet — the graph parked at the async callback.
    assert body["final_outcome"] is None


def test_negotiate_parks_at_wait_for_async_callback(client: TestClient) -> None:
    """Commodity request drives the graph to ``wait_for_async_callback``."""
    response = client.post("/negotiate", json=_commodity_payload())
    body = response.json()
    assert body["paused_at"] == "wait_for_async_callback", (
        f"Expected pause at wait_for_async_callback, got {body['paused_at']}"
    )
    # The interrupt envelope is structured so the broker can resume.
    interrupt = body["interrupt"]
    assert interrupt is not None
    assert interrupt["type"] == "negotiation.awaiting_on_select"
    assert "Waiting for /on_select" in interrupt["message"]
    assert interrupt["correlation_id"] == body["thread_id"]


def test_negotiate_uses_provided_transaction_id(client: TestClient) -> None:
    """An explicit transaction_id is preserved and surfaced as thread_id."""
    txn = f"txn-explicit-{uuid.uuid4()}"
    response = client.post("/negotiate", json=_commodity_payload(transaction_id=txn))
    assert response.status_code == 202
    assert response.json()["thread_id"] == txn


def test_negotiate_response_returns_quickly(client: TestClient) -> None:
    """The endpoint must not block — placeholder nodes run in milliseconds.

    We don't have a real timer threshold here (CI variance), but the
    structural promise is that the response arrives without hanging on
    external I/O. The lifespan's broker task may have failed to connect
    to Redis (no Redis in CI), but the request path must be untouched.
    """
    import time

    t0 = time.perf_counter()
    response = client.post("/negotiate", json=_commodity_payload())
    elapsed_s = time.perf_counter() - t0
    assert response.status_code == 202
    # Generous ceiling — typical run is < 100ms even on cold CI.
    assert elapsed_s < 5.0, f"endpoint took {elapsed_s:.2f}s — should be < 5s"


# ── /negotiate advisory category ─────────────────────────────────────────


def test_negotiate_advisory_category_finalises_synchronously(
    client: TestClient,
) -> None:
    """IT equipment routes through ``evaluate_ambiguous_terms`` → ``finalize``.

    The graph never parks for this category — the endpoint returns 202
    with ``paused_at: None`` and a stamped ``final_outcome``.
    """
    response = client.post("/negotiate", json=_advisory_payload())
    assert response.status_code == 202

    body = response.json()
    assert body["paused_at"] is None
    assert body["interrupt"] is None
    # OPENAI_API_KEY is unset in CI so the advisory node returns a
    # placeholder and stamps ``escalated`` as the terminal outcome.
    assert body["final_outcome"] in {"escalated", "advisory_only", "accepted"}


# ── /negotiate validation ────────────────────────────────────────────────


def test_negotiate_rejects_empty_ranked_offers(client: TestClient) -> None:
    """Pydantic ``min_length=1`` on ranked_offers blocks empty requests."""
    bad = _commodity_payload()
    bad["ranked_offers"] = []
    response = client.post("/negotiate", json=bad)
    assert response.status_code == 422


def test_negotiate_rejects_missing_category(client: TestClient) -> None:
    """Category is required."""
    bad = _commodity_payload()
    del bad["category"]
    response = client.post("/negotiate", json=bad)
    assert response.status_code == 422


def test_negotiate_rejects_invalid_max_rounds(client: TestClient) -> None:
    """G4 — max_rounds ≤ 5 enforced at the API layer too."""
    bad = _commodity_payload()
    bad["max_rounds"] = 99
    response = client.post("/negotiate", json=bad)
    assert response.status_code == 422


def test_negotiate_rejects_unknown_fields(client: TestClient) -> None:
    """``extra='forbid'`` rejects unexpected top-level fields."""
    bad = _commodity_payload()
    bad["arbitrary_field"] = "should be rejected"
    response = client.post("/negotiate", json=bad)
    assert response.status_code == 422


# ── /negotiate/{transaction_id} inspector ────────────────────────────────


def test_get_negotiation_returns_paused_state(client: TestClient) -> None:
    """After POST /negotiate, the inspector returns the parked checkpoint."""
    txn = f"txn-inspect-{uuid.uuid4()}"
    started = client.post("/negotiate", json=_commodity_payload(transaction_id=txn))
    assert started.status_code == 202

    response = client.get(f"/negotiate/{txn}")
    assert response.status_code == 200
    body = response.json()
    assert body["thread_id"] == txn
    assert "wait_for_async_callback" in body["next"]
    assert body["final_outcome"] is None
    assert body["current_counter_offer"] is not None
    # We expect at least three audit events: analyze, compute, guardrail.
    assert body["audit_event_count"] >= 3


def test_get_negotiation_returns_404_for_unknown(client: TestClient) -> None:
    """Inspecting a never-started thread_id returns 404."""
    response = client.get(f"/negotiate/never-existed-{uuid.uuid4()}")
    assert response.status_code == 404
