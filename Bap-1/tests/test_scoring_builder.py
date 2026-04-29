"""Unit tests for the _build_scoring helper in src.server.

The shape produced here is what the Comparison UI renders. It must remain
stable (multi-criterion-ready) so a future Comparison Engine swap doesn't
require frontend changes.
"""
from __future__ import annotations

from src.beckn.models import DiscoverOffering
from src.server import _build_scoring


def _offer(pid: str, price: str, name: str = "X") -> DiscoverOffering:
    return DiscoverOffering(
        bpp_id=f"bpp.{pid}",
        bpp_uri=f"http://{pid}.test",
        provider_id=pid,
        provider_name=name,
        item_id=f"item-{pid}",
        item_name=f"Item {pid}",
        price_value=price,
        price_currency="INR",
    )


def test_empty_offerings_produces_empty_scoring():
    result = _build_scoring([], recommended_item_id=None)
    assert result == {"recommended_item_id": None, "criteria": [], "ranking": []}


def test_scoring_shape_is_multicriterion_ready():
    offerings = [_offer("a", "100"), _offer("b", "150")]
    result = _build_scoring(offerings, recommended_item_id="item-a")
    # Top-level shape
    assert "criteria" in result
    assert "ranking" in result
    # Criterion shape
    price_crit = result["criteria"][0]
    assert price_crit["key"] == "price"
    assert price_crit["direction"] == "min"
    assert "weight" in price_crit
    assert "label" in price_crit
    # Per-offering score shape
    for row in price_crit["scores"]:
        assert {"item_id", "raw", "normalized", "explanation"} <= row.keys()


def test_cheapest_has_normalized_score_1_and_most_expensive_0():
    offerings = [_offer("a", "100"), _offer("b", "150"), _offer("c", "200")]
    result = _build_scoring(offerings, recommended_item_id="item-a")
    scores = {s["item_id"]: s["normalized"] for s in result["criteria"][0]["scores"]}
    assert scores["item-a"] == 1.0
    assert scores["item-c"] == 0.0
    assert 0.0 < scores["item-b"] < 1.0


def test_ranking_is_sorted_by_composite_score_desc():
    offerings = [_offer("a", "200"), _offer("b", "100"), _offer("c", "150")]
    result = _build_scoring(offerings, recommended_item_id="item-b")
    ranking = result["ranking"]
    assert [r["item_id"] for r in ranking] == ["item-b", "item-c", "item-a"]
    assert [r["rank"] for r in ranking] == [1, 2, 3]


def test_recommended_item_id_echoed_at_top_level():
    offerings = [_offer("a", "100")]
    result = _build_scoring(offerings, recommended_item_id="item-a")
    assert result["recommended_item_id"] == "item-a"


def test_cheapest_explanation_labels_it_as_cheapest():
    offerings = [_offer("a", "100"), _offer("b", "150")]
    result = _build_scoring(offerings, recommended_item_id="item-a")
    scores = {s["item_id"]: s for s in result["criteria"][0]["scores"]}
    assert scores["item-a"]["explanation"] == "Cheapest option"
    assert "above cheapest" in scores["item-b"]["explanation"]


def test_identical_prices_do_not_divide_by_zero():
    offerings = [_offer("a", "100"), _offer("b", "100")]
    result = _build_scoring(offerings, recommended_item_id="item-a")
    # Both normalized to 1.0 (no spread → cheapest everywhere).
    normalizeds = [s["normalized"] for s in result["criteria"][0]["scores"]]
    assert normalizeds == [1.0, 1.0]
