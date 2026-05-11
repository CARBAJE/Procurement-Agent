"""Shared pytest fixtures for the ComparativeAndScoreing test suite.

Per the project convention (CLAUDE.md), tests use pytest-asyncio with
`asyncio_mode = auto` — declared in `pytest.ini`. Module-level config import
(`os.getenv` inside `_Config`) is refreshed inside each MLOps test via
`dataclasses.replace`; this conftest does not mutate module-level config so
tests can be run individually or as a suite without ordering side effects.
"""
from __future__ import annotations

import numpy as np
import pytest
import torch


# ---------------------------------------------------------------------------
# Determinism — autouse so every test starts from a known RNG state.
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _deterministic_seeds():
    """Reset numpy and torch global RNG state before each test.

    Tests that need their own controlled randomness should still pass an
    explicit seed to `np.random.default_rng(...)` rather than relying on
    the global state — this fixture is a safety net, not a contract.
    """
    np.random.seed(42)
    torch.manual_seed(42)
    yield


# ---------------------------------------------------------------------------
# Convenience fixtures — shared payloads / synthetic data.
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_catalog_payload() -> dict:
    """A canonical 3-item /score request body usable by any API or feature test."""
    return {
        "transaction_id": "txn-fixture-001",
        "items": [
            {"id": "i1", "price": 1200.0, "delivery_time_hours": 48, "risk_score": 0.85},
            {"id": "i2", "price":  980.0, "delivery_time_hours": 72, "risk_score": 0.70},
            {"id": "i3", "price": 1400.0, "delivery_time_hours": 24, "risk_score": 0.95},
        ],
    }


@pytest.fixture
def synthetic_session_batch() -> tuple[torch.Tensor, np.ndarray]:
    """Small (N=4, n_suppliers=5, n_features=3) tensor + oracle indices.

    Suitable for unit-testing RankNet pair construction and NDCG evaluation
    without invoking the full training pipeline. Deterministic via local
    `np.random.default_rng(0)` — independent of the autouse global seed.
    """
    rng = np.random.default_rng(0)
    X = torch.from_numpy(
        rng.uniform(0.1, 1.0, size=(4, 5, 3)).astype(np.float32)
    )
    idx_oracle = np.array([0, 2, 4, 1], dtype=np.int64)
    return X, idx_oracle
