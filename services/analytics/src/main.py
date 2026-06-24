"""Analytics microservice — GET /analytics

Owns the database connection and all reporting queries.
Falls back to deterministic mock data only when the DB is UNAVAILABLE (pool is
None or a query raises). A reachable-but-empty DB returns real zeros (live).

Environment variables:
  DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD
  PORT  (default 8009)
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

    # DB unreachable → honest error, never fabricated data. A reachable-but-empty
    # DB is NOT an error: fetch_analytics returns real zeros (data_source: live).
    if pool is None:
        logger.warning("DB pool unavailable — returning 503 (no mock data)")
        return web.json_response(
            {"error": "database_unavailable",
             "detail": "The analytics database is not reachable."},
            status=503,
        )

    try:
        from queries import fetch_analytics
        data = await fetch_analytics(pool, period)
        return web.json_response(data)
    except Exception as exc:
        logger.error("DB query failed (%s) — returning 503 (no mock data)", exc)
        return web.json_response(
            {"error": "database_query_failed", "detail": str(exc)},
            status=503,
        )


async def business_impact(request: web.Request) -> web.Response:
    period = request.query.get("period", "90d")
    if period not in VALID_PERIODS:
        period = "90d"

    pool = request.app.get("db_pool")
    if pool is None:
        return web.json_response(
            {"error": "database_unavailable"},
            status=503,
        )

    try:
        from queries import fetch_business_impact
        data = await fetch_business_impact(pool, period)
        return web.json_response(data)
    except Exception as exc:
        logger.error("business_impact query failed (%s)", exc)
        return web.json_response(
            {"error": "database_query_failed", "detail": str(exc)},
            status=503,
        )


async def benchmark(request: web.Request) -> web.Response:
    period = request.query.get("period", "90d")
    if period not in VALID_PERIODS:
        period = "90d"

    pool = request.app.get("db_pool")
    if pool is None:
        return web.json_response(
            {"error": "database_unavailable"},
            status=503,
        )

    try:
        from queries import fetch_benchmark
        data = await fetch_benchmark(pool, period)
        return web.json_response(data)
    except Exception as exc:
        logger.error("benchmark query failed (%s)", exc)
        return web.json_response(
            {"error": "database_query_failed", "detail": str(exc)},
            status=503,
        )


# ── App factory ───────────────────────────────────────────────────────────────

def create_app() -> web.Application:
    app = web.Application()
    app.on_startup.append(_on_startup)
    app.on_cleanup.append(_on_cleanup)
    app.router.add_get("/health",          health)
    app.router.add_get("/analytics",       analytics)
    app.router.add_get("/business-impact", business_impact)
    app.router.add_get("/benchmark",       benchmark)
    return app


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    port = int(os.getenv("PORT", "8009"))
    web.run_app(create_app(), host="0.0.0.0", port=port)
