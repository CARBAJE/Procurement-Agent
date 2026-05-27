"""Background task that signs and POSTs a status webhook back to erp-adapter.

For M3.1 the emitter is wired but only triggered from M3.2 (PO create
success). For M3.3 it provides the inbound-path test harness.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
from datetime import datetime, timezone
from uuid import uuid4

import aiohttp

logger = logging.getLogger(__name__)


def _sign(secret: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


async def emit_after(
    delay_seconds: float,
    *,
    vendor: str,
    target_url: str,
    secret: str,
    transaction_id: str,
    erp_reference_id: str,
    state: str = "ACCEPTED",
) -> None:
    """Sleep then POST a signed status webhook back to the adapter."""
    if delay_seconds > 0:
        await asyncio.sleep(delay_seconds)

    payload = {
        "vendor": vendor,
        "transaction_id": transaction_id,
        "erp_reference_id": erp_reference_id,
        "state": state,
        "event_ts": datetime.now(timezone.utc).isoformat(),
        "vendor_event_id": f"evt-{uuid4().hex[:12]}",
    }
    body = json.dumps(payload).encode()
    sig_header = f"X-{vendor.capitalize()}-Signature"
    url = f"{target_url.rstrip('/')}/api/v1/webhooks/{vendor}/po-status"

    try:
        async with aiohttp.ClientSession() as s:
            async with s.post(url, data=body, headers={
                "Content-Type": "application/json",
                sig_header: _sign(secret, body),
            }) as resp:
                logger.info("webhook -> %s status=%s txn=%s", url, resp.status, transaction_id)
    except Exception as exc:
        logger.warning("webhook emit failed url=%s err=%s", url, exc)


def schedule(loop: asyncio.AbstractEventLoop, **kwargs) -> asyncio.Task:
    return loop.create_task(emit_after(**kwargs))
