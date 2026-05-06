"""Real Telegram bot wrapper — no mocks.

Reads TELEGRAM_BOT_TOKEN and TELEGRAM_OPERATOR_USER_ID from env. Hard-fails
if either is missing (no silent defaults — Iron Law 1 anti-placeholder).

Used by:
  * Phase 1: smoke test (this module's test).
  * Phase 11: HMAC-authed /halt kill switch.
  * Phase 10+: daily PnL summary cron.

Exposed:
  * send_alert(text, parse_mode='HTML') -> Telegram API JSON response
  * TelegramError exception
"""
from __future__ import annotations

import os
from typing import Any

import urllib.error
import urllib.parse
import urllib.request
import json


class TelegramError(RuntimeError):
    """Raised when Telegram API returns ok=False or transport fails."""


def _bot_token() -> str:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    if not token:
        raise TelegramError(
            "TELEGRAM_BOT_TOKEN missing from env — "
            "see infra/secrets/.env.example for setup steps."
        )
    return token


def _operator_user_id() -> int:
    raw = os.environ.get("TELEGRAM_OPERATOR_USER_ID", "")
    if not raw:
        raise TelegramError(
            "TELEGRAM_OPERATOR_USER_ID missing from env — "
            "see infra/secrets/.env.example for setup steps."
        )
    try:
        return int(raw)
    except ValueError as exc:
        raise TelegramError(
            f"TELEGRAM_OPERATOR_USER_ID must be an integer, got: {raw!r}"
        ) from exc


def send_alert(text: str, parse_mode: str = "HTML") -> dict[str, Any]:
    """Send a real message to the operator's Telegram. Raises TelegramError on failure.

    Args:
        text: message body (max 4096 chars per Telegram limit).
        parse_mode: 'HTML' (default) or 'MarkdownV2' or '' (plain).

    Returns:
        Parsed Telegram API response (the {ok, result} dict).

    Raises:
        TelegramError: API rejects the message OR transport fails OR env missing.
    """
    if not text or not text.strip():
        raise TelegramError("send_alert called with empty text — refusing to send.")

    if len(text) > 4096:
        raise TelegramError(
            f"send_alert text exceeds Telegram 4096-char limit ({len(text)} chars). "
            "Split into multiple alerts or summarize."
        )

    url = f"https://api.telegram.org/bot{_bot_token()}/sendMessage"
    payload = urllib.parse.urlencode(
        {
            "chat_id": _operator_user_id(),
            "text": text,
            "parse_mode": parse_mode,
            "disable_web_page_preview": "true",
        }
    ).encode("utf-8")

    req = urllib.request.Request(
        url,
        data=payload,
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        # Telegram returns useful JSON errors even on 4xx — surface them.
        try:
            error_body = exc.read().decode("utf-8")
            error_json = json.loads(error_body)
            description = error_json.get("description", "no description")
        except Exception:
            description = str(exc)
        raise TelegramError(
            f"Telegram API HTTP {exc.code}: {description}"
        ) from exc
    except urllib.error.URLError as exc:
        raise TelegramError(f"Telegram API transport failure: {exc.reason}") from exc

    parsed = json.loads(body)
    if not parsed.get("ok"):
        raise TelegramError(
            f"Telegram API returned ok=False: {parsed.get('description', body)}"
        )
    return parsed  # type: ignore[no-any-return]
