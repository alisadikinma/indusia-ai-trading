"""FastAPI app entry for the Dashboard read-only API (Phase 1.5.B + C).

Referenced by infra/systemd/dashboard-api.service as `pulse_bridge.dashboard_main:app`
and listens on 127.0.0.1:8081 in production.

NB: Phase 4 will own pulse_bridge/main.py for the Claude↔Freqtrade /v1/* bridge.
This module is the dashboard router half only.
"""
from __future__ import annotations

import os
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .db import create_pool
from .dashboard_routes import (
    auth as auth_routes,
)
from .dashboard_routes import (
    backtest,
    chart,
    equity,
    freqai,
    iteration,
    journal,
    positions,
    risk,
)
from .ws_pg_listener import broadcaster
from .ws_pg_listener import router as ws_router


def _require_origin() -> str:
    origin = os.environ.get("DASHBOARD_UI_ORIGIN")
    if not origin:
        raise RuntimeError(
            "Missing DASHBOARD_UI_ORIGIN — pulse-bridge dashboard refuses to start "
            "without an explicit allowed CORS origin."
        )
    return origin


class _LifespanState:
    """Tiny holder so the test conftest can drive startup/shutdown manually
    (httpx ASGITransport doesn't fire FastAPI's lifespan)."""

    def __init__(self) -> None:
        self._started = False

    async def startup(self) -> None:
        if self._started:
            return
        app.state.pg_pool = await create_pool()
        await broadcaster.start()
        self._started = True

    async def shutdown(self) -> None:
        if not self._started:
            return
        await broadcaster.stop()
        pool = getattr(app.state, "pg_pool", None)
        if pool is not None:
            await pool.close()
            app.state.pg_pool = None
        self._started = False


lifespan_state = _LifespanState()


@asynccontextmanager
async def lifespan(_app: FastAPI):  # type: ignore[no-untyped-def]
    await lifespan_state.startup()
    try:
        yield
    finally:
        await lifespan_state.shutdown()


app = FastAPI(
    title="AI Trading 24/7 — Dashboard API",
    version="0.0.1",
    docs_url="/docs" if __debug__ else None,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[_require_origin()],
    allow_credentials=True,
    allow_methods=["GET"],
    allow_headers=["authorization", "content-type"],
)


jwt_dep = Depends(auth_routes.verify_jwt)

app.include_router(chart.router, prefix="/dashboard/chart", tags=["chart"], dependencies=[jwt_dep])
app.include_router(journal.router, prefix="/dashboard/journal", tags=["journal"], dependencies=[jwt_dep])
app.include_router(positions.router, prefix="/dashboard/positions", tags=["positions"], dependencies=[jwt_dep])
app.include_router(equity.router, prefix="/dashboard/equity", tags=["equity"], dependencies=[jwt_dep])
app.include_router(backtest.router, prefix="/dashboard/backtest", tags=["backtest"], dependencies=[jwt_dep])
app.include_router(freqai.router, prefix="/dashboard/freqai", tags=["freqai"], dependencies=[jwt_dep])
app.include_router(risk.router, prefix="/dashboard/risk", tags=["risk"], dependencies=[jwt_dep])
app.include_router(iteration.router, prefix="/dashboard/iteration-runs", tags=["iteration"], dependencies=[jwt_dep])

# WebSocket auth is handled inside the handler (FastAPI dependencies don't gate the
# upgrade cleanly when reading from a query-string token).
app.include_router(ws_router, prefix="/dashboard/ws", tags=["ws"])


@app.get("/dashboard/health", tags=["meta"])
async def health() -> dict[str, str]:
    """Unauthenticated liveness probe — returns 200 if the asyncpg pool is up."""
    pool = getattr(app.state, "pg_pool", None)
    if pool is None:
        return {"status": "starting"}
    return {"status": "ok"}
