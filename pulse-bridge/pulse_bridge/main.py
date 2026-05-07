"""FastAPI app entry for the PULSE bridge — Claude ↔ Freqtrade.

Phase 4 deliverable. Referenced by infra/systemd/pulse-bridge.service as
``pulse_bridge.main:app`` and listens on the Unix socket /run/pulse/pulse.sock
in production.

All /v1/* endpoints are HMAC-protected (see pulse_bridge.v1_routes.auth).
The dashboard read-only API is a sibling module: pulse_bridge.dashboard_main —
both share the same package + db helpers but are deployed as separate
processes (systemd: pulse-bridge.service vs dashboard-api.service).
"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from .db import create_pool
from .v1_routes import context as context_routes
from .v1_routes import decide as decide_routes
from .v1_routes import pending as pending_routes


class _LifespanState:
    """Holder so the test harness can drive startup/shutdown manually
    (httpx ASGITransport doesn't fire FastAPI's lifespan)."""

    def __init__(self) -> None:
        self._started = False

    async def startup(self) -> None:
        if self._started:
            return
        app.state.pg_pool = await create_pool()
        self._started = True

    async def shutdown(self) -> None:
        if not self._started:
            return
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
    title="AI Trading 24/7 — PULSE bridge",
    version="0.0.1",
    docs_url="/docs" if __debug__ else None,
    lifespan=lifespan,
)


app.include_router(decide_routes.router, prefix="/v1", tags=["decide"])
app.include_router(pending_routes.router, prefix="/v1", tags=["pending"])
app.include_router(context_routes.router, prefix="/v1", tags=["context"])


@app.get("/v1/health", tags=["meta"])
async def health() -> dict[str, str]:
    """Unauthenticated liveness probe — returns 200 if the asyncpg pool is up.

    Intentionally NOT HMAC-gated so systemd / load-balancer probes can hit it
    without holding the shared secret.
    """
    pool = getattr(app.state, "pg_pool", None)
    if pool is None:
        return {"status": "starting"}
    return {"status": "ok"}
