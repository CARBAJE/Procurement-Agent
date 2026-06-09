"""HTTP routes for the ERP adapter.

Public routes (no auth):
  GET  /healthz     liveness
  GET  /readyz      deep readiness (DB + Redis + at least one circuit closed)
  GET  /metrics     Prometheus exposition

Internal routes (bearer-token auth via middleware):
  POST /api/v1/budget/check         synchronous budget gate
  POST /api/v1/po/sync              fire-and-forget PO push (M3.2)
  GET  /api/v1/po/sync/{sync_id}    poll outbox status (M3.2)

Webhook routes (HMAC verified inside the handler):
  POST /api/v1/webhooks/sap/po-status
  POST /api/v1/webhooks/oracle/po-status
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from decimal import Decimal, InvalidOperation

from aiohttp import web

from observability import audit, metrics

logger = logging.getLogger(__name__)


# ── Public ────────────────────────────────────────────────────────────────────

async def healthz(_: web.Request) -> web.Response:
    return web.json_response({"status": "ok"})


async def readyz(request: web.Request) -> web.Response:
    """Deep readiness.

    Hard checks (failure → 503):
      * db_pool present and SELECT 1 succeeds
      * redis present and PING succeeds

    Soft checks (recorded but don't fail readiness — a single vendor outage
    must not take the whole adapter down; the worker + breaker handle it):
      * per-vendor healthcheck()
      * outbox lag (oldest pending row age) when DB is available
    """
    checks: dict[str, object] = {}
    hard_ok = True

    pool = request.app.get("db_pool")
    if pool is None:
        checks["db"] = "unavailable"
        hard_ok = False
    else:
        try:
            async with pool.acquire() as c:
                await c.fetchval("SELECT 1")
            checks["db"] = "ok"
        except Exception as exc:
            checks["db"] = f"error: {exc!s}"
            hard_ok = False

    redis = request.app.get("redis")
    if redis is None:
        checks["redis"] = "unavailable"
        hard_ok = False
    else:
        try:
            await redis.ping()
            checks["redis"] = "ok"
        except Exception as exc:
            checks["redis"] = f"error: {exc!s}"
            hard_ok = False

    # Soft: per-vendor healthcheck
    adapter = request.app.get("adapter")
    vendors_block: dict[str, str] = {}
    if adapter is not None:
        members = getattr(adapter, "_adapters", None) or [adapter]
        for m in members:
            v = getattr(m, "vendor", "unknown")
            try:
                ok = await asyncio.wait_for(m.healthcheck(), timeout=3.0)
            except Exception as exc:
                vendors_block[v] = f"error: {exc!s}"
                continue
            vendors_block[v] = "ok" if ok else "degraded"
    checks["vendors"] = vendors_block

    # Soft: outbox lag (skip if no DB)
    if pool is not None:
        try:
            async with pool.acquire() as c:
                lag = await c.fetchval(
                    """
                    SELECT EXTRACT(EPOCH FROM (NOW() - MIN(synced_at)))
                      FROM erp_sync_records
                     WHERE sync_type = 'po_creation' AND status = 'pending'
                    """
                )
            checks["outbox_lag_seconds"] = float(lag) if lag is not None else 0.0
        except Exception as exc:
            checks["outbox_lag_seconds"] = f"error: {exc!s}"

    return web.json_response(
        {"ready": hard_ok, "checks": checks},
        status=200 if hard_ok else 503,
    )


async def metrics_endpoint(_: web.Request) -> web.Response:
    return web.Response(body=metrics.render(),
                        headers={"Content-Type": "text/plain; version=0.0.4"})


# ── Internal: /api/v1/budget/check ───────────────────────────────────────────

async def budget_check(request: web.Request) -> web.Response:
    """Synchronous budget gate on /commit's critical path.

    Total wall budget = settings.budget_check_total_timeout_ms. On vendor
    unavailable returns 503 — the orchestrator decides fail-open vs fail-closed.
    """
    from models import BudgetCheckRequest
    from adapters.base import VendorPermanentError, VendorTransientError
    from adapters.mock import mock_scenario_ctx

    try:
        body = await request.json()
        req = BudgetCheckRequest.model_validate(body)
    except Exception as exc:
        return web.json_response({"error": "bad_request", "detail": str(exc)}, status=400)

    adapter = request.app["adapter"]
    settings = request.app["settings"]
    vendor_label = ",".join(settings.erp_vendors)
    started = time.perf_counter()

    # Forward the mock-scenario override to the mock adapter (no-op for sap/oracle)
    scenario_token = mock_scenario_ctx.set(request.headers.get("X-Mock-Scenario"))

    try:
        try:
            result = await asyncio.wait_for(
                adapter.check_budget(req),
                timeout=settings.budget_check_total_timeout_ms / 1000,
            )
        finally:
            mock_scenario_ctx.reset(scenario_token)
    except asyncio.TimeoutError:
        elapsed = time.perf_counter() - started
        metrics.budget_check_duration_seconds.labels(vendor=vendor_label).observe(elapsed)
        metrics.budget_check_total.labels(vendor=vendor_label, outcome="timeout").inc()
        audit.emit("BUDGET_CHECK", vendor=vendor_label, outcome="timeout",
                   transaction_id=req.transaction_id, reason="adapter timeout")
        return web.json_response({"allowed": None, "reason": "vendor_unavailable"}, status=503)
    except VendorTransientError as exc:
        metrics.budget_check_total.labels(vendor=vendor_label, outcome="error").inc()
        audit.emit("BUDGET_CHECK", vendor=vendor_label, outcome="error",
                   transaction_id=req.transaction_id, reason=str(exc))
        return web.json_response({"allowed": None, "reason": "vendor_unavailable"}, status=503)
    except VendorPermanentError as exc:
        metrics.budget_check_total.labels(vendor=vendor_label, outcome="error").inc()
        audit.emit("BUDGET_CHECK", vendor=vendor_label, outcome="error",
                   transaction_id=req.transaction_id, reason=str(exc))
        return web.json_response({"error": "vendor_permanent", "detail": str(exc)}, status=502)

    elapsed = time.perf_counter() - started
    metrics.budget_check_duration_seconds.labels(vendor=vendor_label).observe(elapsed)
    outcome = "allowed" if result.allowed else "denied"
    metrics.budget_check_total.labels(vendor=vendor_label, outcome=outcome).inc()
    audit.emit("BUDGET_CHECK", vendor=vendor_label, outcome=outcome,
               transaction_id=req.transaction_id,
               amount_bucket=_bucket(req.requested_amount))
    return web.json_response(result.model_dump(mode="json"))


def _bucket(amount: Decimal) -> str:
    try:
        a = Decimal(amount)
    except (InvalidOperation, TypeError):
        return "unknown"
    if a < 10_000:    return "<10k"
    if a < 100_000:   return "10k-100k"
    if a < 1_000_000: return "100k-1M"
    return ">1M"


# ── Internal: /api/v1/po/sync ────────────────────────────────────────────────

async def policy_evaluate(request: web.Request) -> web.Response:
    """ERP policy gate for the /run orchestration flow.

    Fail-open: on vendor timeout or transient error returns a neutral envelope
    with fallback=True. The orchestrator's PolicyEngine treats fallback=True as
    "ERP unavailable, apply base policy only".

    On VendorPermanentError (4xx from the ERP adapter) returns HTTP 502 so the
    orchestrator surfaces it as a hard failure rather than silently failing open.
    """
    from models import PolicyEvaluateRequest
    from adapters.base import VendorPermanentError, VendorTransientError
    from adapters.mock import mock_scenario_ctx

    _FAIL_OPEN_ENVELOPE = {
        "preferred_supplier_ids": [],
        "approval_required": False,
        "auto_commit_allowed": True,
        "fallback": True,
        "constraints": [],
    }

    try:
        body = await request.json()
        req = PolicyEvaluateRequest.model_validate(body)
    except Exception as exc:
        return web.json_response({"error": "bad_request", "detail": str(exc)}, status=400)

    adapter = request.app["adapter"]
    settings = request.app["settings"]
    vendor_label = ",".join(settings.erp_vendors)

    scenario_token = mock_scenario_ctx.set(request.headers.get("X-Mock-Scenario"))
    try:
        try:
            result = await asyncio.wait_for(
                adapter.evaluate_policy(req),
                timeout=settings.budget_check_total_timeout_ms / 1000,
            )
        finally:
            mock_scenario_ctx.reset(scenario_token)
    except asyncio.TimeoutError:
        audit.emit("POLICY_EVAL", vendor=vendor_label, outcome="timeout",
                   transaction_id=req.transaction_id, reason="adapter_timeout")
        return web.json_response({**_FAIL_OPEN_ENVELOPE, "vendor": vendor_label})
    except VendorTransientError as exc:
        audit.emit("POLICY_EVAL", vendor=vendor_label, outcome="error",
                   transaction_id=req.transaction_id, reason=str(exc))
        return web.json_response({**_FAIL_OPEN_ENVELOPE, "vendor": vendor_label})
    except VendorPermanentError as exc:
        return web.json_response(
            {"error": "vendor_permanent", "detail": str(exc)}, status=502
        )

    audit.emit(
        "POLICY_EVAL", vendor=vendor_label, outcome="ok",
        transaction_id=req.transaction_id,
        approval_required=result.approval_required,
        auto_commit_allowed=result.auto_commit_allowed,
        preferred_count=len(result.preferred_supplier_ids),
    )
    return web.json_response(result.model_dump(mode="json"))


async def po_sync(request: web.Request) -> web.Response:
    """Enqueue a PO push. Idempotent on `transaction_id` (per vendor).

    Returns 202 with `{sync_id, status, idempotency_key, vendors}`. The
    background worker drains the outbox asynchronously — this endpoint never
    blocks on the vendor.
    """
    from models import NormalizedPO

    try:
        body = await request.json()
        po = NormalizedPO.model_validate(body)
    except Exception as exc:
        return web.json_response({"error": "bad_request", "detail": str(exc)}, status=400)

    settings = request.app["settings"]
    repo = request.app["outbox_repo"]
    vendors: list[str] = list(settings.erp_vendors)

    # Stash X-Mock-Scenario in metadata so the async outbox worker sees it.
    scenario = request.headers.get("X-Mock-Scenario")
    if scenario:
        po.metadata = {**(po.metadata or {}), "mock_scenario": scenario}
    payload = po.model_dump(mode="json")

    results: list[dict] = []
    for vendor in vendors:
        try:
            row, inserted = await repo.insert_pending(
                transaction_id=po.transaction_id,
                vendor=vendor,
                payload=payload,
            )
        except Exception as exc:
            logger.exception("outbox insert failed vendor=%s txn=%s", vendor, po.transaction_id)
            return web.json_response(
                {"error": "outbox_unavailable", "detail": str(exc)}, status=503,
            )
        results.append({
            "vendor": vendor,
            "sync_id": str(row.sync_id),
            "status": row.status,
            "idempotency_key": row.idempotency_key,
            "deduplicated": (not inserted),
        })
        audit.emit("PO_SYNC_ENQUEUED", vendor=vendor, transaction_id=po.transaction_id,
                   sync_id=str(row.sync_id), deduplicated=(not inserted))

    return web.json_response({
        "transaction_id": po.transaction_id,
        "order_id": po.order_id,
        "results": results,
        # Convenience field for single-vendor deployments — the most common case
        "sync_id": results[0]["sync_id"] if len(results) == 1 else None,
    }, status=202)


async def po_sync_status(request: web.Request) -> web.Response:
    sync_id_str = request.match_info.get("sync_id", "")
    from uuid import UUID
    try:
        sync_id = UUID(sync_id_str)
    except ValueError:
        return web.json_response({"error": "bad_sync_id"}, status=400)

    repo = request.app["outbox_repo"]
    row = await repo.get(sync_id)
    if row is None:
        return web.json_response({"error": "not_found"}, status=404)

    return web.json_response({
        "sync_id": str(row.sync_id),
        "transaction_id": row.transaction_id,
        "vendor": row.vendor,
        "sync_type": row.sync_type,
        "status": row.status,
        "attempts": row.attempts,
        "erp_reference_id": row.erp_reference_id,
        "last_error": row.last_error,
        "next_attempt_at": row.next_attempt_at.isoformat() if row.next_attempt_at else None,
        "lease_until": row.lease_until.isoformat() if row.lease_until else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    })


# ── Webhooks — inbound from ERP vendor ───────────────────────────────────────

def _signature_header_name(vendor: str) -> str:
    return f"X-{vendor.capitalize()}-Signature"


def _vendor_secrets(settings, vendor: str) -> tuple[str, str]:
    """Return (primary, next) HMAC secrets for the vendor."""
    if vendor == "sap":
        return settings.sap_webhook_hmac_secret, settings.sap_webhook_hmac_secret_next
    if vendor == "oracle":
        return settings.oracle_webhook_hmac_secret, settings.oracle_webhook_hmac_secret_next
    if vendor == "mock":
        # The mock vendor signs with the SAP secret (it's a stand-in — see
        # services/erp-mock/src/webhook_emitter.py).
        return settings.sap_webhook_hmac_secret, settings.sap_webhook_hmac_secret_next
    return "", ""


def _adapter_for_vendor(app: web.Application, vendor: str):
    """Find the concrete adapter for the given vendor. Falls back to the
    single configured adapter when there's only one (the common case)."""
    a = app["adapter"]
    # MultiVendorAdapter exposes its members; for single-adapter setups the
    # adapter's .vendor attribute is the authoritative match.
    members = getattr(a, "_adapters", None)
    if members:
        for m in members:
            if m.vendor == vendor:
                return m
        return None
    return a if getattr(a, "vendor", None) == vendor else None


async def _handle_webhook(request: web.Request, vendor: str) -> web.Response:
    """Common webhook handler — HMAC verify → normalize → update outbox →
    Redis publish → audit + metrics. Vendor-specific behavior lives in the
    adapter's `normalize_inbound_status`."""
    from security import verify_signature

    settings = request.app["settings"]
    raw = await request.read()
    header_name = _signature_header_name(vendor)
    sig = request.headers.get(header_name)
    primary, nxt = _vendor_secrets(settings, vendor)

    if not verify_signature(raw_body=raw, header_value=sig, secrets=(primary, nxt)):
        metrics.webhook_received_total.labels(vendor=vendor, outcome="401").inc()
        audit.emit("WEBHOOK_REJECTED", vendor=vendor, reason="hmac_mismatch",
                   source_ip=request.remote)
        return web.json_response({"error": "invalid_signature"}, status=401)

    try:
        payload = json.loads(raw or b"{}")
    except json.JSONDecodeError:
        metrics.webhook_received_total.labels(vendor=vendor, outcome="400").inc()
        audit.emit("WEBHOOK_REJECTED", vendor=vendor, reason="bad_json",
                   source_ip=request.remote)
        return web.json_response({"error": "bad_json"}, status=400)

    adapter = _adapter_for_vendor(request.app, vendor)
    if adapter is None:
        metrics.webhook_received_total.labels(vendor=vendor, outcome="400").inc()
        audit.emit("WEBHOOK_REJECTED", vendor=vendor, reason="vendor_not_configured")
        return web.json_response({"error": "vendor_not_configured"}, status=400)

    try:
        inbound = adapter.normalize_inbound_status(payload, dict(request.headers))
    except NotImplementedError:
        # Vendor adapter not wired yet (SAP/Oracle in M3.3 still stubbed)
        metrics.webhook_received_total.labels(vendor=vendor, outcome="501").inc()
        audit.emit("WEBHOOK_REJECTED", vendor=vendor, reason="vendor_normalize_not_implemented")
        return web.json_response({"error": "vendor_normalize_not_implemented"}, status=501)
    except Exception as exc:
        metrics.webhook_received_total.labels(vendor=vendor, outcome="400").inc()
        audit.emit("WEBHOOK_REJECTED", vendor=vendor, reason=f"normalize_failed: {exc}")
        return web.json_response({"error": "normalize_failed", "detail": str(exc)}, status=400)

    repo = request.app["outbox_repo"]
    try:
        await repo.update_inbound_state(
            transaction_id=inbound.transaction_id,
            vendor=vendor,
            erp_reference_id=inbound.erp_reference_id,
        )
    except Exception as exc:
        logger.warning("outbox update on webhook failed txn=%s vendor=%s err=%s",
                       inbound.transaction_id, vendor, exc)

    # Build the canonical event payload (used by both Kafka and Redis).
    event_payload = {
        "vendor": vendor,
        "transaction_id": inbound.transaction_id,
        "erp_reference_id": inbound.erp_reference_id,
        "state": inbound.state,
        "event_ts": inbound.event_ts.isoformat(),
        "vendor_event_id": inbound.vendor_event_id,
        "source": "erp_webhook",
    }

    # Kafka (primary path — orchestrator WS broker + notification-dispatcher)
    kafka_producer = request.app.get("kafka_producer")
    settings = request.app["settings"]
    if kafka_producer is not None:
        try:
            await kafka_producer.send_and_wait(
                settings.kafka_topic,
                value=json.dumps(event_payload).encode("utf-8"),
            )
        except Exception as exc:
            logger.warning("kafka publish on webhook failed err=%s", exc)

    # Redis (legacy fallback — kept for any subscriber that hasn't migrated)
    redis = request.app.get("redis")
    if redis is not None:
        try:
            channel = f"po.status_changed:{inbound.transaction_id}"
            await redis.publish(channel, json.dumps(event_payload))
        except Exception as exc:
            logger.warning("redis publish on webhook failed err=%s", exc)

    metrics.webhook_received_total.labels(vendor=vendor, outcome="ok").inc()
    audit.emit("WEBHOOK_RECEIVED", vendor=vendor, transaction_id=inbound.transaction_id,
               state=inbound.state, erp_reference_id=inbound.erp_reference_id,
               vendor_event_id=inbound.vendor_event_id)
    return web.json_response({"accepted": True, "transaction_id": inbound.transaction_id})


async def webhook_sap(request: web.Request) -> web.Response:
    return await _handle_webhook(request, "sap")


async def webhook_oracle(request: web.Request) -> web.Response:
    return await _handle_webhook(request, "oracle")


async def webhook_mock(request: web.Request) -> web.Response:
    return await _handle_webhook(request, "mock")


# ── Internal: /api/v1/admin/outbox/{sync_id}/replay ──────────────────────────

async def admin_replay(request: web.Request) -> web.Response:
    """Reset a DLQ'd outbox row back to 'pending' so the worker re-tries.

    Idempotency: only acts on rows in status='failed'. Already-pending or
    already-success rows return 404 (with a hint) so an accidental replay
    can't disturb in-flight work.
    """
    from uuid import UUID
    sync_id_str = request.match_info.get("sync_id", "")
    try:
        sync_id = UUID(sync_id_str)
    except ValueError:
        return web.json_response({"error": "bad_sync_id"}, status=400)

    repo = request.app["outbox_repo"]
    row = await repo.replay(sync_id)
    if row is None:
        # Distinguish missing vs not-replayable
        existing = await repo.get(sync_id)
        if existing is None:
            return web.json_response({"error": "not_found"}, status=404)
        return web.json_response(
            {"error": "not_replayable", "current_status": existing.status,
             "hint": "Only rows in status='failed' can be replayed."},
            status=409,
        )

    audit.emit("PO_REPLAY", vendor=row.vendor, transaction_id=row.transaction_id,
               sync_id=str(row.sync_id))
    return web.json_response({
        "sync_id": str(row.sync_id),
        "status": row.status,
        "attempts": row.attempts,
        "next_attempt_at": row.next_attempt_at.isoformat(),
    })


def register(app: web.Application) -> None:
    app.router.add_get("/healthz", healthz)
    app.router.add_get("/readyz", readyz)
    app.router.add_get("/metrics", metrics_endpoint)

    app.router.add_post("/api/v1/budget/check", budget_check)
    app.router.add_post("/api/v1/policy/evaluate", policy_evaluate)
    app.router.add_post("/api/v1/po/sync", po_sync)
    app.router.add_get("/api/v1/po/sync/{sync_id}", po_sync_status)

    app.router.add_post("/api/v1/webhooks/sap/po-status", webhook_sap)
    app.router.add_post("/api/v1/webhooks/oracle/po-status", webhook_oracle)
    app.router.add_post("/api/v1/webhooks/mock/po-status", webhook_mock)

    app.router.add_post("/api/v1/admin/outbox/{sync_id}/replay", admin_replay)
