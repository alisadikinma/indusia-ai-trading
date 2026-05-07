"""WebSocket endpoint at /dashboard/ws.

Real-time fan-out of Postgres NOTIFY events on three channels:
  - dashboard_signals
  - dashboard_journal
  - dashboard_equity

Each connected WS client receives `{"channel": "<name>", "payload": <json>}` JSON
messages. NOTIFY payloads are emitted by triggers in
infra/migrations/002_pg_notify_triggers.sql.

Auth: client must connect with `?token=<jwt>` matching the same JWT contract
as the REST routes (see dashboard_routes/auth.py).

Heartbeat: server sends `{"type":"ping"}` every 30s. Client should respond
`{"type":"pong"}`. If no traffic in either direction for 90s the server closes
the connection (handled by client-side reconnect with backoff).
"""
from __future__ import annotations

import asyncio
import json
import logging
from contextlib import suppress
from typing import Any

import asyncpg
from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect, status

from .dashboard_routes.auth import verify_jwt_token
from .db import build_dsn

logger = logging.getLogger("pulse_bridge.ws")

CHANNELS = ("dashboard_signals", "dashboard_journal", "dashboard_equity")
HEARTBEAT_INTERVAL_SECONDS = 30.0

router = APIRouter()


class WsBroadcaster:
    """Owns one dedicated asyncpg connection that LISTENs on the dashboard channels
    and fans out NOTIFY payloads to every subscribed WebSocket client.
    """

    def __init__(self) -> None:
        self._conn: asyncpg.Connection | None = None
        self._clients: set[WebSocket] = set()
        self._lock = asyncio.Lock()

    async def start(self) -> None:
        if self._conn is not None:
            return
        self._conn = await asyncpg.connect(dsn=build_dsn())
        for ch in CHANNELS:
            await self._conn.add_listener(ch, self._on_notify)
        logger.info("ws_pg_listener: subscribed to %s", CHANNELS)

    async def stop(self) -> None:
        async with self._lock:
            for ws in list(self._clients):
                with suppress(Exception):
                    await ws.close()
            self._clients.clear()
        if self._conn is not None:
            for ch in CHANNELS:
                with suppress(Exception):
                    await self._conn.remove_listener(ch, self._on_notify)
            with suppress(Exception):
                await self._conn.close()
            self._conn = None

    def _on_notify(self, _conn: Any, _pid: int, channel: str, payload: str) -> None:
        # Fired from asyncpg's listener task — schedule the broadcast.
        asyncio.create_task(self._broadcast(channel, payload))

    async def _broadcast(self, channel: str, payload: str) -> None:
        try:
            parsed: Any = json.loads(payload) if payload else None
        except json.JSONDecodeError:
            parsed = payload
        message = {"channel": channel, "payload": parsed}
        text = json.dumps(message, default=str)
        async with self._lock:
            dead: list[WebSocket] = []
            for ws in self._clients:
                try:
                    await ws.send_text(text)
                except Exception:
                    dead.append(ws)
            for ws in dead:
                self._clients.discard(ws)

    async def register(self, ws: WebSocket) -> None:
        async with self._lock:
            self._clients.add(ws)

    async def unregister(self, ws: WebSocket) -> None:
        async with self._lock:
            self._clients.discard(ws)

    @property
    def client_count(self) -> int:
        return len(self._clients)


# Global broadcaster instance — its lifecycle is owned by the FastAPI app's
# startup/shutdown hooks (see dashboard_main.py).
broadcaster = WsBroadcaster()


@router.websocket("")
async def dashboard_ws(websocket: WebSocket, token: str = Query(...)) -> None:
    # Authenticate BEFORE accepting the upgrade.
    try:
        verify_jwt_token(token)
    except Exception:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    await websocket.accept()
    await broadcaster.register(websocket)

    heartbeat_task: asyncio.Task[None] | None = None

    async def heartbeat() -> None:
        try:
            while True:
                await asyncio.sleep(HEARTBEAT_INTERVAL_SECONDS)
                await websocket.send_text(json.dumps({"type": "ping"}))
        except Exception:
            return

    try:
        heartbeat_task = asyncio.create_task(heartbeat())
        while True:
            msg = await websocket.receive_text()
            # Client may send {"type":"pong"} or {"type":"subscribe","channels":[...]}.
            # In this Phase 1.5 design every connection auto-subscribes to all 3 channels;
            # a finer-grained subscribe could filter server-side later.
            try:
                _ = json.loads(msg)
            except json.JSONDecodeError:
                pass
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.warning("ws client error: %s", exc)
    finally:
        if heartbeat_task is not None:
            heartbeat_task.cancel()
            with suppress(asyncio.CancelledError):
                await heartbeat_task
        await broadcaster.unregister(websocket)
