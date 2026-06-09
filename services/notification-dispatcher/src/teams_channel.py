"""Microsoft Teams notifier — posts an Adaptive Card to an Incoming Webhook."""
from __future__ import annotations

import logging
from typing import Any

import aiohttp

logger = logging.getLogger(__name__)


def _color_for(state: str) -> str:
    return {
        "CONFIRMED": "good",
        "SHIPPED": "accent",
        "DELIVERED": "good",
        "CANCELLED": "attention",
    }.get(state.upper(), "default")


def _build_card(payload: dict[str, Any]) -> dict[str, Any]:
    state = (payload.get("state") or "").upper() or "?"
    txn = payload.get("transaction_id") or "?"
    order = payload.get("order_id") or "?"
    return {
        "type": "message",
        "attachments": [
            {
                "contentType": "application/vnd.microsoft.card.adaptive",
                "content": {
                    "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                    "type": "AdaptiveCard",
                    "version": "1.4",
                    "body": [
                        {
                            "type": "TextBlock",
                            "text": f"Order status update — {state}",
                            "size": "Large",
                            "weight": "Bolder",
                            "color": _color_for(state),
                        },
                        {
                            "type": "FactSet",
                            "facts": [
                                {"title": "Order:", "value": order},
                                {"title": "Transaction:", "value": txn},
                                {"title": "Source:", "value": payload.get("source", "unknown")},
                                {"title": "Observed at:",
                                 "value": payload.get("observed_at", "?")},
                            ],
                        },
                    ],
                },
            }
        ],
    }


class TeamsNotifier:
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
        try:
            async with self._session.post(self._url, json=_build_card(payload),
                                          timeout=5) as resp:
                if resp.status >= 400:
                    text = await resp.text()
                    logger.warning("[teams] HTTP %s — %s", resp.status, text[:200])
                else:
                    logger.info("[teams] sent state=%s txn=%s",
                                payload.get("state"), payload.get("transaction_id"))
        except Exception as exc:
            logger.warning("[teams] send failed: %s", exc)

    async def close(self) -> None:
        if self._session is not None:
            await self._session.close()
            self._session = None
