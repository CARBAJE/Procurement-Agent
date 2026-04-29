"""asyncpg connection pool — initialized once at service startup."""
from __future__ import annotations

import asyncpg

from .config import (
    DB_CMD_TIMEOUT,
    DB_HOST,
    DB_MAX_POOL,
    DB_MIN_POOL,
    DB_NAME,
    DB_PASSWORD,
    DB_PORT,
    DB_SSL,
    DB_USER,
    HNSW_EF_SEARCH,
)

_pool: asyncpg.Pool | None = None


async def _on_connection_init(conn: asyncpg.Connection) -> None:
    """Run once per physical connection when it is created in the pool.

    Registers the pgvector codec and pins hnsw.ef_search so every ANN
    query on this connection uses the production recall setting.
    """
    from pgvector.asyncpg import register_vector  # type: ignore[import]

    await register_vector(conn)
    await conn.execute(f"SET hnsw.ef_search = {HNSW_EF_SEARCH}")


async def init_pool() -> None:
    """Create the pool. Called during application lifespan startup."""
    global _pool

    kwargs: dict = dict(
        host=DB_HOST,
        port=DB_PORT,
        database=DB_NAME,
        user=DB_USER,
        min_size=DB_MIN_POOL,
        max_size=DB_MAX_POOL,
        max_inactive_connection_lifetime=300,
        max_cached_statement_lifetime=600,
        command_timeout=DB_CMD_TIMEOUT,
        init=_on_connection_init,
    )
    if DB_PASSWORD:
        kwargs["password"] = DB_PASSWORD
    if DB_SSL != "disable":
        kwargs["ssl"] = DB_SSL

    _pool = await asyncpg.create_pool(**kwargs)


async def get_pool() -> asyncpg.Pool:
    """Return the pool, initialising it lazily if needed."""
    if _pool is None:
        await init_pool()
    return _pool


async def close_pool() -> None:
    """Gracefully drain and close all pool connections."""
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None
