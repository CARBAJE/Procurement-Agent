"""Email notifier — async SMTP via aiosmtplib + Jinja2 HTML templates."""
from __future__ import annotations

import logging
import os
from email.message import EmailMessage
from typing import Any

import aiosmtplib
from jinja2 import Environment, FileSystemLoader, select_autoescape

logger = logging.getLogger(__name__)

_TEMPLATES_DIR = os.path.join(os.path.dirname(__file__), "templates")
_env = Environment(
    loader=FileSystemLoader(_TEMPLATES_DIR),
    autoescape=select_autoescape(["html"]),
)


def _template_for(state: str) -> str:
    return {
        "CONFIRMED": "email_confirmed.html",
        "DELIVERED": "email_delivered.html",
    }.get(state.upper(), "email_generic.html")


class EmailNotifier:
    def __init__(
        self,
        *,
        host: str,
        port: int,
        user: str,
        password: str,
        from_addr: str,
    ) -> None:
        self._host = host
        self._port = port
        self._user = user
        self._password = password
        self._from = from_addr

    @property
    def enabled(self) -> bool:
        return bool(self._host)

    async def send(self, to_addr: str, payload: dict[str, Any]) -> None:
        if not self.enabled or not to_addr:
            return
        state = (payload.get("state") or "").upper()
        template = _env.get_template(_template_for(state))
        html = template.render(**payload)

        msg = EmailMessage()
        msg["From"] = self._from
        msg["To"] = to_addr
        msg["Subject"] = f"Order {state} — {payload.get('order_id', 'unknown')}"
        msg.set_content(
            f"Order {payload.get('order_id')} state changed to {state}.\n"
            f"Transaction: {payload.get('transaction_id')}\n"
        )
        msg.add_alternative(html, subtype="html")

        try:
            await aiosmtplib.send(
                msg,
                hostname=self._host,
                port=self._port,
                username=self._user or None,
                password=self._password or None,
                start_tls=True,
                timeout=10,
            )
            logger.info("[email] sent to=%s state=%s txn=%s",
                        to_addr, state, payload.get("transaction_id"))
        except Exception as exc:
            logger.warning("[email] send failed to=%s: %s", to_addr, exc)

    async def close(self) -> None:
        # aiosmtplib uses one-shot connections; nothing persistent to close.
        return
