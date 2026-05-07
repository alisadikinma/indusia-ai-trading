"""WebSocket fan-out tests for /dashboard/ws.

These tests require:
  - Postgres reachable (via .env)
  - infra/migrations/002_pg_notify_triggers.sql applied (the conftest applies it
    on first use if it is not already present).
"""
from __future__ import annotations

import asyncio
import json
import os
import secrets
from pathlib import Path

import asyncpg
import pytest
import pytest_asyncio
import uvicorn


@pytest_asyncio.fixture(scope="module")
async def ensure_pg_notify_migration() -> None:
    """Apply 002_pg_notify_triggers.sql idempotently before WS tests run."""
    sql_path = Path(__file__).resolve().parents[2] / "infra/migrations/002_pg_notify_triggers.sql"
    sql = sql_path.read_text(encoding="utf-8")
    dsn = (
        f"postgresql://{os.environ['POSTGRES_USER']}:{os.environ['POSTGRES_PASSWORD']}"
        f"@{os.environ['POSTGRES_HOST']}:{os.environ['POSTGRES_PORT']}"
        f"/{os.environ['POSTGRES_DB']}"
    )
    conn = await asyncpg.connect(dsn=dsn)
    try:
        await conn.execute(sql)
    finally:
        await conn.close()


@pytest_asyncio.fixture
async def live_server(ensure_pg_notify_migration: None):  # noqa: ARG001
    """Run uvicorn against the dashboard app on a random localhost port."""
    from pulse_bridge.dashboard_main import app

    # Pick a free port.
    import socket

    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()

    config = uvicorn.Config(app=app, host="127.0.0.1", port=port, log_level="warning", lifespan="on")
    server = uvicorn.Server(config)
    task = asyncio.create_task(server.serve())
    # Wait for the server to come up.
    for _ in range(50):
        await asyncio.sleep(0.1)
        if server.started:
            break
    assert server.started, "uvicorn did not start in time"
    try:
        yield port
    finally:
        server.should_exit = True
        await task


@pytest.mark.asyncio
async def test_ws_rejects_without_token(live_server: int) -> None:
    import websockets

    url = f"ws://127.0.0.1:{live_server}/dashboard/ws"
    with pytest.raises(Exception):
        async with websockets.connect(url):
            pass


@pytest.mark.asyncio
async def test_ws_rejects_invalid_token(live_server: int) -> None:
    import websockets

    url = f"ws://127.0.0.1:{live_server}/dashboard/ws?token=garbage"
    with pytest.raises(Exception):
        async with websockets.connect(url):
            pass


def _make_jwt() -> str:
    import time

    from jose import jwt

    secret = os.environ["DASHBOARD_JWT_SECRET"]
    now = int(time.time())
    return jwt.encode(
        {
            "sub": "test-operator",
            "role": "operator",
            "iat": now,
            "exp": now + 3600,
            "iss": "bot-cockpit",
            "aud": "bot-cockpit-operator",
        },
        secret,
        algorithm="HS256",
    )


@pytest.mark.asyncio
async def test_ws_receives_signal_notification(live_server: int) -> None:
    """INSERT into brain.signals → WS client receives a dashboard_signals payload."""
    import websockets

    token = _make_jwt()
    url = f"ws://127.0.0.1:{live_server}/dashboard/ws?token={token}"

    dsn = (
        f"postgresql://{os.environ['POSTGRES_USER']}:{os.environ['POSTGRES_PASSWORD']}"
        f"@{os.environ['POSTGRES_HOST']}:{os.environ['POSTGRES_PORT']}"
        f"/{os.environ['POSTGRES_DB']}"
    )

    async with websockets.connect(url) as ws:
        # Give the server a beat to register the listener.
        await asyncio.sleep(0.2)

        marker_pair = f"WSTEST/{secrets.token_hex(4)}"
        # Insert a signal (this fires the AFTER INSERT trigger → pg_notify).
        conn = await asyncpg.connect(dsn=dsn)
        try:
            await conn.execute(
                """
                INSERT INTO brain.signals (pair, tf, signal_type, price_at_signal)
                VALUES ($1, '1m', 'enter_long', 1)
                """,
                marker_pair,
            )
        finally:
            await conn.close()

        # Wait up to 3 seconds for our marker to come through.
        deadline = asyncio.get_running_loop().time() + 3.0
        received_pair: str | None = None
        while asyncio.get_running_loop().time() < deadline and received_pair != marker_pair:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=1.0)
            except asyncio.TimeoutError:
                continue
            msg = json.loads(raw)
            if msg.get("type") == "ping":
                await ws.send(json.dumps({"type": "pong"}))
                continue
            if msg.get("channel") == "dashboard_signals":
                payload = msg.get("payload") or {}
                if payload.get("pair") == marker_pair:
                    received_pair = marker_pair
                    break
        assert received_pair == marker_pair, "did not receive expected dashboard_signals notify"


@pytest.mark.asyncio
async def test_ws_disconnect_cleans_up_broadcaster(live_server: int) -> None:
    import websockets

    from pulse_bridge.ws_pg_listener import broadcaster

    token = _make_jwt()
    url = f"ws://127.0.0.1:{live_server}/dashboard/ws?token={token}"

    starting = broadcaster.client_count
    async with websockets.connect(url):
        await asyncio.sleep(0.2)
        assert broadcaster.client_count == starting + 1
    # Give the server a moment to unregister.
    await asyncio.sleep(0.4)
    assert broadcaster.client_count == starting
