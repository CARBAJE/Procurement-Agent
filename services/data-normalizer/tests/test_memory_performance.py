"""Memory performance and ground truth validation tests.

Validates two Phase 3 acceptance criteria:
  1. ANN search latency P99 < 100ms (under representative load with warm model)
  2. Similarity search returns the correct provider for known query→provider pairs

Requires a live PostgreSQL + pgvector DB with the schema applied.
Run with: pytest tests/test_memory_performance.py -v -m integration
"""
from __future__ import annotations

import time

import pytest
import pytest_asyncio
from aiohttp.test_utils import TestClient

# ── Catalog fixtures (from orchestrator._LOCAL_CATALOG) ──────────────────────

_CATALOG_TRANSACTIONS = [
    {
        "item_text":      "A4 Paper 80gsm Ream 500 sheets standard",
        "provider_name":  "PaperDirect India",
        "price":          168.0,
        "currency":       "INR",
        "delivery_hours": 48,
    },
    {
        "item_text":      "A4 Paper 80gsm office grade trusted brand",
        "provider_name":  "OfficeWorld Supplies",
        "price":          195.0,
        "currency":       "INR",
        "delivery_hours": 24,
    },
    {
        "item_text":      "A4 Paper Premium 80gsm high brightness acid-free",
        "provider_name":  "Stationery Hub",
        "price":          218.0,
        "currency":       "INR",
        "delivery_hours": 72,
    },
    {
        "item_text":      "A4 Paper Eco 80gsm 100 percent recycled FSC certified",
        "provider_name":  "GreenLeaf Papers",
        "price":          182.0,
        "currency":       "INR",
        "delivery_hours": 96,
    },
    {
        "item_text":      "A4 Paper 80gsm Express same-day dispatch",
        "provider_name":  "QuickPrint Depot",
        "price":          205.0,
        "currency":       "INR",
        "delivery_hours": 24,
    },
    {
        "item_text":      "A4 Paper Basic 80gsm budget-friendly bulk",
        "provider_name":  "Budget Paper Co",
        "price":          165.0,
        "currency":       "INR",
        "delivery_hours": 120,
    },
]

# 14 additional items for a realistic 20-record dataset (latency test)
_EXTRA_TRANSACTIONS = [
    {"item_text": f"A4 Paper 80gsm batch {i}", "provider_name": f"ExtraSupplier{i}",
     "price": 160.0 + i * 5, "currency": "INR", "delivery_hours": 48}
    for i in range(14)
]


@pytest_asyncio.fixture
async def memory_preloaded(client: TestClient):
    """Write 6 catalog transactions so ground truth tests have data to search."""
    for tx in _CATALOG_TRANSACTIONS:
        r = await client.post("/normalize/memory/write", json=tx)
        assert r.status == 201, f"Failed to seed: {tx['provider_name']}"
    yield


@pytest_asyncio.fixture
async def memory_full_dataset(client: TestClient):
    """Write 20 transactions (6 catalog + 14 extra) for the latency test."""
    for tx in _CATALOG_TRANSACTIONS + _EXTRA_TRANSACTIONS:
        r = await client.post("/normalize/memory/write", json=tx)
        assert r.status == 201
    yield


# ── Latency test ─────────────────────────────────────────────────────────────

@pytest.mark.integration
async def test_search_latency_p99_under_100ms(client: TestClient, memory_full_dataset):
    """ANN search P99 latency must be < 100ms after model warm-up.

    The first embedding call downloads/loads the ONNX model (~2s on cold start).
    We discard that warm-up iteration and measure 20 subsequent calls.
    """
    query = {"item_text": "A4 paper 80gsm ream 500 sheets", "limit": 3}

    # Warm-up: load the fastembed ONNX model into memory
    warmup = await client.post("/normalize/memory/search", json=query)
    assert warmup.status == 200

    times_ms: list[float] = []
    for _ in range(20):
        t0 = time.perf_counter()
        resp = await client.post("/normalize/memory/search", json=query)
        elapsed_ms = (time.perf_counter() - t0) * 1000
        assert resp.status == 200
        times_ms.append(elapsed_ms)

    times_ms.sort()
    p50 = times_ms[9]
    p99 = times_ms[int(len(times_ms) * 0.99)]

    print(
        f"\nSearch latency (ms) over 20 iterations — "
        f"min={times_ms[0]:.1f}  p50={p50:.1f}  p99={p99:.1f}  max={times_ms[-1]:.1f}"
    )
    assert p99 < 100.0, (
        f"P99 latency {p99:.1f}ms exceeds the 100ms SLA required by Phase 3. "
        "Check pgvector HNSW index (migration 22) and DB connection pool sizing."
    )


# ── Ground truth similarity tests ────────────────────────────────────────────

@pytest.mark.integration
@pytest.mark.parametrize("query,expected_provider", [
    (
        "eco-friendly recycled A4 paper 100 percent green FSC",
        "GreenLeaf Papers",
    ),
    (
        "premium high brightness A4 acid-free FSC certified paper",
        "Stationery Hub",
    ),
    (
        "cheapest budget basic A4 paper bulk purchase",
        "Budget Paper Co",
    ),
    (
        "A4 paper express same-day fast quick delivery",
        "QuickPrint Depot",
    ),
])
async def test_ground_truth_similarity(
    query: str,
    expected_provider: str,
    client: TestClient,
    memory_preloaded,
):
    """Verify cosine similarity retrieves the correct provider for known semantic queries.

    Each query is crafted to be semantically unambiguous — the expected provider
    is the only one in the catalog with matching differentiating attributes
    (recycled, premium/FSC, budget, express).
    """
    resp = await client.post("/normalize/memory/search", json={
        "item_text": query,
        "limit":     1,
    })
    assert resp.status == 200
    body = await resp.json()

    assert body["count"] >= 1, (
        f"No results for query {query!r} — "
        "similarity might be below 0.75 threshold. "
        "Check that memory_preloaded fixture wrote all 6 catalog records."
    )
    got = body["results"][0]["provider_name"]
    sim = body["results"][0]["similarity"]
    assert got == expected_provider, (
        f"Expected {expected_provider!r} but got {got!r} "
        f"(similarity={sim:.3f}) for query: {query!r}"
    )
