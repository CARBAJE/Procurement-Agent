"""Integration test fixtures for the data-normalizer service.

The test DB is bootstrapped two ways (in order of preference):

  1. testcontainers.postgres.PostgresContainer — preferred. Spins up a fresh
     Postgres 16 container per session, applies database/sql/*.sql in order,
     and tears down at the end. Requires Docker on the host.

  2. Local Postgres on $TEST_DB_HOST/$TEST_DB_PORT — fallback when
     testcontainers is unavailable. The test session creates schema
     `dn_integration_test` (drop-and-recreate) and applies the SQL there.
     Set USE_LOCAL_PG=1 to force this path.

A `clean_db` fixture TRUNCATEs every audit-relevant table between tests so
state never bleeds across cases. The order respects FK dependencies.
"""
from __future__ import annotations

import asyncio
import importlib
import os
import pathlib
import sys
from contextlib import asynccontextmanager

import asyncpg
import pytest
import pytest_asyncio
from aiohttp.test_utils import TestClient, TestServer

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
SQL_DIR = REPO_ROOT / "database" / "sql"

# Tables to TRUNCATE between tests, ordered child → parent so FK CASCADE
# trimming does the right thing.
_TRUNCATE_TABLES = [
    "audit_trail_events",
    "erp_sync_records",
    "purchase_orders",
    "approval_decisions",
    "negotiation_outcomes",
    "scored_offers",
    "seller_offerings",
    "discovery_queries",
    "beckn_intents",
    "parsed_intents",
    "procurement_requests",
    "bpp",
    # users is intentionally NOT truncated — _ensure_system_user expects the
    # system user row to survive between tests. We delete it once on shutdown.
]


# ── DB bootstrap helpers ──────────────────────────────────────────────────────

async def _ensure_database_exists(dsn: str) -> None:
    """Create the target DB if it doesn't exist (local-PG fallback only).

    Connects to the server-level `postgres` DB to issue CREATE DATABASE since
    asyncpg requires a connection to do anything.
    """
    from urllib.parse import urlparse, urlunparse
    parsed = urlparse(dsn)
    target_db = (parsed.path or "/").lstrip("/")
    if not target_db:
        return
    admin_parsed = parsed._replace(path="/postgres")
    admin_dsn = urlunparse(admin_parsed)
    conn = await asyncpg.connect(admin_dsn)
    try:
        exists = await conn.fetchval(
            "SELECT 1 FROM pg_database WHERE datname = $1", target_db,
        )
        if not exists:
            await conn.execute(f'CREATE DATABASE "{target_db}"')
    finally:
        await conn.close()


async def _apply_schema(dsn: str) -> None:
    """Run every database/sql/*.sql in lexicographic order against `dsn`."""
    await _ensure_database_exists(dsn)
    conn = await asyncpg.connect(dsn)
    try:
        for sql_file in sorted(SQL_DIR.glob("*.sql")):
            sql = sql_file.read_text()
            try:
                await conn.execute(sql)
            except asyncpg.exceptions.DuplicateObjectError:
                # Re-running schema in a session that already has the types.
                pass
    finally:
        await conn.close()


def _testcontainer_dsn():
    """Try to start a Postgres testcontainer. Return DSN or None."""
    try:
        from testcontainers.postgres import PostgresContainer
    except ImportError:
        return None, None
    try:
        container = PostgresContainer("postgres:16-alpine")
        container.start()
    except Exception:
        return None, None
    dsn = container.get_connection_url().replace("postgresql+psycopg2://", "postgresql://")
    return dsn, container


def _local_pg_dsn():
    """Build DSN against a local Postgres. Returns dsn or None if disabled."""
    host = os.getenv("TEST_DB_HOST", "localhost")
    port = os.getenv("TEST_DB_PORT", "5432")
    user = os.getenv("TEST_DB_USER", os.getenv("USER", ""))
    password = os.getenv("TEST_DB_PASSWORD", "")
    db = os.getenv("TEST_DB_NAME", "procurement_agent_test")
    if not user:
        return None
    if password:
        return f"postgresql://{user}:{password}@{host}:{port}/{db}"
    return f"postgresql://{user}@{host}:{port}/{db}"


# ── Pytest hooks ──────────────────────────────────────────────────────────────

def pytest_configure(config):
    """Set DB_* env vars before DataNormalizer imports its db module."""
    use_local = os.getenv("USE_LOCAL_PG") == "1"
    dsn = None
    container = None

    if not use_local:
        dsn, container = _testcontainer_dsn()

    if dsn is None:
        dsn = _local_pg_dsn()
        if dsn is None:
            pytest.skip(
                "No DB available. Either install Docker for testcontainers or "
                "set TEST_DB_USER / TEST_DB_NAME for the local fallback.",
                allow_module_level=True,
            )

    # Parse DSN into DB_* env vars consumed by DataNormalizer.db.get_pool.
    from urllib.parse import urlparse
    parsed = urlparse(dsn)
    os.environ["DB_HOST"]     = parsed.hostname or "localhost"
    os.environ["DB_PORT"]     = str(parsed.port or 5432)
    os.environ["DB_USER"]     = parsed.username or ""
    os.environ["DB_PASSWORD"] = parsed.password or ""
    os.environ["DB_NAME"]     = (parsed.path or "/postgres").lstrip("/")

    config._dn_dsn = dsn
    config._dn_container = container


def pytest_unconfigure(config):
    container = getattr(config, "_dn_container", None)
    if container is not None:
        try:
            container.stop()
        except Exception:
            pass


# ── Async session-scoped pool ─────────────────────────────────────────────────

@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def schema_applied(request):
    """Apply all SQL files once per session."""
    dsn = request.config._dn_dsn
    await _apply_schema(dsn)
    yield dsn


@pytest_asyncio.fixture(scope="function")
async def db_pool(schema_applied):
    """Fresh asyncpg pool per test function.

    Also resets DataNormalizer.db._pool so the service-side singleton is
    rebuilt against the current event loop. Without this, the second test
    inherits a pool bound to a closed loop and asyncpg blows up with
    "Event loop is closed".
    """
    import DataNormalizer.db as db_mod
    db_mod._pool = None

    pool = await asyncpg.create_pool(
        dsn=schema_applied, min_size=1, max_size=4,
    )
    yield pool
    await pool.close()


@pytest_asyncio.fixture
async def clean_db(db_pool):
    """TRUNCATE all audit-relevant tables before each test."""
    async with db_pool.acquire() as conn:
        await conn.execute(
            "TRUNCATE TABLE " + ", ".join(_TRUNCATE_TABLES) + " CASCADE"
        )
    yield


@pytest_asyncio.fixture
async def client(clean_db):
    """aiohttp TestClient wrapping the data-normalizer create_app().

    The service-side DataNormalizer.db._pool was nulled by db_pool, so the
    first /normalize/* call inside this test creates a fresh pool on the
    current event loop.
    """
    sys.path.insert(0, str(REPO_ROOT / "services" / "data-normalizer"))
    # Drop any cached handler import so create_app rebuilds against current state.
    sys.modules.pop("src.handler", None)
    from src.handler import create_app  # type: ignore  # noqa: E402

    app = create_app()
    async with TestClient(TestServer(app)) as c:
        yield c

    import DataNormalizer.db as db_mod
    if db_mod._pool is not None:
        await db_mod.close_pool()
