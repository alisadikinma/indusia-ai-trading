"""Per-route tests for /dashboard/* — empty-state, seeded-state, auth.

TDD step 1: the very first test below ('test_positions_empty_state_returns_empty_array')
is the failing-first test required by the orchestrator gate. It will fail until
dashboard_main + positions.py route are implemented.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import asyncpg
import pytest
from httpx import AsyncClient


# ---------------------------------------------------------------------------
# Auth gate (apply to one representative route — it's the same dependency).
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_positions_requires_auth_returns_401(app_client: AsyncClient) -> None:
    r = await app_client.get("/dashboard/positions")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_positions_invalid_jwt_returns_401(app_client: AsyncClient) -> None:
    r = await app_client.get(
        "/dashboard/positions",
        headers={"Authorization": "Bearer not-a-real-jwt"},
    )
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_chart_requires_auth(app_client: AsyncClient) -> None:
    r = await app_client.get("/dashboard/chart/ohlcv")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_journal_requires_auth(app_client: AsyncClient) -> None:
    r = await app_client.get("/dashboard/journal")
    assert r.status_code == 401


# ---------------------------------------------------------------------------
# /dashboard/positions
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_positions_empty_state_returns_empty_array(
    app_client: AsyncClient, auth_headers: dict[str, str], clean_db: asyncpg.Pool
) -> None:
    """TDD step 1 — empty signals table => returns []. Must NOT 500."""
    r = await app_client.get("/dashboard/positions", headers=auth_headers)
    assert r.status_code == 200
    assert r.json() == []


@pytest.mark.asyncio
async def test_positions_returns_approved_open_signals(
    app_client: AsyncClient,
    auth_headers: dict[str, str],
    clean_db: asyncpg.Pool,
) -> None:
    async with clean_db.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO brain.signals (pair, tf, signal_type, price_at_signal,
                claude_decision, claude_size_mult, claude_decided_at)
            VALUES
                ('BTC/USDT', '1m', 'enter_long', 50000, 'approve', 1.0, now()),
                ('ETH/USDT', '1m', 'enter_short', 2500, 'approve', 0.8, now()),
                ('SOL/USDT', '1m', 'enter_long', 100, 'veto', NULL, now())
            """
        )
    r = await app_client.get("/dashboard/positions", headers=auth_headers)
    assert r.status_code == 200
    body = r.json()
    pairs = [p["pair"] for p in body]
    assert "BTC/USDT" in pairs
    assert "ETH/USDT" in pairs
    assert "SOL/USDT" not in pairs  # vetoed
    btc = next(p for p in body if p["pair"] == "BTC/USDT")
    assert btc["side"] == "long"
    assert "signal_id" in btc
    assert "decided_at" in btc
    assert btc["intended_size_mult"] == 1.0


# ---------------------------------------------------------------------------
# /dashboard/chart/ohlcv
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_chart_returns_real_ohlcv(
    app_client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """brain.ohlcv has 44k+ rows from Phase 2; basic query should return data."""
    r = await app_client.get(
        "/dashboard/chart/ohlcv",
        params={"pair": "BTC/USDT", "tf": "1m", "limit": 10},
        headers=auth_headers,
    )
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body, list)
    assert len(body) <= 10
    if body:
        row = body[0]
        for key in ("ts", "open", "high", "low", "close", "volume"):
            assert key in row


@pytest.mark.asyncio
async def test_chart_empty_pair_returns_empty_array(
    app_client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    r = await app_client.get(
        "/dashboard/chart/ohlcv",
        params={"pair": "ZZZ/NOPE", "tf": "1m", "limit": 10},
        headers=auth_headers,
    )
    assert r.status_code == 200
    assert r.json() == []


@pytest.mark.asyncio
async def test_chart_limit_capped(
    app_client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    r = await app_client.get(
        "/dashboard/chart/ohlcv",
        params={"pair": "BTC/USDT", "tf": "1m", "limit": 99999},
        headers=auth_headers,
    )
    # 422 from query validation OR 200 with capped len <= 5000
    if r.status_code == 200:
        assert len(r.json()) <= 5000
    else:
        assert r.status_code == 422


# ---------------------------------------------------------------------------
# /dashboard/journal
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_journal_empty_state_returns_empty_page(
    app_client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """brain.brain_journal can't be truncated. Use very narrow time-filter to be empty."""
    r = await app_client.get(
        "/dashboard/journal",
        params={"from": "1900-01-01T00:00:00Z", "to": "1900-01-02T00:00:00Z"},
        headers=auth_headers,
    )
    assert r.status_code == 200
    body = r.json()
    assert "items" in body and "total" in body and "page" in body and "size" in body
    assert body["items"] == []
    assert body["total"] == 0


@pytest.mark.asyncio
async def test_journal_pagination_params(
    app_client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    r = await app_client.get(
        "/dashboard/journal",
        params={"page": 2, "size": 25},
        headers=auth_headers,
    )
    assert r.status_code == 200
    assert r.json()["page"] == 2
    assert r.json()["size"] == 25


# ---------------------------------------------------------------------------
# /dashboard/equity
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_equity_empty_state_returns_empty_array(
    app_client: AsyncClient, auth_headers: dict[str, str], clean_db: asyncpg.Pool
) -> None:
    r = await app_client.get("/dashboard/equity", headers=auth_headers)
    assert r.status_code == 200
    assert r.json() == []


@pytest.mark.asyncio
async def test_equity_returns_seeded_rows(
    app_client: AsyncClient, auth_headers: dict[str, str], clean_db: asyncpg.Pool
) -> None:
    async with clean_db.acquire() as conn:
        now = datetime.now(timezone.utc)
        await conn.execute(
            "INSERT INTO brain.equity_curve (ts, equity_usd, drawdown_pct) "
            "VALUES ($1, 10000, 0.05), ($2, 9500, 0.10)",
            now - timedelta(hours=1),
            now,
        )
    r = await app_client.get("/dashboard/equity", headers=auth_headers)
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 2
    assert "equity_usd" in body[0]


# ---------------------------------------------------------------------------
# /dashboard/backtest
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_backtest_runs_empty(
    app_client: AsyncClient, auth_headers: dict[str, str], clean_db: asyncpg.Pool
) -> None:
    r = await app_client.get("/dashboard/backtest/runs", headers=auth_headers)
    assert r.status_code == 200
    assert r.json() == []


@pytest.mark.asyncio
async def test_backtest_run_detail_404_when_missing(
    app_client: AsyncClient, auth_headers: dict[str, str], clean_db: asyncpg.Pool
) -> None:
    r = await app_client.get("/dashboard/backtest/runs/9999", headers=auth_headers)
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_backtest_run_detail_returns_full(
    app_client: AsyncClient, auth_headers: dict[str, str], clean_db: asyncpg.Pool
) -> None:
    async with clean_db.acquire() as conn:
        now = datetime.now(timezone.utc)
        rid = await conn.fetchval(
            """
            INSERT INTO brain.backtest_runs
                (strategy_version, fold_index, train_start, train_end,
                 test_start, test_end, parameters, metrics, gate_passed)
            VALUES ('v1.0', 1, $1, $2, $2, $3, $4::jsonb, $5::jsonb, true)
            RETURNING id
            """,
            now - timedelta(days=10),
            now - timedelta(days=5),
            now,
            json.dumps({"lookback": 14}),
            json.dumps({"sharpe": 1.8, "max_dd": 0.18}),
        )
    r = await app_client.get(f"/dashboard/backtest/runs/{rid}", headers=auth_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == rid
    assert body["strategy_version"] == "v1.0"
    assert body["metrics"]["sharpe"] == 1.8


# ---------------------------------------------------------------------------
# /dashboard/freqai
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_freqai_calibration_empty_until_phase7(
    app_client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """Phase 6 creates brain.freqai_history empty; calibration returns empty
    arrays with an explanatory note until Phase 7 populates retrains."""
    r = await app_client.get("/dashboard/freqai/calibration", headers=auth_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["calibration"] == []
    assert body["auc_history"] == []
    assert body["feature_importance"] is None
    assert "Phase 7" in body["note"]


@pytest.mark.asyncio
async def test_freqai_history_empty(
    app_client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    r = await app_client.get("/dashboard/freqai/history", headers=auth_headers)
    assert r.status_code == 200
    assert isinstance(r.json(), list)


# ---------------------------------------------------------------------------
# /dashboard/risk
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_risk_empty_returns_green(
    app_client: AsyncClient, auth_headers: dict[str, str], clean_db: asyncpg.Pool
) -> None:
    r = await app_client.get("/dashboard/risk/state", headers=auth_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["circuit_breaker_state"] == "green"
    assert body["drawdown_pct"] is None or body["drawdown_pct"] == 0


@pytest.mark.asyncio
async def test_risk_state_with_equity(
    app_client: AsyncClient, auth_headers: dict[str, str], clean_db: asyncpg.Pool
) -> None:
    async with clean_db.acquire() as conn:
        await conn.execute(
            "INSERT INTO brain.equity_curve (ts, equity_usd, drawdown_pct, open_positions) "
            "VALUES (now(), 9500, 0.05, 2)"
        )
    r = await app_client.get("/dashboard/risk/state", headers=auth_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["open_positions"] == 2
    assert float(body["drawdown_pct"]) == 0.05


# ---------------------------------------------------------------------------
# /dashboard/iteration-runs
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_iteration_runs_empty(
    app_client: AsyncClient, auth_headers: dict[str, str], clean_db: asyncpg.Pool
) -> None:
    r = await app_client.get("/dashboard/iteration-runs", headers=auth_headers)
    assert r.status_code == 200
    assert r.json() == []


@pytest.mark.asyncio
async def test_iteration_runs_returns_seeded(
    app_client: AsyncClient, auth_headers: dict[str, str], clean_db: asyncpg.Pool
) -> None:
    async with clean_db.acquire() as conn:
        await conn.execute(
            "INSERT INTO brain.iteration_runs (run_type, cycle_n, outcome) "
            "VALUES ('iteration', 1, 'IN_PROGRESS')"
        )
    r = await app_client.get("/dashboard/iteration-runs", headers=auth_headers)
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 1
    assert body[0]["run_type"] == "iteration"
