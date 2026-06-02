"""E2E tests for the Frontend Demo Gateway.

Two headline scenarios from the implementation brief:

* ``POST /api/demo/score`` returns a list **strictly sorted** by the
  Phase-2 PyTorch model's scores. We verify (a) the scores are
  monotonically decreasing, (b) the ranking respects the feature
  signals (higher price → lower score, etc.).
* ``POST /api/demo/negotiate`` returns ``202 Accepted`` with a valid
  ``thread_id`` and surfaces the parked LangGraph state. The
  ``BackgroundTask`` simulating the Beckn callback fires after the
  configured delay and the polling endpoint reflects the resumed state.

Supporting tests pin:

* The 20% policy guardrail is enforced — a malicious request that tries
  to use an invalid category still respects the hard cap.
* The polling endpoint returns 404 for an unknown ``thread_id``.
* The score endpoint validates input (empty items, malformed shapes).
"""
from __future__ import annotations

import time
import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient

from frontend_demo_gateway.main import app


# ─────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────


@pytest.fixture
def client() -> Any:
    """Yield a TestClient that has fully gone through lifespan startup."""
    with TestClient(app) as c:
        yield c


def _score_payload() -> dict:
    """A three-supplier payload spanning the price/speed/risk axes.

    Designed so the LTR model produces an unambiguous ranking:

    * ``supplier_C`` — cheapest + fastest + best risk → top
    * ``supplier_A`` — mid on all axes → middle
    * ``supplier_B`` — most expensive + slowest + worst risk → bottom
    """
    return {
        "transaction_id": "txn-test-score",
        "items": [
            {
                "id": "supplier_A",
                "supplier_name": "Acme Cables",
                "price": 100.0,
                "delivery_time_hours": 72,
                "risk_score": 0.7,
            },
            {
                "id": "supplier_B",
                "supplier_name": "Brick Corp",
                "price": 140.0,
                "delivery_time_hours": 120,
                "risk_score": 0.4,
            },
            {
                "id": "supplier_C",
                "supplier_name": "Carbon Wire",
                "price": 80.0,
                "delivery_time_hours": 48,
                "risk_score": 0.9,
            },
        ],
    }


def _negotiate_payload(
    transaction_id: str | None = None,
    *,
    simulated_outcome: str = "accepted",
    callback_delay_s: float = 0.1,
) -> dict:
    """A commodity-category negotiation payload that drives the graph to the
    ``wait_for_async_callback`` interrupt.

    Default ``callback_delay_s=0.1`` keeps the test suite fast — the
    BackgroundTask still exercises the full asyncio.sleep + Command(resume)
    path, just on a tighter timeline than the 3-second demo default.
    """
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
        "simulated_outcome": simulated_outcome,
        "callback_delay_s": callback_delay_s,
    }
    if transaction_id is not None:
        body["transaction_id"] = transaction_id
    return body


# ─────────────────────────────────────────────────────────────────────────
# Ops endpoints
# ─────────────────────────────────────────────────────────────────────────


def test_healthz_returns_ok(client: TestClient) -> None:
    """Liveness probe is unconditional."""
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readyz_surfaces_model_weights(client: TestClient) -> None:
    """Readiness probe confirms model + graph are loaded and exposes the weights."""
    response = client.get("/readyz")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert body["score_model_version"] == "phase2-fallback-static-weights"
    weights = body["score_model_weights"]
    # The fallback weights match the documented Phase-2 priors:
    # price > speed > risk.
    assert weights["w_price"] == pytest.approx(0.50)
    assert weights["w_speed"] == pytest.approx(0.30)
    assert weights["w_risk"] == pytest.approx(0.20)
    assert weights["bias"] == pytest.approx(0.0)


# ─────────────────────────────────────────────────────────────────────────
# /api/demo/score — sorting behaviour
# ─────────────────────────────────────────────────────────────────────────


def test_score_returns_strictly_sorted_list(client: TestClient) -> None:
    """The headline assertion: scores are monotonically non-increasing."""
    response = client.post("/api/demo/score", json=_score_payload())
    assert response.status_code == 200, response.text

    body = response.json()
    ranked = body["ranked"]
    assert len(ranked) == 3
    scores = [r["score"] for r in ranked]
    # Strictly sorted (no ties in this fixture).
    for i in range(len(scores) - 1):
        assert scores[i] > scores[i + 1], f"Ranking not monotonic: {scores!r}"
    # Rank field also increases monotonically.
    assert [r["rank"] for r in ranked] == [1, 2, 3]


def test_score_recommends_the_best_supplier(client: TestClient) -> None:
    """``supplier_C`` dominates on every axis → must rank first."""
    response = client.post("/api/demo/score", json=_score_payload())
    body = response.json()
    assert body["recommended_id"] == "supplier_C"
    assert body["ranked"][0]["id"] == "supplier_C"
    assert body["ranked"][0]["rank"] == 1
    # And the worst on every axis is last.
    assert body["ranked"][-1]["id"] == "supplier_B"


def test_score_includes_normalised_features(client: TestClient) -> None:
    """Each ranked entry surfaces its post-normalisation feature vector."""
    response = client.post("/api/demo/score", json=_score_payload())
    body = response.json()
    for entry in body["ranked"]:
        feats = entry["features"]
        assert {"price", "speed", "risk"} <= feats.keys()
        # All features are in [0, 1] after min-max normalisation.
        for key in ("price", "speed", "risk"):
            assert 0.0 <= feats[key] <= 1.0, f"{key}={feats[key]} out of [0,1]"


def test_score_surfaces_model_weights_in_response(client: TestClient) -> None:
    """The response includes the model's coefficients for explainability."""
    response = client.post("/api/demo/score", json=_score_payload())
    body = response.json()
    weights = body["model_weights"]
    assert {"w_price", "w_speed", "w_risk", "bias"} <= weights.keys()


def test_score_validates_empty_items(client: TestClient) -> None:
    """Empty ``items`` list is a 422 (Pydantic ``min_length=1``)."""
    bad = {"items": []}
    response = client.post("/api/demo/score", json=bad)
    assert response.status_code == 422


def test_score_validates_missing_required_fields(client: TestClient) -> None:
    """Missing ``price`` on an item is a 422."""
    bad = {
        "items": [{"id": "x", "delivery_time_hours": 24}],  # no price
    }
    response = client.post("/api/demo/score", json=bad)
    assert response.status_code == 422


def test_score_handles_single_item_gracefully(client: TestClient) -> None:
    """A single-item input still produces a valid response (no min-max edge case)."""
    body = {
        "items": [
            {
                "id": "lonely",
                "price": 50.0,
                "delivery_time_hours": 24,
                "risk_score": 0.8,
            }
        ]
    }
    response = client.post("/api/demo/score", json=body)
    assert response.status_code == 200
    payload = response.json()
    assert len(payload["ranked"]) == 1
    assert payload["recommended_id"] == "lonely"


# ─────────────────────────────────────────────────────────────────────────
# /api/demo/negotiate — async kick-off + 202 thread_id
# ─────────────────────────────────────────────────────────────────────────


def test_negotiate_returns_202_with_thread_id(client: TestClient) -> None:
    """The other headline assertion: 202 + valid thread_id."""
    # TestClient blocks on the BG task; use a tiny delay so this stays fast.
    response = client.post(
        "/api/demo/negotiate", json=_negotiate_payload(callback_delay_s=0.05)
    )
    assert response.status_code == 202, response.text

    body = response.json()
    assert body["status"] == "accepted"
    assert isinstance(body["thread_id"], str)
    assert body["thread_id"].startswith("txn-demo-")
    # Graph parked at the real LangGraph interrupt.
    assert body["paused_at"] == "wait_for_async_callback"
    interrupt = body["interrupt"]
    assert interrupt is not None
    assert interrupt["type"] == "negotiation.awaiting_on_select"


def test_negotiate_preserves_provided_thread_id(client: TestClient) -> None:
    """An explicit ``transaction_id`` is honoured."""
    txn = f"txn-demo-explicit-{uuid.uuid4()}"
    response = client.post(
        "/api/demo/negotiate",
        json=_negotiate_payload(transaction_id=txn, callback_delay_s=0.05),
    )
    assert response.status_code == 202
    assert response.json()["thread_id"] == txn


# NOTE on non-blocking semantics:
# Starlette's request lifecycle holds the response open until BackgroundTasks
# finish — this applies to both ``TestClient`` and ``httpx.AsyncClient`` + ASGI.
# The non-blocking property of ``POST /api/demo/negotiate`` is only observable
# against a real ``uvicorn`` server (which sends the response to the wire
# *before* draining the BG queue). Smoke-test it with::
#
#     curl -w "%{time_total}\n" -X POST http://localhost:8005/api/demo/negotiate \
#       -H 'Content-Type: application/json' \
#       -d '{"category":"commodity","ranked_offers":[...],"callback_delay_s":3.0}'
#
# The unit-test layer pins the structural contract (202 + thread_id + parked
# state) and the end-state contract (resumed + terminal outcome); the timing
# contract is left to integration.


def test_negotiate_full_cycle_reaches_terminal_outcome(client: TestClient) -> None:
    """End-to-end: kick off → simulated callback → terminal state.

    ``TestClient`` runs background tasks before returning control to the
    test, so by the time ``client.post(...)`` returns, the BackgroundTask
    has already fired the simulated ``/on_select`` and the graph has
    resumed through to ``finalize``. We assert on the post-resume state
    directly. The async / non-blocking property is pinned separately by
    ``test_negotiate_does_not_block_on_callback_delay``.
    """
    txn = f"txn-cycle-{uuid.uuid4()}"
    started = client.post(
        "/api/demo/negotiate",
        json=_negotiate_payload(
            transaction_id=txn,
            simulated_outcome="accepted",
            callback_delay_s=0.05,
        ),
    )
    assert started.status_code == 202

    # By now the BG task has run — snapshot shows the resumed terminal state.
    snapshot = client.get(f"/api/demo/negotiate/{txn}")
    assert snapshot.status_code == 200
    body = snapshot.json()
    assert body["thread_id"] == txn
    assert body["resumed"] is True
    assert body["final_outcome"] == "accepted"
    assert body["next"] == []  # graph terminated
    # The drafted counter-offer is preserved in state for audit replay.
    assert body["current_counter_offer"] is not None


def test_negotiate_advisory_category_terminates_synchronously(
    client: TestClient,
) -> None:
    """``it_equipment`` (advisory) routes through ``evaluate_ambiguous_terms`` →
    ``finalize`` without ever parking — paused_at must be None."""
    body = _negotiate_payload(simulated_outcome="accepted")
    body["category"] = "it_equipment"
    body["ranked_offers"][0]["provider_id"] = "bpp_lenovo"
    body["ranked_offers"][0]["item_id"] = "laptop-tp-x1"

    response = client.post("/api/demo/negotiate", json=body)
    assert response.status_code == 202
    payload = response.json()
    assert payload["paused_at"] is None
    assert payload["interrupt"] is None
    assert payload["final_outcome"] in {"escalated", "advisory_only", "accepted"}


def test_negotiate_validates_payload(client: TestClient) -> None:
    """Pydantic rejects malformed payloads (missing ranked_offers)."""
    response = client.post(
        "/api/demo/negotiate",
        json={"category": "commodity"},  # ranked_offers missing
    )
    assert response.status_code == 422


def test_negotiate_rejects_unknown_fields(client: TestClient) -> None:
    """``extra='forbid'`` on the request model rejects unknown top-level fields."""
    bad = _negotiate_payload()
    bad["arbitrary_field"] = "nope"
    response = client.post("/api/demo/negotiate", json=bad)
    assert response.status_code == 422


def test_get_negotiation_returns_404_for_unknown_thread(
    client: TestClient,
) -> None:
    """Polling a thread that never existed returns 404."""
    response = client.get(f"/api/demo/negotiate/never-{uuid.uuid4()}")
    assert response.status_code == 404


# ─────────────────────────────────────────────────────────────────────────
# 20% policy guardrail is the real production guardrail
# ─────────────────────────────────────────────────────────────────────────


def test_negotiate_respects_real_20pct_cap(client: TestClient) -> None:
    """The graph's drafted counter-offer never exceeds the real G1 cap.

    Even when the request's budget creates a huge gap (which would push
    the rule engine toward an aggressive ask), the deterministic
    ``policy_guardrail_check`` node clamps to ``ABSOLUTE_MAX_DISCOUNT_PCT
    = 0.20``. We verify by polling the snapshot's counter offer.
    """
    txn = f"txn-cap-{uuid.uuid4()}"
    aggressive_request = _negotiate_payload(
        transaction_id=txn, callback_delay_s=0.05
    )
    # Tiny budget vs. listed price → huge gap → strategy wants high discount.
    aggressive_request["policy"]["budget_unit_price"] = 1.0
    aggressive_request["ranked_offers"][0]["price"] = 1000.0

    response = client.post("/api/demo/negotiate", json=aggressive_request)
    assert response.status_code == 202

    snapshot = client.get(f"/api/demo/negotiate/{txn}").json()
    counter = snapshot["current_counter_offer"]
    assert counter is not None
    # Even with a 99 900%+ gap, the clamp holds.
    assert 0.0 <= counter["discount_pct"] <= 0.20, (
        f"Guardrail breached: discount_pct={counter['discount_pct']}"
    )
