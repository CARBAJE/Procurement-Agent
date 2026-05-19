"""Analytics microservice — GET /analytics

Owns the database connection and all reporting queries.
Falls back to deterministic mock data when the DB is unavailable or empty.

Environment variables:
  DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD
  PORT  (default 8006)
"""
from __future__ import annotations

import logging
import os

from aiohttp import web

logger = logging.getLogger(__name__)

DB_HOST     = os.getenv("DB_HOST",     "localhost")
DB_PORT     = int(os.getenv("DB_PORT", "5432"))
DB_NAME     = os.getenv("DB_NAME",     "procurement_agent")
DB_USER     = os.getenv("DB_USER",     "postgres")
DB_PASSWORD = os.getenv("DB_PASSWORD", "postgres123")

VALID_PERIODS = frozenset({"30d", "90d", "180d"})


# ── DB lifecycle ──────────────────────────────────────────────────────────────

async def _on_startup(app: web.Application) -> None:
    try:
        import asyncpg  # type: ignore
        pool = await asyncpg.create_pool(
            host=DB_HOST, port=DB_PORT, database=DB_NAME,
            user=DB_USER, password=DB_PASSWORD,
            min_size=1, max_size=10, command_timeout=15,
        )
        app["db_pool"] = pool
        logger.info("DB pool ready (%s@%s:%s/%s)", DB_USER, DB_HOST, DB_PORT, DB_NAME)
    except Exception as exc:
        logger.warning("DB unavailable (%s) — will serve mock data", exc)
        app["db_pool"] = None


async def _on_cleanup(app: web.Application) -> None:
    pool = app.get("db_pool")
    if pool is not None:
        await pool.close()
        logger.info("DB pool closed")


# ── Handlers ──────────────────────────────────────────────────────────────────

async def health(request: web.Request) -> web.Response:
    pool = request.app.get("db_pool")
    return web.json_response({
        "status": "ok",
        "db": "connected" if pool is not None else "unavailable",
    })


async def analytics(request: web.Request) -> web.Response:
    period = request.query.get("period", "90d")
    if period not in VALID_PERIODS:
        period = "90d"

    pool = request.app.get("db_pool")
    if pool is not None:
        try:
            from queries import fetch_analytics
            data = await fetch_analytics(pool, period)
            if data is not None:
                return web.json_response(data)
        except Exception as exc:
            logger.warning("DB query failed (%s) — serving mock data", exc)

    from mock import generate_mock_analytics
    return web.json_response(generate_mock_analytics(period))


# ── App factory ───────────────────────────────────────────────────────────────

def create_app() -> web.Application:
    app = web.Application()
    app.on_startup.append(_on_startup)
    app.on_cleanup.append(_on_cleanup)
    app.router.add_get("/health",    health)
    app.router.add_get("/analytics", analytics)
    return app


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    port = int(os.getenv("PORT", "8006"))
    web.run_app(create_app(), host="0.0.0.0", port=port)
