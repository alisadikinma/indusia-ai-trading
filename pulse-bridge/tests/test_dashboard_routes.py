"""Per-route tests for /dashboard/* — empty-state, seeded-state, auth.

TDD step 1: the very first test below ('test_positions_empty_state_returns_empty_array')
is the failing-first test required by the orchestrator gate. It will fail until
dashboard_main + positions.py route are implemented.
"""
from __future__ import annotations

import json
import secrets
from datetime import datetime, timedelta, timezone

import asyncpg
import pytest
from httpx import AsyncClient


def _secrets_token() -> str:
    """Short URL-safe token for test row tagging — keeps Phase 1.5.F journal
    tests from cross-contaminating since brain.brain_journal is append-only."""
    return secrets.token_hex(4)


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
# /dashboard/journal — Phase 1.5.F filter / search / export extensions.
#
# brain.brain_journal is append-only (Iron Law 5), so we cannot TRUNCATE in
# clean_db. Instead, every test row uses a UUID-prefixed reasoning string we
# can target with the FTS `q` parameter to isolate it from other test rows.
# ---------------------------------------------------------------------------
async def _seed_journal_row(
    pool: asyncpg.Pool,
    *,
    regime: str,
    decision: str,
    reasoning: str,
    actual_outcome: str | None,
    confidence: int = 7,
) -> int:
    async with pool.acquire() as conn:
        return await conn.fetchval(
            """
            INSERT INTO brain.brain_journal
                (regime, decision, reasoning, confidence, actual_outcome,
                 expected_outcome)
            VALUES ($1, $2, $3, $4, $5, $6)
            RETURNING id
            """,
            regime,
            decision,
            reasoning,
            confidence,
            actual_outcome,
            "test expected",
        )


@pytest.mark.asyncio
async def test_journal_outcome_filter_win_only(
    app_client: AsyncClient,
    auth_headers: dict[str, str],
    db_pool: asyncpg.Pool,
) -> None:
    """outcome=win returns only entries with actual_outcome='win'."""
    tag = f"phase15f-outcome-{_secrets_token()}"
    await _seed_journal_row(
        db_pool,
        regime="trending_up",
        decision="approve",
        reasoning=f"{tag} winning trade",
        actual_outcome="win",
    )
    await _seed_journal_row(
        db_pool,
        regime="ranging",
        decision="veto",
        reasoning=f"{tag} losing trade",
        actual_outcome="loss",
    )
    await _seed_journal_row(
        db_pool,
        regime="volatile",
        decision="approve",
        reasoning=f"{tag} still open",
        actual_outcome=None,
    )

    r = await app_client.get(
        "/dashboard/journal",
        params={"q": tag, "outcome": "win", "size": 50},
        headers=auth_headers,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 1
    assert body["items"][0]["actual_outcome"] == "win"


@pytest.mark.asyncio
async def test_journal_outcome_filter_open(
    app_client: AsyncClient,
    auth_headers: dict[str, str],
    db_pool: asyncpg.Pool,
) -> None:
    """outcome=open returns only entries with actual_outcome IS NULL."""
    tag = f"phase15f-open-{_secrets_token()}"
    await _seed_journal_row(
        db_pool,
        regime="trending_up",
        decision="approve",
        reasoning=f"{tag} closed win",
        actual_outcome="win",
    )
    await _seed_journal_row(
        db_pool,
        regime="ranging",
        decision="approve",
        reasoning=f"{tag} still open trade",
        actual_outcome=None,
    )

    r = await app_client.get(
        "/dashboard/journal",
        params={"q": tag, "outcome": "open", "size": 50},
        headers=auth_headers,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 1
    assert body["items"][0]["actual_outcome"] is None


@pytest.mark.asyncio
async def test_journal_regime_multi_value_filter(
    app_client: AsyncClient,
    auth_headers: dict[str, str],
    db_pool: asyncpg.Pool,
) -> None:
    """regime supports comma-separated values: 'trending_up,ranging' returns either."""
    tag = f"phase15f-multi-{_secrets_token()}"
    await _seed_journal_row(
        db_pool,
        regime="trending_up",
        decision="approve",
        reasoning=f"{tag} up",
        actual_outcome="win",
    )
    await _seed_journal_row(
        db_pool,
        regime="ranging",
        decision="approve",
        reasoning=f"{tag} range",
        actual_outcome="loss",
    )
    await _seed_journal_row(
        db_pool,
        regime="volatile",
        decision="veto",
        reasoning=f"{tag} vol",
        actual_outcome=None,
    )

    r = await app_client.get(
        "/dashboard/journal",
        params={"q": tag, "regime": "trending_up,ranging", "size": 50},
        headers=auth_headers,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 2
    regimes = {item["regime"] for item in body["items"]}
    assert regimes == {"trending_up", "ranging"}


@pytest.mark.asyncio
async def test_journal_search_matches_reasoning_fts(
    app_client: AsyncClient,
    auth_headers: dict[str, str],
    db_pool: asyncpg.Pool,
) -> None:
    tag = f"phase15f-fts-{_secrets_token()}"
    await _seed_journal_row(
        db_pool,
        regime="trending_up",
        decision="approve",
        reasoning=f"{tag} reclaimed 50d moving average on rising volume",
        actual_outcome="win",
    )
    # An entry that should NOT match the search.
    await _seed_journal_row(
        db_pool,
        regime="trending_up",
        decision="approve",
        reasoning=f"{tag} unrelated pattern",
        actual_outcome="loss",
    )

    r = await app_client.get(
        "/dashboard/journal",
        params={"q": f"{tag} reclaimed", "size": 50},
        headers=auth_headers,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 1
    assert "reclaimed" in body["items"][0]["reasoning"]


@pytest.mark.asyncio
async def test_journal_export_csv_returns_text_csv(
    app_client: AsyncClient,
    auth_headers: dict[str, str],
    db_pool: asyncpg.Pool,
) -> None:
    tag = f"phase15f-csv-{_secrets_token()}"
    await _seed_journal_row(
        db_pool,
        regime="trending_up",
        decision="approve",
        reasoning=f"{tag} clean reasoning",
        actual_outcome="win",
    )
    # Reasoning with embedded comma + newline + double-quote — must be CSV-escaped.
    await _seed_journal_row(
        db_pool,
        regime="ranging",
        decision="veto",
        reasoning=f'{tag} multi,line\nquoted "text" inside',
        actual_outcome="loss",
    )

    r = await app_client.get(
        "/dashboard/journal/export.csv",
        params={"q": tag},
        headers=auth_headers,
    )
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    body = r.text
    # CSV header row.
    first_line = body.splitlines()[0]
    for col in (
        "id",
        "ts",
        "regime",
        "decision",
        "confidence",
        "reasoning",
        "expected_outcome",
        "actual_outcome",
    ):
        assert col in first_line
    # Both rows present.
    assert "clean reasoning" in body
    # Embedded comma / quote / newline correctly escaped (RFC 4180 quoting).
    assert '"' in body  # at minimum, fields containing commas are quoted
    # Doubled internal quotes per RFC 4180.
    assert '""text""' in body


@pytest.mark.asyncio
async def test_journal_export_csv_respects_filters(
    app_client: AsyncClient,
    auth_headers: dict[str, str],
    db_pool: asyncpg.Pool,
) -> None:
    tag = f"phase15f-csvf-{_secrets_token()}"
    await _seed_journal_row(
        db_pool,
        regime="trending_up",
        decision="approve",
        reasoning=f"{tag} approved row",
        actual_outcome="win",
    )
    await _seed_journal_row(
        db_pool,
        regime="trending_up",
        decision="veto",
        reasoning=f"{tag} vetoed row",
        actual_outcome=None,
    )

    r = await app_client.get(
        "/dashboard/journal/export.csv",
        params={"q": tag, "decision": "veto"},
        headers=auth_headers,
    )
    assert r.status_code == 200
    body = r.text
    assert "vetoed row" in body
    assert "approved row" not in body


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
