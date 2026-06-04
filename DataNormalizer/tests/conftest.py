"""Shared fixtures for DataNormalizer unit tests.

These are pure unit tests — no Postgres required. `asyncpg.create_pool` and the
acquired `Connection` are replaced with AsyncMocks that mimic the methods the
repos call (`fetchrow`, `execute`, `transaction`). Each test programs the mock
return values to exercise specific code paths.
"""
from __future__ import annotations

import pathlib
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import pytest

import DataNormalizer.db as db_module
from DataNormalizer.repositories import (
    audit_repo,
    discovery_repo,
    intent_repo,
    order_repo,
    request_repo,
    scoring_repo,
)


@pytest.fixture
def mock_conn():
    """A mocked asyncpg.Connection with fetchrow/execute/transaction stubs."""
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value=None)
    conn.execute = AsyncMock(return_value="UPDATE 1")

    @asynccontextmanager
    async def _transaction():
        yield

    conn.transaction = MagicMock(side_effect=_transaction)
    return conn


@pytest.fixture
def mock_pool(mock_conn):
    """Mocked asyncpg.Pool whose acquire() yields mock_conn."""
    pool = MagicMock()

    @asynccontextmanager
    async def _acquire():
        yield mock_conn

    pool.acquire = MagicMock(side_effect=_acquire)
    return pool


_UNIT_TESTS_DIR = pathlib.Path(__file__).resolve().parent


@pytest.fixture(autouse=True)
def patch_db_pool(request, monkeypatch, mock_pool):
    """Replace get_pool in every repo's local namespace — only for tests in
    THIS directory (unit tests). When the integration suite under
    services/data-normalizer/tests/ is collected in the same pytest run, we
    must NOT patch its DB calls or its real-DB tests will silently hit mocks.

    Each repo does `from ..db import get_pool` which binds the name into its
    own module, so patching db_module.get_pool alone has no effect — we have
    to replace the binding inside each repo too.
    """
    test_file = pathlib.Path(request.fspath).resolve()
    if _UNIT_TESTS_DIR not in test_file.parents:
        yield
        return

    async def _get_pool():
        return mock_pool
    monkeypatch.setattr(db_module, "get_pool", _get_pool)
    for mod in (request_repo, intent_repo, discovery_repo,
                scoring_repo, order_repo, audit_repo):
        monkeypatch.setattr(mod, "get_pool", _get_pool)
    yield
