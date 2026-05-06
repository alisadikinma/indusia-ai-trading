"""Phase 1 integration test: real Telegram alert delivery.

This test sends a REAL message to the operator's Telegram. It does not mock.
It is skipped if TELEGRAM_BOT_TOKEN or TELEGRAM_OPERATOR_USER_ID are missing.

Setup:
  1. Operator opens Telegram, messages @BotFather, runs /newbot
  2. Capture the bot token, save to .env as TELEGRAM_BOT_TOKEN
  3. Send any message to the new bot from operator's account
  4. Curl https://api.telegram.org/bot<TOKEN>/getUpdates to find user_id
  5. Save user_id to .env as TELEGRAM_OPERATOR_USER_ID
  6. Run this test — operator's phone receives the message
"""
from __future__ import annotations

import os
import time

import pytest


pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not os.environ.get("TELEGRAM_BOT_TOKEN")
        or not os.environ.get("TELEGRAM_OPERATOR_USER_ID"),
        reason="TELEGRAM_BOT_TOKEN or TELEGRAM_OPERATOR_USER_ID missing — see test docstring",
    ),
]


def test_send_alert_delivers_to_operator() -> None:
    from infra.notifications.telegram import send_alert

    probe_marker = f"[ai-trading-247 phase-1 test {int(time.time())}]"
    response = send_alert(probe_marker)

    assert response["ok"] is True, f"Telegram API rejected message: {response}"
    assert response["result"]["text"].endswith(probe_marker), (
        "Sent text didn't round-trip through Telegram API"
    )


def test_send_alert_raises_on_invalid_token() -> None:
    """If token is invalid, send_alert must raise — never silently swallow."""
    from infra.notifications.telegram import TelegramError, send_alert

    saved = os.environ["TELEGRAM_BOT_TOKEN"]
    try:
        os.environ["TELEGRAM_BOT_TOKEN"] = "0000000000:invalid_token_for_test"
        with pytest.raises(TelegramError):
            send_alert("this should fail loudly")
    finally:
        os.environ["TELEGRAM_BOT_TOKEN"] = saved
