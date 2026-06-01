"""Integration tests for the prediction_api FastAPI service."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


SAMPLE_PAYLOAD = {
    "transaction_id": "txn-test-001",
    "items": [
        {"id": "cheap_slow", "price": 900, "delivery_time_hours": 96, "risk_score": 0.6},
        {"id": "mid_balanced", "price": 1200, "delivery_time_hours": 48, "risk_score": 0.8},
        {"id": "premium_fast", "price": 1500, "delivery_time_hours": 24, "risk_score": 0.95},
    ],
}


def _inject_test_model(app):
    """Replacement for _load_model_from_mlflow used in tests."""
    from core.model import Phase2Scorer

    # Use known weights so we can predict the ranking deterministically.
    app.state.model = Phase2Scorer.from_weights([1.0, 0.5, 0.25], b=0.0)
    app.state.model.eval()
    app.state.model_version = "test-stub-v1"


@pytest.fixture
def client(monkeypatch):
    """TestClient with the MLflow loader patched out before lifespan runs."""
    from prediction_api import main as api_main

    monkeypatch.setattr(api_main, "_load_model_from_mlflow", _inject_test_model)
    with TestClient(api_main.app) as c:
        yield c


@pytest.fixture
def spy_client(monkeypatch):
    """TestClient that records every call to the patched loader."""
    from prediction_api import main as api_main

    calls = {"count": 0}

    def _spy_loader(app):
        calls["count"] += 1
        _inject_test_model(app)

    monkeypatch.setattr(api_main, "_load_model_from_mlflow", _spy_loader)
    with TestClient(api_main.app) as c:
        yield c, calls


@pytest.fixture
def fallback_client(monkeypatch):
    """TestClient where mlflow.pytorch.load_model raises so the fallback path runs."""
    import mlflow.pytorch
    from prediction_api import main as api_main

    def _raise(*args, **kwargs):
        raise RuntimeError("MLflow down")

    monkeypatch.setattr(mlflow.pytorch, "load_model", _raise)
    with TestClient(api_main.app) as c:
        yield c


class TestHealth:
    def test_health_returns_200(self, client):
        response = client.get("/health")
        assert response.status_code == 200

    def test_health_includes_model_version(self, client):
        body = client.get("/health").json()
        assert body["model_version"] == "test-stub-v1"

    def test_health_status_field_ok(self, client):
        body = client.get("/health").json()
        assert body["status"] == "ok"

    def test_health_service_field(self, client):
        body = client.get("/health").json()
        assert body["service"] == "comparative-scoring-phase2"


class TestScore:
    def test_score_returns_200(self, client):
        response = client.post("/score", json=SAMPLE_PAYLOAD)
        assert response.status_code == 200

    def test_score_has_recommended_and_ranked_list(self, client):
        body = client.post("/score", json=SAMPLE_PAYLOAD).json()
        assert "recommended" in body
        assert "ranked_list" in body

    def test_score_ranked_list_length_matches_input(self, client):
        body = client.post("/score", json=SAMPLE_PAYLOAD).json()
        assert len(body["ranked_list"]) == len(SAMPLE_PAYLOAD["items"])

    def test_score_ranked_list_descending(self, client):
        body = client.post("/score", json=SAMPLE_PAYLOAD).json()
        scores = [entry["score"] for entry in body["ranked_list"]]
        assert scores == sorted(scores, reverse=True)

    def test_score_ranks_are_1_indexed_consecutive(self, client):
        body = client.post("/score", json=SAMPLE_PAYLOAD).json()
        ranks = [entry["rank"] for entry in body["ranked_list"]]
        assert ranks == [1, 2, 3]

    def test_score_recommended_matches_top_of_ranked_list(self, client):
        body = client.post("/score", json=SAMPLE_PAYLOAD).json()
        assert body["recommended"]["id"] == body["ranked_list"][0]["item"]["id"]

    def test_score_recommended_id_is_cheap_slow(self, client):
        body = client.post("/score", json=SAMPLE_PAYLOAD).json()
        # With weights [1.0, 0.5, 0.25] the price feature dominates and
        # cheap_slow (x_price=1.0) wins.
        assert body["recommended"]["id"] == "cheap_slow"

    def test_score_model_version_propagates(self, client):
        body = client.post("/score", json=SAMPLE_PAYLOAD).json()
        assert body["model_version"] == "test-stub-v1"

    def test_score_pipeline_field(self, client):
        body = client.post("/score", json=SAMPLE_PAYLOAD).json()
        assert body["pipeline"] == "phase2_ranknet"

    def test_score_empty_items_returns_400(self, client):
        response = client.post("/score", json={"items": [], "transaction_id": "txn-empty"})
        assert response.status_code == 400

    def test_score_missing_items_returns_422(self, client):
        response = client.post("/score", json={})
        assert response.status_code == 422

    def test_score_invalid_price_returns_422(self, client):
        bad_payload = {
            "items": [
                {"id": "bad_price", "price": "", "delivery_time_hours": 24, "risk_score": 0.5},
            ],
        }
        response = client.post("/score", json=bad_payload)
        assert response.status_code == 422

    def test_score_accepts_currency_price(self, client):
        payload = {
            "transaction_id": "txn-currency",
            "items": [
                {"id": "a", "price": "₹ 1,200", "delivery_time_hours": 48, "risk_score": 0.7},
                {"id": "b", "price": "₹ 900", "delivery_time_hours": 72, "risk_score": 0.6},
            ],
        }
        response = client.post("/score", json=payload)
        assert response.status_code == 200
        body = response.json()
        prices = {entry["item"]["id"]: entry["item"]["price"] for entry in body["ranked_list"]}
        assert prices["a"] == pytest.approx(1200.0)
        assert prices["b"] == pytest.approx(900.0)


class TestReload:
    def test_reload_returns_200_and_model_version(self, client):
        response = client.post("/reload")
        assert response.status_code == 200
        body = response.json()
        assert "model_version" in body
        assert body["status"] == "reloaded"

    def test_reload_invokes_loader_again(self, spy_client):
        c, calls = spy_client
        # Baseline: lifespan triggered exactly one call on startup.
        assert calls["count"] == 1
        response = c.post("/reload")
        assert response.status_code == 200
        assert calls["count"] == 2


class TestFallback:
    def test_fallback_when_mlflow_unreachable(self, fallback_client):
        health = fallback_client.get("/health")
        assert health.status_code == 200
        assert "fallback-static-weights" in health.json()["model_version"]

        score_response = fallback_client.post("/score", json=SAMPLE_PAYLOAD)
        assert score_response.status_code == 200
        body = score_response.json()
        assert "recommended" in body
        assert "ranked_list" in body
        assert len(body["ranked_list"]) == len(SAMPLE_PAYLOAD["items"])
        assert body["pipeline"] == "phase2_ranknet"


class TestValidation:
    def test_score_request_with_extra_fields_allowed(self, client):
        payload = {
            "transaction_id": "txn-extras",
            "items": [
                {
                    "id": "with_extras",
                    "price": 1000,
                    "delivery_time_hours": 48,
                    "risk_score": 0.7,
                    "warranty_months": 12,
                },
                {
                    "id": "plain",
                    "price": 1100,
                    "delivery_time_hours": 36,
                    "risk_score": 0.8,
                    "warranty_months": 6,
                },
            ],
        }
        response = client.post("/score", json=payload)
        assert response.status_code == 200

    def test_score_request_with_alt_keys_via_endpoint(self, client):
        # features.py tolerates "price_value" but CatalogItem requires "price";
        # the endpoint must reject the alt-key payload at the schema layer.
        payload = {
            "items": [
                {"id": "alt", "price_value": 1000, "delivery_time_hours": 48, "risk_score": 0.7},
            ],
        }
        response = client.post("/score", json=payload)
        assert response.status_code == 422
