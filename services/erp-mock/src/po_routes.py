"""Vendor-neutral PO creation surface for the MockERPAdapter.

Honors:
- `X-Mock-Scenario: po_create_fails` → returns HTTP 500 the first N attempts
  (per `Idempotency-Key`) so the outbox-worker retry path is exercisable.
- `Idempotency-Key` header → on retry the same response is returned instead
  of minting a fresh PO number (vendor-side dedup).

Webhook emission: after a successful create, schedules a fire-and-forget
status webhook back to erp-adapter (M3.3 will validate; M3.2 ignores it).
"""
from __future__ import annotations

import asyncio
import logging
import os
from uuid import uuid4

from aiohttp import web

import scenarios
import store
import webhook_emitter

# Strong refs to in-flight webhook tasks — `asyncio.create_task` alone allows
# the task to be GC'd before it fires, dropping the webhook silently.
_PENDING_WEBHOOKS: set[asyncio.Task] = set()

logger = logging.getLogger(__name__)


async def po_create(request: web.Request) -> web.Response:
    cfg = request.app["cfg"]
    sc = scenarios.resolve(cfg.scenario, request.headers.get(scenarios.SCENARIO_HEADER))

    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "bad_json"}, status=400)

    transaction_id = body.get("transaction_id") or body.get("transactionId") or ""
    idem = request.headers.get("Idempotency-Key", "") or transaction_id
    key = idem or f"anon-{uuid4().hex[:12]}"

    # Scenario po_create_fails — 5xx the first N attempts (per idempotency key)
    if sc.po_create_failures_before_success > 0:
        seen = store.failure_count(key)
        if seen < sc.po_create_failures_before_success:
            store.increment_failure(key)
            logger.info("mock-po transient 5xx idem=%s attempt=%d/%d",
                        key, seen + 1, sc.po_create_failures_before_success)
            return web.json_response({"error": "transient_5xx", "attempt": seen + 1}, status=500)

    # Idempotency replay
    existing = store.get(key)
    if existing is not None and "erp_reference_id" in existing:
        return web.json_response(existing)

    erp_ref = f"MOCK-PO-{uuid4().hex[:10].upper()}"
    record = {
        "erp_reference_id": erp_ref,
        "vendor": "mock",
        "transaction_id": transaction_id,
        "status": "CREATED",
    }
    store.put(key, record)
    logger.info("mock-po created erp_ref=%s txn=%s scenario=%s",
                erp_ref, transaction_id, sc.name)

    # Schedule the inbound webhook so M3.3 has something to consume.
    # WEBHOOK_TARGET_URL is read at request-time so smoke tests can point it
    # at an ephemeral adapter port after the mock has already booted.
    delay = sc.webhook_delay_seconds if sc.webhook_delay_seconds is not None else cfg.webhook_delay_seconds
    target_url = os.getenv("WEBHOOK_TARGET_URL", cfg.webhook_target_url)
    # Read the live HMAC secret from the env at fire time too — smoke tests
    # rotate it after the mock has booted.
    secret = os.getenv("SAP_WEBHOOK_HMAC_SECRET", cfg.sap_hmac_secret)
    task = asyncio.create_task(webhook_emitter.emit_after(
        delay,
        vendor="mock",
        target_url=target_url,
        secret=secret,
        transaction_id=transaction_id,
        erp_reference_id=erp_ref,
        state="ACCEPTED",
    ))
    _PENDING_WEBHOOKS.add(task)
    task.add_done_callback(_PENDING_WEBHOOKS.discard)

    return web.json_response(record, status=201)


def register(app: web.Application) -> None:
    app.router.add_post("/mock/po/create", po_create)
