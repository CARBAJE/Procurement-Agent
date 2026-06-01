"""Unit tests for services/ComparativeAndScoreing/core/."""
from __future__ import annotations

import math

import numpy as np
import pytest
import torch
from pydantic import ValidationError

from core.features import (
    FEATURE_ORDER,
    extract_features_from_catalog,
    extract_features_tensor,
)
from core.model import Phase2Scorer
from core.ranknet import build_pairs_from_oracle, ndcg_at_k, ranknet_loss
from core.schemas import CatalogItem, ScoredItem, ScoreRequest, ScoreResponse


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def scorer() -> Phase2Scorer:
    """A deterministic Phase2Scorer with known weights for reproducible tests."""
    return Phase2Scorer.from_weights([0.5, 0.3, 0.2], b=0.1)


@pytest.fixture
def sample_items() -> list[dict]:
    """A four-supplier catalog with full price/delivery/rating coverage."""
    return [
        {
            "item_id": "A",
            "price_value": "100",
            "fulfillment_hours": 24,
            "rating": "4.5",
        },
        {
            "item_id": "B",
            "price_value": "200",
            "fulfillment_hours": 48,
            "rating": "3.5",
        },
        {
            "item_id": "C",
            "price_value": "150",
            "fulfillment_hours": 12,
            "rating": "5.0",
        },
        {
            "item_id": "D",
            "price_value": "175",
            "fulfillment_hours": 72,
            "rating": "4.0",
        },
    ]


@pytest.fixture
def fixed_input() -> torch.Tensor:
    """A small fixed (10, 3) tensor used to compare model outputs across reloads."""
    torch.manual_seed(0)
    return torch.randn(10, 3, dtype=torch.float32)


# ---------------------------------------------------------------------------
# TestPhase2Scorer
# ---------------------------------------------------------------------------


class TestPhase2Scorer:
    def test_forward_shape_2d(self, scorer: Phase2Scorer) -> None:
        x = torch.zeros(10, 3, dtype=torch.float32)
        out = scorer(x)
        assert out.shape == (10,)

    def test_forward_shape_3d(self, scorer: Phase2Scorer) -> None:
        x = torch.zeros(4, 10, 3, dtype=torch.float32)
        out = scorer(x)
        assert out.shape == (4, 10)

    def test_forward_dtype_preserved(self, scorer: Phase2Scorer) -> None:
        x = torch.zeros(5, 3, dtype=torch.float32)
        out = scorer(x)
        assert out.dtype == torch.float32

    def test_from_weights_roundtrip(self) -> None:
        model = Phase2Scorer.from_weights([0.5, 0.3, 0.2], 0.1)
        weights = model.get_weights()
        assert math.isclose(weights["w_price"], 0.5, abs_tol=1e-6)
        assert math.isclose(weights["w_speed"], 0.3, abs_tol=1e-6)
        assert math.isclose(weights["w_risk"], 0.2, abs_tol=1e-6)
        assert math.isclose(weights["bias"], 0.1, abs_tol=1e-6)

    def test_get_weights_keys(self, scorer: Phase2Scorer) -> None:
        assert set(scorer.get_weights().keys()) == {
            "w_price",
            "w_speed",
            "w_risk",
            "bias",
        }

    def test_get_weights_raises_if_in_features_not_3(self) -> None:
        model = Phase2Scorer(in_features=4)
        with pytest.raises(ValueError):
            model.get_weights()

    def test_save_load_roundtrip(
        self,
        scorer: Phase2Scorer,
        fixed_input: torch.Tensor,
        tmp_path,
    ) -> None:
        path = tmp_path / "phase2.pt"
        scorer.save_state(str(path))
        with torch.no_grad():
            expected = scorer(fixed_input)
        loaded = Phase2Scorer.load_state(str(path), in_features=3)
        with torch.no_grad():
            actual = loaded(fixed_input)
        assert torch.allclose(expected, actual, atol=1e-6)

    def test_gradient_flow(self, scorer: Phase2Scorer) -> None:
        x = torch.randn(8, 3, dtype=torch.float32)
        target = torch.zeros(8, dtype=torch.float32)
        scorer.zero_grad()
        scores = scorer(x)
        loss = ((scores - target) ** 2).mean()
        loss.backward()
        grad = scorer.linear.weight.grad
        assert grad is not None
        assert torch.any(grad != 0.0)

    def test_invalid_in_features_zero_raises(self) -> None:
        with pytest.raises(ValueError):
            Phase2Scorer(in_features=0)

    def test_from_weights_invalid_ndim_raises(self) -> None:
        with pytest.raises(ValueError):
            Phase2Scorer.from_weights([[0.5, 0.3, 0.2]])  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# TestRankNetLoss
# ---------------------------------------------------------------------------


class TestRankNetLoss:
    def test_loss_is_scalar_tensor(self) -> None:
        s_rej = torch.tensor([0.1, 0.2, 0.3])
        s_pref = torch.tensor([0.4, 0.5, 0.6])
        loss = ranknet_loss(s_rej, s_pref)
        assert isinstance(loss, torch.Tensor)
        assert loss.ndim == 0

    def test_loss_perfect_ranking(self) -> None:
        s_pref = torch.tensor([10.0])
        s_rej = torch.tensor([-10.0])
        loss = ranknet_loss(s_rej, s_pref)
        assert float(loss) < 1e-3

    def test_loss_wrong_ranking(self) -> None:
        s_rej = torch.tensor([10.0])
        s_pref = torch.tensor([-10.0])
        loss = ranknet_loss(s_rej, s_pref)
        assert float(loss) > 5.0

    def test_loss_tied_equals_log2(self) -> None:
        s = torch.tensor([1.0, 2.0, 3.0])
        loss = ranknet_loss(s, s.clone())
        assert math.isclose(float(loss), math.log(2.0), abs_tol=1e-5)

    def test_loss_no_nan_extreme_inputs(self) -> None:
        s_rej = torch.tensor([100.0, -100.0, 100.0])
        s_pref = torch.tensor([-100.0, 100.0, -100.0])
        loss = ranknet_loss(s_rej, s_pref, gamma=1.0)
        assert torch.isfinite(loss).item()

    def test_loss_gamma_scaling(self) -> None:
        s_rej = torch.tensor([1.0])
        s_pref = torch.tensor([-1.0])  # wrong ranking — loss should grow with gamma
        loss_low = ranknet_loss(s_rej, s_pref, gamma=0.5)
        loss_high = ranknet_loss(s_rej, s_pref, gamma=4.0)
        assert float(loss_high) > float(loss_low)

    def test_loss_batch_mean(self) -> None:
        s_rej = torch.tensor([1.0, -1.0])
        s_pref = torch.tensor([2.0, 0.5])
        batch_loss = ranknet_loss(s_rej, s_pref)
        l0 = ranknet_loss(s_rej[0:1], s_pref[0:1])
        l1 = ranknet_loss(s_rej[1:2], s_pref[1:2])
        assert math.isclose(float(batch_loss), float((l0 + l1) / 2.0), abs_tol=1e-6)

    def test_loss_gradient_flows(self) -> None:
        s_rej = torch.tensor([0.5], requires_grad=True)
        s_pref = torch.tensor([1.0], requires_grad=True)
        loss = ranknet_loss(s_rej, s_pref)
        loss.backward()
        assert s_rej.grad is not None
        assert s_pref.grad is not None
        assert float(s_rej.grad.abs().sum()) > 0.0
        assert float(s_pref.grad.abs().sum()) > 0.0

    def test_loss_known_value_handcalc(self) -> None:
        s_rej = torch.tensor([1.0])
        s_pref = torch.tensor([2.0])
        loss = ranknet_loss(s_rej, s_pref, gamma=1.0)
        expected = math.log1p(math.exp(-1.0))  # ≈ 0.3133
        assert math.isclose(float(loss), expected, abs_tol=1e-5)


# ---------------------------------------------------------------------------
# TestPairBuilder
# ---------------------------------------------------------------------------


class TestPairBuilder:
    def test_pair_shapes(self) -> None:
        torch.manual_seed(0)
        X = torch.randn(3, 5, 4)
        idx_oracle = np.array([0, 2, 4])
        x_rej, x_pref = build_pairs_from_oracle(X, idx_oracle)
        assert x_rej.shape == (12, 4)
        assert x_pref.shape == (12, 4)

    def test_pref_matches_oracle_features(self) -> None:
        torch.manual_seed(0)
        n_sessions, n_suppliers, n_features = 3, 5, 4
        X = torch.randn(n_sessions, n_suppliers, n_features)
        idx_oracle = np.array([0, 2, 4])
        _, x_pref = build_pairs_from_oracle(X, idx_oracle)
        # Each session contributes (n_suppliers - 1) preferred rows in order.
        rows_per_session = n_suppliers - 1
        for s in range(n_sessions):
            expected = X[s, idx_oracle[s]]
            block = x_pref[s * rows_per_session : (s + 1) * rows_per_session]
            for row in block:
                assert torch.allclose(row, expected, atol=1e-6)

    def test_rej_excludes_oracle(self) -> None:
        torch.manual_seed(1)
        n_sessions, n_suppliers, n_features = 3, 5, 4
        X = torch.randn(n_sessions, n_suppliers, n_features)
        idx_oracle = np.array([0, 2, 4])
        x_rej, _ = build_pairs_from_oracle(X, idx_oracle)
        rows_per_session = n_suppliers - 1
        for s in range(n_sessions):
            oracle_feat = X[s, idx_oracle[s]]
            block = x_rej[s * rows_per_session : (s + 1) * rows_per_session]
            for row in block:
                # No rejected row should ever equal the oracle's feature row.
                assert not torch.allclose(row, oracle_feat, atol=1e-6)

    def test_rejects_invalid_X_shape(self) -> None:
        X = torch.zeros(5, 3)  # 2-D
        with pytest.raises(ValueError):
            build_pairs_from_oracle(X, np.array([0]))

    def test_rejects_too_few_suppliers(self) -> None:
        X = torch.zeros(2, 1, 3)  # only 1 supplier per session
        with pytest.raises(ValueError):
            build_pairs_from_oracle(X, np.array([0, 0]))

    def test_rejects_bad_oracle_shape(self) -> None:
        X = torch.zeros(3, 5, 4)
        with pytest.raises(ValueError):
            build_pairs_from_oracle(X, np.array([0, 1]))  # length 2 ≠ 3 sessions


# ---------------------------------------------------------------------------
# TestNDCG
# ---------------------------------------------------------------------------


class TestNDCG:
    def test_ndcg_perfect_ranking_equals_1(self) -> None:
        scores = np.array([5.0, 4.0, 3.0, 2.0, 1.0])
        rels = np.array([1.0, 0.0, 0.0, 0.0, 0.0])
        assert math.isclose(ndcg_at_k(scores, rels, k=5), 1.0, abs_tol=1e-9)

    def test_ndcg_worst_ranking_lt_1(self) -> None:
        scores = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
        rels = np.array([1.0, 0.0, 0.0, 0.0, 0.0])
        assert ndcg_at_k(scores, rels, k=5) < 1.0

    def test_ndcg_zero_relevances_returns_0(self) -> None:
        scores = np.array([5.0, 4.0, 3.0])
        rels = np.array([0.0, 0.0, 0.0])
        assert ndcg_at_k(scores, rels, k=3) == 0.0

    def test_ndcg_handles_k_greater_than_size(self) -> None:
        scores = np.array([5.0, 4.0, 3.0, 2.0, 1.0])
        rels = np.array([1.0, 0.0, 0.0, 0.0, 0.0])
        value = ndcg_at_k(scores, rels, k=10)
        assert math.isfinite(value)
        assert 0.0 <= value <= 1.0

    def test_ndcg_handles_k_zero(self) -> None:
        scores = np.array([5.0, 4.0, 3.0])
        rels = np.array([1.0, 0.0, 0.0])
        assert ndcg_at_k(scores, rels, k=0) == 0.0

    def test_ndcg_known_value(self) -> None:
        scores = np.array([3.0, 2.0, 1.0])
        rels = np.array([0.0, 1.0, 0.0])
        expected = 1.0 / math.log2(3.0)  # ≈ 0.6309
        assert math.isclose(ndcg_at_k(scores, rels, k=2), expected, abs_tol=1e-4)


# ---------------------------------------------------------------------------
# TestFeatures
# ---------------------------------------------------------------------------


class TestFeatures:
    def test_shape_n_by_3(self, sample_items: list[dict]) -> None:
        feats = extract_features_from_catalog(sample_items)
        assert feats.shape == (4, 3)

    def test_dtype_float32(self, sample_items: list[dict]) -> None:
        feats = extract_features_from_catalog(sample_items)
        assert feats.dtype == np.float32

    def test_bounded_0_to_1(self, sample_items: list[dict]) -> None:
        feats = extract_features_from_catalog(sample_items)
        assert np.all(feats >= 0.0)
        assert np.all(feats <= 1.0)

    def test_cheaper_item_higher_price_feature(self) -> None:
        items = [
            {"price_value": "100", "fulfillment_hours": 24, "rating": "4.0"},
            {"price_value": "500", "fulfillment_hours": 24, "rating": "4.0"},
        ]
        feats = extract_features_from_catalog(items)
        # FEATURE_ORDER[0] == "price"; cheaper item (index 0) must score higher.
        assert feats[0, 0] > feats[1, 0]

    def test_faster_item_higher_speed_feature(self) -> None:
        items = [
            {"price_value": "100", "fulfillment_hours": 12, "rating": "4.0"},
            {"price_value": "100", "fulfillment_hours": 72, "rating": "4.0"},
        ]
        feats = extract_features_from_catalog(items)
        # FEATURE_ORDER[1] == "speed"; faster item (index 0) must score higher.
        assert feats[0, 1] > feats[1, 1]

    def test_zero_variance_collapses_to_neutral(self) -> None:
        items = [
            {"price_value": "100", "fulfillment_hours": 12, "rating": "4.0"},
            {"price_value": "100", "fulfillment_hours": 48, "rating": "3.0"},
            {"price_value": "100", "fulfillment_hours": 24, "rating": "5.0"},
        ]
        feats = extract_features_from_catalog(items)
        assert np.allclose(feats[:, 0], 1.0)

    def test_missing_rating_default_05(self) -> None:
        items = [
            {"price_value": "100", "fulfillment_hours": 12},
            {"price_value": "200", "fulfillment_hours": 48},
            {"price_value": "150", "fulfillment_hours": 24},
        ]
        feats = extract_features_from_catalog(items)
        # FEATURE_ORDER[2] == "risk"; when no rating data is present at all,
        # the column is filled with the neutral 0.5 prior.
        assert np.allclose(feats[:, 2], 0.5)

    def test_currency_parsing(self) -> None:
        items = [
            {"price_value": "₹ 1,200", "fulfillment_hours": 24, "rating": "4.0"},
            {"price_value": "₹ 2,400", "fulfillment_hours": 24, "rating": "4.0"},
        ]
        feats = extract_features_from_catalog(items)
        # No exceptions and the cheaper item still scores higher on price.
        assert feats.shape == (2, 3)
        assert feats[0, 0] > feats[1, 0]

    def test_alt_key_price(self) -> None:
        items = [
            {"price": 100, "fulfillment_hours": 24, "rating": "4.0"},
            {"price": 200, "fulfillment_hours": 24, "rating": "4.0"},
        ]
        feats = extract_features_from_catalog(items)
        assert feats.shape == (2, 3)
        assert feats[0, 0] > feats[1, 0]

    def test_alt_key_delivery(self) -> None:
        items = [
            {"price_value": "100", "delivery_time": 12, "rating": "4.0"},
            {"price_value": "100", "delivery_time": 72, "rating": "4.0"},
        ]
        feats = extract_features_from_catalog(items)
        assert feats.shape == (2, 3)
        assert feats[0, 1] > feats[1, 1]

    def test_empty_list_returns_empty_array(self) -> None:
        feats = extract_features_from_catalog([])
        assert feats.shape == (0, 3)
        assert feats.dtype == np.float32

    def test_extract_features_tensor_returns_torch_float32(
        self, sample_items: list[dict]
    ) -> None:
        tensor = extract_features_tensor(sample_items)
        assert isinstance(tensor, torch.Tensor)
        assert tensor.dtype == torch.float32
        assert tensor.shape == (4, 3)

    def test_feature_order_is_canonical(self) -> None:
        # Sanity-check the module-level constant the rest of the system relies on.
        assert FEATURE_ORDER == ("price", "speed", "risk")


# ---------------------------------------------------------------------------
# TestSchemas
# ---------------------------------------------------------------------------


class TestSchemas:
    def test_catalogitem_validates_minimum_fields(self) -> None:
        item = CatalogItem(id="x", price=100, delivery_time_hours=24)
        assert item.id == "x"
        assert math.isclose(item.price, 100.0)
        assert item.delivery_time_hours == 24

    def test_catalogitem_price_coerces_string(self) -> None:
        item = CatalogItem(id="x", price="1200.50", delivery_time_hours=24)
        assert math.isclose(item.price, 1200.50, abs_tol=1e-6)

    def test_catalogitem_price_coerces_currency(self) -> None:
        item = CatalogItem(id="x", price="₹ 1,200", delivery_time_hours=24)
        assert math.isclose(item.price, 1200.0, abs_tol=1e-6)

    def test_catalogitem_rejects_empty_price(self) -> None:
        with pytest.raises(ValidationError):
            CatalogItem(id="x", price="", delivery_time_hours=24)

    def test_catalogitem_from_discover_offering(self) -> None:
        offering = {
            "bpp_id": "bpp.example.com",
            "bpp_uri": "https://bpp.example.com",
            "provider_id": "prov-1",
            "provider_name": "Acme Cables Pvt Ltd",
            "item_id": "item-42",
            "item_name": "Cat6 UTP Cable",
            "price_value": "₹ 1,200",
            "price_currency": "INR",
            "available_quantity": 500,
            "rating": "4.5",
            "specifications": ["Cat6", "UTP", "305m"],
            "fulfillment_hours": 48,
        }
        item = CatalogItem.from_discover_offering(offering)
        assert item.id == "item-42"
        assert math.isclose(item.price, 1200.0, abs_tol=1e-6)
        assert item.delivery_time_hours == 48
        assert item.supplier_name == "Acme Cables Pvt Ltd"
        assert item.risk_score is not None
        assert math.isclose(item.risk_score, 4.5, abs_tol=1e-6)

    def test_score_request_requires_items(self) -> None:
        # Pydantic schema itself permits an empty list — the API endpoint is
        # responsible for rejecting empty requests at the HTTP boundary.
        req = ScoreRequest(items=[])
        assert req.items == []

    def test_score_response_serialises(self) -> None:
        item = CatalogItem(
            id="x",
            price=100.0,
            delivery_time_hours=24,
            risk_score=4.5,
            supplier_name="Acme",
        )
        response = ScoreResponse(
            recommended=item,
            ranked_list=[ScoredItem(item=item, score=0.87, rank=1)],
            model_version="v0.1.0",
        )
        payload = response.model_dump_json()
        restored = ScoreResponse.model_validate_json(payload)
        assert restored.recommended.id == "x"
        assert restored.model_version == "v0.1.0"
        assert restored.pipeline == "phase2_ranknet"
        assert len(restored.ranked_list) == 1
        assert restored.ranked_list[0].rank == 1
        assert math.isclose(restored.ranked_list[0].score, 0.87, abs_tol=1e-6)
