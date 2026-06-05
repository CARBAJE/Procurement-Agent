"""asyncpg connection pool — reads DB_* env vars."""
from __future__ import annotations

import logging
import os
from typing import Optional

import asyncpg

logger = logging.getLogger(__name__)

_pool: Optional[asyncpg.Pool] = None


async def get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(
            host=os.getenv("DB_HOST", "localhost"),
            port=int(os.getenv("DB_PORT", "5432")),
            database=os.getenv("DB_NAME", "procurement_agent"),
            user=os.getenv("DB_USER", ""),
            password=os.getenv("DB_PASSWORD", ""),
            min_size=2,
            max_size=10,
            command_timeout=30,
        )
        logger.info("asyncpg pool created → %s:%s/%s",
                    os.getenv("DB_HOST", "localhost"),
                    os.getenv("DB_PORT", "5432"),
                    os.getenv("DB_NAME", "procurement_agent"))
    return _pool


async def close_pool() -> None:
    global _pool
    if _pool:
        await _pool.close()
        _pool = None
        logger.info("asyncpg pool closed")
