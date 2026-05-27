"""ERP adapter microservice — entrypoint.

Boots:
- Pydantic Settings from env
- asyncpg pool against procurement-postgres (best-effort; readyz will reflect)
- Redis client (best-effort; readyz will reflect)
- The configured ERPAdapter (mock | sap | oracle | multi)
- Bearer auth middleware on /api/v1/* (webhooks exempt — HMAC instead)
- HTTP routes

Mirrors the layout of services/analytics/src/main.py.
"""
from __future__ import annotations

import logging
import os
import sys

# Make sibling modules importable when launched as `python src/main.py`
sys.path.insert(0, os.path.dirname(__file__))

from aiohttp import ClientSession, web

from config import Settings
from middleware.auth import make_auth_middleware
import routes
from adapters.factory import build_adapter
from outbox import AsyncpgOutboxRepo, InMemoryOutboxRepo
from outbox.worker import OutboxWorker

logger = logging.getLogger(__name__)


# ── Lifecycle ─────────────────────────────────────────────────────────────────

async def _on_startup(app: web.Application) -> None:
    settings: Settings = app["settings"]

    # DB pool — best effort
    try:
        import asyncpg  # type: ignore
        import json as _json

        async def _init_conn(conn):
            # Teach asyncpg to (de)serialize JSONB transparently. Without this
            # the outbox `payload` JSONB column would reject Python dicts as
            # "expected str, got dict".
            await conn.set_type_codec(
                "jsonb",
                encoder=_json.dumps,
                decoder=_json.loads,
                schema="pg_catalog",
            )
            await conn.set_type_codec(
                "json",
                encoder=_json.dumps,
                decoder=_json.loads,
                schema="pg_catalog",
            )

        pool = await asyncpg.create_pool(
            host=settings.db_host, port=settings.db_port, database=settings.db_name,
            user=settings.db_user, password=settings.db_password,
            min_size=1, max_size=10, command_timeout=15,
            init=_init_conn,
        )
        app["db_pool"] = pool
        logger.info("DB pool ready (%s@%s:%s/%s)",
                    settings.db_user, settings.db_host, settings.db_port, settings.db_name)
    except Exception as exc:
        logger.warning("DB unavailable (%s) — /readyz will report not-ready", exc)
        app["db_pool"] = None

    # Redis — best effort
    try:
        import redis.asyncio as aioredis  # type: ignore
        redis = aioredis.from_url(settings.redis_url, encoding="utf-8", decode_responses=True)
        await redis.ping()
        app["redis"] = redis
        logger.info("Redis connected (%s)", settings.redis_url)
    except Exception as exc:
        logger.warning("Redis unavailable (%s) — /readyz will report not-ready", exc)
        app["redis"] = None

    # Shared aiohttp session for outbound vendor calls
    app["http"] = ClientSession()

    # Vendor adapter
    app["adapter"] = build_adapter(settings, app["http"])
    logger.info("Adapter ready (vendors=%s)", ",".join(settings.erp_vendors))

    # Outbox repository — asyncpg in prod, in-memory fallback when DB missing
    if app.get("db_pool") is not None:
        app["outbox_repo"] = AsyncpgOutboxRepo(app["db_pool"])
        logger.info("Outbox: AsyncpgOutboxRepo")
    else:
        app["outbox_repo"] = InMemoryOutboxRepo()
        logger.warning("Outbox: InMemoryOutboxRepo (no DB) — POs are NOT durable")

    # Background outbox worker
    worker = OutboxWorker(
        repo=app["outbox_repo"],
        adapter=app["adapter"],
        redis=app.get("redis"),
        concurrency=settings.worker_concurrency,
        poll_interval=settings.worker_poll_interval_seconds,
        backoff=settings.worker_backoff,
    )
    worker.start()
    app["outbox_worker"] = worker


async def _on_cleanup(app: web.Application) -> None:
    worker = app.get("outbox_worker")
    if worker is not None:
        await worker.stop()
    http: ClientSession | None = app.get("http")
    if http is not None:
        await http.close()
    pool = app.get("db_pool")
    if pool is not None:
        await pool.close()
    redis = app.get("redis")
    if redis is not None:
        await redis.aclose()


def create_app(settings: Settings | None = None) -> web.Application:
    settings = settings or Settings()  # type: ignore[arg-type]
    app = web.Application(middlewares=[make_auth_middleware(settings.internal_token)])
    app["settings"] = settings
    app.on_startup.append(_on_startup)
    app.on_cleanup.append(_on_cleanup)
    routes.register(app)
    return app


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s :: %(message)s",
    )
    settings = Settings()  # type: ignore[arg-type]
    web.run_app(create_app(settings), host="0.0.0.0", port=settings.port)
