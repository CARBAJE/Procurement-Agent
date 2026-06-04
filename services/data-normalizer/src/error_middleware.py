"""aiohttp middleware that maps asyncpg exceptions to structured HTTP errors.

Without this middleware every DB constraint violation lands as a generic 500,
which makes callers unable to distinguish "your input is bad" from "the DB is
on fire". With it:

  - UniqueViolationError      → 409  {"error": "duplicate", ...}
  - ForeignKeyViolationError  → 409  {"error": "fk_violation", ...}
  - CheckViolationError       → 422  {"error": "check_violation", ...}
  - NotNullViolationError     → 422  {"error": "not_null_violation", ...}
  - PostgresError (any other) → 500  {"error": "db_error", ...}

HTTPExceptions (from web.HTTPBadRequest etc) pass through unchanged so the
existing 400/404 handling keeps working.
"""
from __future__ import annotations

import logging

import asyncpg
from aiohttp import web

logger = logging.getLogger(__name__)


@web.middleware
async def db_error_middleware(
    request: web.Request,
    handler,
) -> web.StreamResponse:
    try:
        return await handler(request)
    except web.HTTPException:
        raise
    except asyncpg.exceptions.UniqueViolationError as exc:
        logger.warning("[db] unique violation on %s: %s", request.path, exc)
        return web.json_response(
            {
                "error":      "duplicate",
                "constraint": exc.constraint_name,
                "detail":     exc.detail or str(exc).splitlines()[0],
            },
            status=409,
        )
    except asyncpg.exceptions.ForeignKeyViolationError as exc:
        logger.warning("[db] fk violation on %s: %s", request.path, exc)
        return web.json_response(
            {
                "error":      "fk_violation",
                "constraint": exc.constraint_name,
                "detail":     exc.detail or str(exc).splitlines()[0],
            },
            status=409,
        )
    except asyncpg.exceptions.CheckViolationError as exc:
        logger.warning("[db] check violation on %s: %s", request.path, exc)
        return web.json_response(
            {
                "error":      "check_violation",
                "constraint": exc.constraint_name,
                "detail":     exc.detail or str(exc).splitlines()[0],
            },
            status=422,
        )
    except asyncpg.exceptions.NotNullViolationError as exc:
        logger.warning("[db] not-null violation on %s: %s", request.path, exc)
        return web.json_response(
            {
                "error":  "not_null_violation",
                "column": exc.column_name,
                "detail": exc.detail or str(exc).splitlines()[0],
            },
            status=422,
        )
    except asyncpg.exceptions.PostgresError as exc:
        logger.exception("[db] unhandled postgres error on %s", request.path)
        return web.json_response(
            {"error": "db_error", "detail": str(exc).splitlines()[0]},
            status=500,
        )
