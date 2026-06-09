"""Slack notifier — POSTs a simple Block Kit payload to an Incoming Webhook."""
from __future__ import annotations

import logging
from typing import Any

import aiohttp

logger = logging.getLogger(__name__)


def _emoji_for(state: str) -> str:
    return {
        "CONFIRMED": ":white_check_mark:",
        "SHIPPED": ":truck:",
        "DELIVERED": ":package:",
        "CANCELLED": ":x:",
        "ACCEPTED": ":handshake:",
        "PACKED": ":package:",
        "OUT_FOR_DELIVERY": ":motor_scooter:",
    }.get(state.upper(), ":bell:")


def _build_blocks(payload: dict[str, Any]) -> list[dict[str, Any]]:
    state = (payload.get("state") or "").upper() or "?"
    txn = payload.get("transaction_id") or "?"
    order = payload.get("order_id") or "?"
    source = payload.get("source") or "unknown"
    return [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f"{_emoji_for(state)} Order status update — {state}",
            },
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Order:*\n`{order}`"},
                {"type": "mrkdwn", "text": f"*Transaction:*\n`{txn}`"},
                {"type": "mrkdwn", "text": f"*Source:*\n{source}"},
                {"type": "mrkdwn",
                 "text": f"*Observed at:*\n{payload.get('observed_at', '?')}"},
            ],
        },
    ]


class SlackNotifier:
    def __init__(self, webhook_url: str) -> None:
        self._url = webhook_url
        self._session: aiohttp.ClientSession | None = None

    @property
    def enabled(self) -> bool:
        return bool(self._url)

    async def send(self, payload: dict[str, Any]) -> None:
        if not self.enabled:
            return
        if self._session is None:
            self._session = aiohttp.ClientSession()
        body = {"blocks": _build_blocks(payload)}
        try:
            async with self._session.post(self._url, json=body, timeout=5) as resp:
                if resp.status >= 400:
                    text = await resp.text()
                    logger.warning("[slack] HTTP %s — %s", resp.status, text[:200])
                else:
                    logger.info("[slack] sent state=%s txn=%s",
                                payload.get("state"), payload.get("transaction_id"))
        except Exception as exc:
            logger.warning("[slack] send failed: %s", exc)

    async def close(self) -> None:
        if self._session is not None:
            await self._session.close()
            self._session = None
