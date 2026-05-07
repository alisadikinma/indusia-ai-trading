"""HMAC verification for /v1/* — the Claude oversight bridge.

Contract (mirrored in <bot>/claude-routines callers, e.g.
crypto-bot/claude-routines, polymarket-bot/claude-routines):
    Each request must carry these headers:
        X-PULSE-Timestamp : str(int(unix_seconds))
        X-PULSE-Signature : hex(HMAC-SHA256(secret, f"{method}\\n{path}\\n{ts}\\n{body}"))

    Replay protection: timestamp drift > 60s → 401.
    Constant-time comparison: hmac.compare_digest (Iron Law: real auth, not toy).

Hard-fails on missing PULSE_HMAC_SECRET (Iron Law 3 — no silent default).
"""
from __future__ import annotations

import hashlib
import hmac
import os
import time
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status

# Allowable clock drift between Claude routine host and pulse-bridge host.
# Anything above 60s is almost certainly a replay attempt or a clock
# misconfiguration — either way, we reject.
MAX_TIMESTAMP_DRIFT_SECONDS = 60


def _get_secret() -> bytes:
    secret = os.environ.get("PULSE_HMAC_SECRET")
    if not secret:
        raise RuntimeError(
            "Missing PULSE_HMAC_SECRET — pulse-bridge /v1 refuses to verify "
            "Claude requests without an explicit shared secret."
        )
    if len(secret) < 32:
        raise RuntimeError(
            "PULSE_HMAC_SECRET must be at least 32 characters long."
        )
    return secret.encode("utf-8")


def _expected_signature(secret: bytes, method: str, path: str, ts: str, body: bytes) -> str:
    msg = b"\n".join([method.encode("utf-8"), path.encode("utf-8"), ts.encode("utf-8"), body])
    return hmac.new(secret, msg, hashlib.sha256).hexdigest()


async def verify_hmac(request: Request) -> None:
    """FastAPI dependency: raises 401 if the request is unsigned, replayed,
    or carries an invalid signature.

    The body bytes are read once and stashed on ``request.state._raw_body``
    so downstream handlers can re-use them without re-reading the stream.
    """
    ts_header = request.headers.get("x-pulse-timestamp") or request.headers.get("X-PULSE-Timestamp")
    sig_header = request.headers.get("x-pulse-signature") or request.headers.get("X-PULSE-Signature")
    if not ts_header or not sig_header:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing X-PULSE-Timestamp or X-PULSE-Signature header.",
        )

    # Parse + drift-check the timestamp.
    try:
        ts_int = int(ts_header)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid X-PULSE-Timestamp (not an integer).",
        ) from exc
    now = int(time.time())
    if abs(now - ts_int) > MAX_TIMESTAMP_DRIFT_SECONDS:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Timestamp drift exceeds 60s (replay protection).",
        )

    # Read the body bytes once. ASGI requests cache the body internally on
    # request.body() — handlers reading the JSON afterwards still work.
    body = await request.body()
    request.state._raw_body = body  # noqa: SLF001 — intentional cross-handler stash

    secret = _get_secret()
    # Include query string in the signed path so attackers cannot fiddle with
    # ?since= or ?limit= without invalidating the HMAC. Falls back to bare
    # path when there is no query.
    raw_path = request.url.path
    if request.url.query:
        raw_path = f"{raw_path}?{request.url.query}"
    expected = _expected_signature(secret, request.method, raw_path, ts_header, body)

    # Constant-time comparison to defeat timing oracles.
    if not hmac.compare_digest(expected, sig_header):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid HMAC signature.",
        )


HmacDep = Annotated[None, Depends(verify_hmac)]
hmac_dep = Depends(verify_hmac)
