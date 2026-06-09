"""Notification dispatcher — consumes Kafka `po.status.changed` and fans out
to Slack / Teams / Email per the rules from `real_time_tracking.md`.

Rules:
  • Slack/Teams:  `confirmed`, `shipped`, `delivered`, `cancelled`
  • Email:        `confirmed`, `delivered`

Channels that aren't configured (empty env var) are silently skipped — the
service still runs, it just doesn't fire that channel.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from typing import Any

from aiohttp import web

sys.path.insert(0, os.path.dirname(__file__))

from config import Settings  # noqa: E402
from slack_channel import SlackNotifier  # noqa: E402
from teams_channel import TeamsNotifier  # noqa: E402
from email_channel import EmailNotifier  # noqa: E402
from recipient_lookup import RecipientLookup  # noqa: E402

logger = logging.getLogger(__name__)

# State → channels rule table. Mirrors the table in real_time_tracking.md.
_RULES: dict[str, set[str]] = {
    "confirmed": {"slack", "teams", "email"},
    "shipped":   {"slack", "teams"},
    "delivered": {"slack", "teams", "email"},
    "cancelled": {"slack", "teams"},
}


def _channels_for_event(payload: dict[str, Any]) -> set[str]:
    """Return the set of channel names to fire for this event.

    The payload's `po_status` (normalized) is preferred; otherwise we fall
    back to lowercasing `state` (the raw Beckn state).
    """
    state_key = (payload.get("po_status") or payload.get("state") or "").lower()
    return _RULES.get(state_key, set())


async def _dispatch_event(
    payload: dict[str, Any],
    *,
    slack: SlackNotifier | None,
    teams: TeamsNotifier | None,
    email: EmailNotifier | None,
    recipients: RecipientLookup,
) -> None:
    """Fire all applicable channels for a single event. Errors are logged
    but never raised — one channel's failure must not block the others."""
    channels = _channels_for_event(payload)
    if not channels:
        logger.debug("[dispatch] no rules matched for state=%s — skipping",
                     payload.get("state"))
        return

    tasks: list[asyncio.Task] = []
    if "slack" in channels and slack is not None and slack.enabled:
        tasks.append(asyncio.create_task(slack.send(payload)))
    if "teams" in channels and teams is not None and teams.enabled:
        tasks.append(asyncio.create_task(teams.send(payload)))
    if "email" in channels and email is not None and email.enabled:
        # Resolve recipient lazily so DB-down doesn't block the other channels.
        # The DB key is order_id (= purchase_orders.beckn_confirm_ref), not txn.
        addr = await recipients.email_for_order(payload.get("order_id"))
        if addr:
            tasks.append(asyncio.create_task(email.send(addr, payload)))
        else:
            logger.info("[email] no recipient found for order=%s txn=%s",
                        payload.get("order_id"), payload.get("transaction_id"))

    if not tasks:
        return
    results = await asyncio.gather(*tasks, return_exceptions=True)
    for r in results:
        if isinstance(r, Exception):
            logger.warning("[dispatch] channel send failed: %s", r)


async def _consumer_loop(
    settings: Settings,
    slack: SlackNotifier | None,
    teams: TeamsNotifier | None,
    email: EmailNotifier | None,
    recipients: RecipientLookup,
) -> None:
    """Long-running task: read Kafka, dispatch each event."""
    from aiokafka import AIOKafkaConsumer  # imported here so tests can stub it

    consumer = AIOKafkaConsumer(
        settings.kafka_topic,
        bootstrap_servers=settings.kafka_bootstrap,
        group_id=settings.kafka_group_id,
        auto_offset_reset="latest",
        enable_auto_commit=True,
    )
    await consumer.start()
    logger.info("[kafka] subscribed to %s (group=%s)",
                settings.kafka_topic, settings.kafka_group_id)
    try:
        async for msg in consumer:
            try:
                payload = json.loads(msg.value.decode("utf-8"))
            except Exception as exc:
                logger.warning("[kafka] malformed message: %s", exc)
                continue
            try:
                await _dispatch_event(
                    payload,
                    slack=slack, teams=teams, email=email,
                    recipients=recipients,
                )
            except Exception as exc:
                logger.warning("[dispatch] failed: %s", exc)
    finally:
        try:
            await consumer.stop()
        except Exception:
            pass


# ── aiohttp app (just /health) ────────────────────────────────────────────────


async def health(_: web.Request) -> web.Response:
    return web.json_response({"status": "ok", "service": "notification-dispatcher"})


async def _on_startup(app: web.Application) -> None:
    settings: Settings = app["settings"]

    slack = SlackNotifier(settings.slack_webhook_url)
    teams = TeamsNotifier(settings.teams_webhook_url)
    email = EmailNotifier(
        host=settings.smtp_host, port=settings.smtp_port,
        user=settings.smtp_user, password=settings.smtp_password,
        from_addr=settings.smtp_from,
    )
    recipients = RecipientLookup(
        host=settings.db_host, port=settings.db_port,
        database=settings.db_name, user=settings.db_user, password=settings.db_password,
    )
    await recipients.start()

    app["slack"] = slack
    app["teams"] = teams
    app["email"] = email
    app["recipients"] = recipients

    enabled = [n for n, c in
               (("slack", slack), ("teams", teams), ("email", email))
               if c.enabled]
    logger.info("Channels enabled: %s", enabled or "(none)")

    if not settings.kafka_bootstrap:
        logger.warning("KAFKA_BOOTSTRAP not set — dispatcher is idle")
        return

    app["consumer_task"] = asyncio.create_task(
        _consumer_loop(settings, slack, teams, email, recipients),
        name="kafka-status-consumer",
    )


async def _on_cleanup(app: web.Application) -> None:
    task = app.get("consumer_task")
    if task is not None:
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass
    for key in ("slack", "teams", "email"):
        ch = app.get(key)
        if ch is not None:
            await ch.close()
    recipients = app.get("recipients")
    if recipients is not None:
        await recipients.stop()


def create_app(settings: Settings | None = None) -> web.Application:
    settings = settings or Settings()  # type: ignore[arg-type]
    app = web.Application()
    app["settings"] = settings
    app.on_startup.append(_on_startup)
    app.on_cleanup.append(_on_cleanup)
    app.router.add_get("/health", health)
    return app


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )
    port = int(os.getenv("PORT", "8010"))
    web.run_app(create_app(), host="0.0.0.0", port=port)
