"""Pytest fixtures for pulse-bridge dashboard tests.

Talks to the real Postgres on 127.0.0.1:5544 (via env loaded from repo-root .env).
No mocks — Iron Law 3.

Important: brain.brain_journal has trigger-enforced INSERT-only (Iron Law 5).
For test cleanup we mark synthetic test rows with `pair_prefix='TEST/'` and only
INSERT/SELECT — never DELETE — to keep the audit log invariant honored.
For tables without that constraint (signals, equity_curve, backtest_runs,
iteration_runs) we TRUNCATE per-test for isolation. We never truncate
brain.ohlcv (Phase 2 loaded ~44k rows we want to query).
"""
from __future__ import annotations

import os
import secrets as _secrets
import time
from collections.abc import AsyncIterator
from pathlib import Path

import asyncpg
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient


def _load_repo_env() -> None:
    """Load repo-root .env into process env if not already populated."""
    repo_root = Path(__file__).resolve().parents[2]
    env_file = repo_root / ".env"
    if not env_file.is_file():
        return
    for raw in env_file.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        k = k.strip()
        v = v.strip()
        if k and k not in os.environ:
            os.environ[k] = v


_load_repo_env()

# Provide a deterministic JWT secret for tests if operator hasn't set one.
# We do NOT silently default in production — only inject when running pytest.
if not os.environ.get("DASHBOARD_JWT_SECRET"):
    os.environ["DASHBOARD_JWT_SECRET"] = _secrets.token_urlsafe(48)
if not os.environ.get("DASHBOARD_UI_ORIGIN"):
    os.environ["DASHBOARD_UI_ORIGIN"] = "http://127.0.0.1:3000"


def _pg_dsn() -> str:
    return (
        f"postgresql://{os.environ['POSTGRES_USER']}:{os.environ['POSTGRES_PASSWORD']}"
        f"@{os.environ['POSTGRES_HOST']}:{os.environ['POSTGRES_PORT']}"
        f"/{os.environ['POSTGRES_DB']}"
    )


@pytest_asyncio.fixture
async def db_pool() -> AsyncIterator[asyncpg.Pool]:
    pool = await asyncpg.create_pool(dsn=_pg_dsn(), min_size=1, max_size=3)
    try:
        yield pool
    finally:
        await pool.close()


@pytest_asyncio.fixture
async def clean_db(db_pool: asyncpg.Pool) -> AsyncIterator[asyncpg.Pool]:
    """Reset all mutable brain.* tables EXCEPT brain.ohlcv and brain.brain_journal.

    brain.ohlcv  — keep Phase 2 data so chart route can return real rows
    brain.brain_journal — append-only; tests filter their inserts via reasoning prefix
    """
    async with db_pool.acquire() as conn:
        # signals first because journal references it
        await conn.execute("TRUNCATE brain.signals RESTART IDENTITY CASCADE")
        await conn.execute("TRUNCATE brain.equity_curve")
        await conn.execute("TRUNCATE brain.backtest_runs RESTART IDENTITY")
        await conn.execute("TRUNCATE brain.iteration_runs RESTART IDENTITY")
    yield db_pool


@pytest.fixture
def auth_token() -> str:
    """Issue a valid JWT matching dashboard-ui/src/lib/auth.ts conventions."""
    from jose import jwt

    secret = os.environ["DASHBOARD_JWT_SECRET"]
    now = int(time.time())
    payload = {
        "sub": "test-operator",
        "role": "operator",
        "iat": now,
        "exp": now + 3600,
        "iss": "bot-cockpit",
        "aud": "bot-cockpit-operator",
    }
    return jwt.encode(payload, secret, algorithm="HS256")


@pytest.fixture
def auth_headers(auth_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {auth_token}"}


@pytest_asyncio.fixture
async def app_client() -> AsyncIterator[AsyncClient]:
    """Async test client bound to the dashboard FastAPI app."""
    from pulse_bridge.dashboard_main import app, lifespan_state

    # Force lifespan startup so the asyncpg pool is initialized.
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Manually trigger startup since ASGITransport doesn't run lifespan.
        await lifespan_state.startup()
        try:
            yield client
        finally:
            await lifespan_state.shutdown()
