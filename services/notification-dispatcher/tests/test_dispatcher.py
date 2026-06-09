"""Unit tests for the notification-dispatcher rules and channel fan-out.

Mocks all I/O (Slack/Teams webhooks, SMTP, DB) so tests run in <1s without
network or testcontainers.
"""
from __future__ import annotations

import os
import sys
from unittest.mock import AsyncMock

import pytest

sys.path.insert(
    0,
    os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")),
)

# Provide stub env so Settings() inside main doesn't blow up on import.
os.environ.setdefault("KAFKA_BOOTSTRAP", "")
os.environ.setdefault("DB_USER", "")

import main as dispatcher_main  # noqa: E402
from main import _channels_for_event, _dispatch_event  # noqa: E402


def _make_channel(enabled: bool = True):
    m = AsyncMock()
    type(m).enabled = property(lambda self: enabled)
    return m


def _make_recipients(email: str | None = "user@example.com"):
    r = AsyncMock()
    r.email_for_order.return_value = email
    return r


# ── _channels_for_event ───────────────────────────────────────────────────────


@pytest.mark.parametrize("state, expected", [
    ("confirmed",       {"slack", "teams", "email"}),
    ("shipped",         {"slack", "teams"}),
    ("delivered",       {"slack", "teams", "email"}),
    ("cancelled",       {"slack", "teams"}),
    ("draft",           set()),     # not in rules
    ("unknown_state",   set()),
])
def test_rules_map_state_to_channels(state, expected):
    payload = {"po_status": state}
    assert _channels_for_event(payload) == expected


def test_rules_fall_back_to_state_field_when_po_status_missing():
    payload = {"state": "SHIPPED"}  # uppercase, no po_status
    assert _channels_for_event(payload) == {"slack", "teams"}


# ── _dispatch_event ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_shipped_fires_slack_and_teams_only():
    slack = _make_channel(enabled=True)
    teams = _make_channel(enabled=True)
    email = _make_channel(enabled=True)
    payload = {"po_status": "shipped", "transaction_id": "T1", "state": "SHIPPED"}

    await _dispatch_event(
        payload, slack=slack, teams=teams, email=email,
        recipients=_make_recipients(),
    )

    slack.send.assert_awaited_once_with(payload)
    teams.send.assert_awaited_once_with(payload)
    email.send.assert_not_called()


@pytest.mark.asyncio
async def test_delivered_fires_all_three_channels():
    slack = _make_channel(enabled=True)
    teams = _make_channel(enabled=True)
    email = _make_channel(enabled=True)
    payload = {"po_status": "delivered", "transaction_id": "T2",
               "state": "DELIVERED", "order_id": "O2"}

    await _dispatch_event(
        payload, slack=slack, teams=teams, email=email,
        recipients=_make_recipients(email="rajesh@example.com"),
    )

    slack.send.assert_awaited_once()
    teams.send.assert_awaited_once()
    email.send.assert_awaited_once_with("rajesh@example.com", payload)


@pytest.mark.asyncio
async def test_unknown_state_fires_no_channel():
    slack = _make_channel(enabled=True)
    teams = _make_channel(enabled=True)
    email = _make_channel(enabled=True)
    payload = {"po_status": "draft", "transaction_id": "T3"}

    await _dispatch_event(
        payload, slack=slack, teams=teams, email=email,
        recipients=_make_recipients(),
    )

    slack.send.assert_not_called()
    teams.send.assert_not_called()
    email.send.assert_not_called()


@pytest.mark.asyncio
async def test_disabled_channels_are_skipped():
    slack = _make_channel(enabled=False)  # disabled
    teams = _make_channel(enabled=True)
    email = _make_channel(enabled=False)
    payload = {"po_status": "delivered", "transaction_id": "T4"}

    await _dispatch_event(
        payload, slack=slack, teams=teams, email=email,
        recipients=_make_recipients(),
    )

    slack.send.assert_not_called()
    teams.send.assert_awaited_once()
    email.send.assert_not_called()


@pytest.mark.asyncio
async def test_email_skipped_when_no_recipient_resolved():
    slack = _make_channel(enabled=True)
    teams = _make_channel(enabled=True)
    email = _make_channel(enabled=True)
    payload = {"po_status": "delivered", "transaction_id": "T5"}

    await _dispatch_event(
        payload, slack=slack, teams=teams, email=email,
        recipients=_make_recipients(email=None),  # lookup returns None
    )

    slack.send.assert_awaited_once()
    teams.send.assert_awaited_once()
    email.send.assert_not_called()


@pytest.mark.asyncio
async def test_one_channel_failure_doesnt_block_others():
    slack = _make_channel(enabled=True)
    slack.send.side_effect = RuntimeError("Slack 503")
    teams = _make_channel(enabled=True)
    email = _make_channel(enabled=True)
    payload = {"po_status": "delivered", "transaction_id": "T6"}

    # Should NOT raise — dispatcher swallows per-channel exceptions
    await _dispatch_event(
        payload, slack=slack, teams=teams, email=email,
        recipients=_make_recipients(),
    )

    # Teams and email still got called
    teams.send.assert_awaited_once()
    email.send.assert_awaited_once()
