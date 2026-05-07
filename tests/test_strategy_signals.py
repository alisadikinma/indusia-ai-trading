"""Phase 3 — ClaudeOversightStrategy tests.

These tests exercise the strategy class in two layers:

1. Unit-level — feed synthetic OHLCV DataFrames (RandomState-seeded so
   they are deterministic) into populate_indicators / populate_entry_trend /
   populate_exit_trend and assert the entry/exit columns are set as the
   strategy contract requires.

2. Integration-level — exercise ``_write_signal_to_brain`` against the
   real Postgres instance running on 127.0.0.1:5544 (the docker compose
   service that Phase 1 set up). No mocking — Iron Law 3.

We keep the integration test under @pytest.mark.integration so the
unit suite still runs cleanly on a developer box without Postgres.
"""
from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime

import numpy as np
import pandas as pd
import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def trending_up_df() -> pd.DataFrame:
    """100 rows of 15m candles, monotonically climbing.

    Construction:
      * close = linspace(100, 130) + tiny gaussian noise (RNG seed 42)
      * EMA20 will cross above EMA50 around row ~30 and stay above
      * ADX14 will rise well above 25 once the trend is established

    Returns a DataFrame with columns Freqtrade's IStrategy expects:
    date, open, high, low, close, volume.
    """
    n = 100
    base = np.linspace(100.0, 130.0, n)
    noise = np.random.RandomState(42).normal(0, 0.5, n)
    close = base + noise
    df = pd.DataFrame(
        {
            "date": pd.date_range("2024-06-01", periods=n, freq="15min", tz="UTC"),
            "open": close - 0.1,
            "high": close + 0.5,
            "low": close - 0.5,
            "close": close,
            "volume": np.full(n, 100.0),
        }
    )
    return df


@pytest.fixture
def ranging_df() -> pd.DataFrame:
    """100 rows oscillating around 100; no sustained trend."""
    n = 100
    rng = np.random.RandomState(7)
    # sin wave around 100 with amplitude 1 + small noise — won't push ADX high
    t = np.arange(n)
    close = 100.0 + np.sin(t / 4.0) * 1.0 + rng.normal(0, 0.2, n)
    df = pd.DataFrame(
        {
            "date": pd.date_range("2024-06-01", periods=n, freq="15min", tz="UTC"),
            "open": close - 0.05,
            "high": close + 0.3,
            "low": close - 0.3,
            "close": close,
            "volume": np.full(n, 100.0),
        }
    )
    return df


@pytest.fixture
def trend_then_reversal_df() -> pd.DataFrame:
    """100 rows: climb then descend; EMA20 crosses BACK below EMA50 in the second half."""
    n = 100
    half = n // 2
    up = np.linspace(100.0, 130.0, half)
    down = np.linspace(130.0, 100.0, n - half)
    close = np.concatenate([up, down]) + np.random.RandomState(11).normal(0, 0.3, n)
    df = pd.DataFrame(
        {
            "date": pd.date_range("2024-06-01", periods=n, freq="15min", tz="UTC"),
            "open": close - 0.1,
            "high": close + 0.5,
            "low": close - 0.5,
            "close": close,
            "volume": np.full(n, 100.0),
        }
    )
    return df


# ---------------------------------------------------------------------------
# Unit tests
# ---------------------------------------------------------------------------
def test_strategy_imports() -> None:
    """The strategy class must be importable as a plain Python module."""
    from strategies.ClaudeOversightStrategy import ClaudeOversightStrategy

    assert ClaudeOversightStrategy.timeframe == "15m"
    assert ClaudeOversightStrategy.INTERFACE_VERSION == 3
    assert ClaudeOversightStrategy.can_short is False


def test_populate_entry_trend_fires_on_trending_up(trending_up_df: pd.DataFrame) -> None:
    from strategies.ClaudeOversightStrategy import ClaudeOversightStrategy

    s = ClaudeOversightStrategy({"runmode": "backtest"})
    df = s.populate_indicators(trending_up_df, {"pair": "BTC/USDT"})
    df = s.populate_entry_trend(df, {"pair": "BTC/USDT"})
    assert "enter_long" in df.columns
    assert df["enter_long"].sum() > 0, (
        "Strategy must fire at least one entry on a sustained uptrend "
        "(EMA20>EMA50, ADX>25, close>EMA20)."
    )


def test_populate_entry_trend_quiet_on_ranging(ranging_df: pd.DataFrame) -> None:
    from strategies.ClaudeOversightStrategy import ClaudeOversightStrategy

    s = ClaudeOversightStrategy({"runmode": "backtest"})
    df = s.populate_indicators(ranging_df, {"pair": "BTC/USDT"})
    df = s.populate_entry_trend(df, {"pair": "BTC/USDT"})
    # ADX on a small-amplitude oscillator stays well under 25
    assert df["enter_long"].sum() == 0, (
        "Strategy must NOT fire entries on a flat / ranging market — "
        "ADX should stay below 25."
    )


def test_populate_exit_trend_fires_on_reversal(trend_then_reversal_df: pd.DataFrame) -> None:
    from strategies.ClaudeOversightStrategy import ClaudeOversightStrategy

    s = ClaudeOversightStrategy({"runmode": "backtest"})
    df = s.populate_indicators(trend_then_reversal_df, {"pair": "BTC/USDT"})
    df = s.populate_exit_trend(df, {"pair": "BTC/USDT"})
    assert "exit_long" in df.columns
    assert df["exit_long"].sum() > 0, (
        "Strategy must fire at least one exit when EMA20 crosses back below EMA50."
    )


# ---------------------------------------------------------------------------
# Integration test — real Postgres write
# ---------------------------------------------------------------------------
@pytest.mark.integration
def test_signal_writeback_inserts_into_brain_signals() -> None:
    """confirm_trade_entry must persist a row to brain.signals using a real
    psycopg connection. The pg_notify trigger added in 002_pg_notify_triggers.sql
    will then fan the insert out to dashboard WS clients.
    """
    import psycopg

    pg_host = os.environ["POSTGRES_HOST"]
    pg_port = os.environ["POSTGRES_PORT"]
    pg_db = os.environ["POSTGRES_DB"]
    pg_user = os.environ["POSTGRES_USER"]
    pg_password = os.environ["POSTGRES_PASSWORD"]

    from strategies.ClaudeOversightStrategy import ClaudeOversightStrategy

    strat = ClaudeOversightStrategy({"runmode": "dry_run"})

    # Use a unique pair name so we don't collide with seeded fixtures or other
    # parallel test runs.
    test_pair = f"TEST{os.getpid()}/USDT"
    test_ts = datetime.now(tz=UTC)

    accepted = strat.confirm_trade_entry(
        pair=test_pair,
        order_type="limit",
        amount=0.01,
        rate=12345.67,
        time_in_force="GTC",
        current_time=test_ts,
        entry_tag="trend_ema_cross_adx",
        side="long",
    )
    assert accepted is True

    conn_str = (
        f"host={pg_host} port={pg_port} dbname={pg_db} "
        f"user={pg_user} password={pg_password}"
    )
    with psycopg.connect(conn_str) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT pair, tf, signal_type, price_at_signal "
            "FROM brain.signals WHERE pair = %s ORDER BY ts DESC LIMIT 1",
            (test_pair,),
        )
        row = cur.fetchone()
        assert row is not None, "expected a row in brain.signals after confirm_trade_entry"
        assert row[0] == test_pair
        assert row[1] == ClaudeOversightStrategy.timeframe
        assert row[2] == "enter_long"
        assert float(row[3]) == pytest.approx(12345.67)

        # Cleanup so reruns stay deterministic.
        cur.execute("DELETE FROM brain.signals WHERE pair = %s", (test_pair,))
        conn.commit()


# ---------------------------------------------------------------------------
# Phase 4 — confirm_trade_entry honors Claude's veto / approve verdict
# ---------------------------------------------------------------------------
def _pg_conn_str() -> str:
    return (
        f"host={os.environ['POSTGRES_HOST']} port={os.environ['POSTGRES_PORT']} "
        f"dbname={os.environ['POSTGRES_DB']} user={os.environ['POSTGRES_USER']} "
        f"password={os.environ['POSTGRES_PASSWORD']}"
    )


def _set_claude_decision(pair: str, decision: str | None) -> None:
    """Direct UPDATE on brain.signals.claude_decision for the latest row of
    the given pair. Used in tests only; bypasses the /v1/decide path because
    we're testing the strategy in isolation from the bridge.
    """
    import psycopg

    with psycopg.connect(_pg_conn_str()) as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE brain.signals SET claude_decision = %s, claude_decided_at = now() "
            "WHERE id = (SELECT id FROM brain.signals WHERE pair = %s ORDER BY ts DESC LIMIT 1)",
            (decision, pair),
        )
        conn.commit()


def _cleanup_test_signal_if_safe(pair: str) -> None:
    """Best-effort cleanup of a test pair's signals row.

    Note: brain.signals → brain.brain_journal has ON DELETE SET NULL, which
    triggers an UPDATE on the (append-only) journal table. We therefore only
    DELETE signals that have no journal row pointing at them — otherwise the
    Iron Law 5 trigger would correctly reject the cascade. Test pairs are
    suffixed with PID + uuid for cross-run uniqueness, so leftover rows do
    not interfere with reruns.
    """
    import psycopg

    with psycopg.connect(_pg_conn_str()) as conn, conn.cursor() as cur:
        cur.execute(
            "DELETE FROM brain.signals s WHERE s.pair = %s "
            "AND NOT EXISTS (SELECT 1 FROM brain.brain_journal j WHERE j.signal_id = s.id)",
            (pair,),
        )
        conn.commit()


@pytest.mark.integration
def test_confirm_trade_entry_aborts_on_veto() -> None:
    """If brain.signals.claude_decision='veto' for the just-written signal,
    confirm_trade_entry must return False on the next call for that signal."""
    from strategies.ClaudeOversightStrategy import ClaudeOversightStrategy

    strat = ClaudeOversightStrategy({"runmode": "dry_run"})
    test_pair = f"VETO{os.getpid()}{uuid.uuid4().hex[:6]}/USDT"
    test_ts = datetime.now(tz=UTC)
    try:
        # Step 1 — first call writes the signal (claude_decision = NULL).
        first = strat.confirm_trade_entry(
            pair=test_pair,
            order_type="limit",
            amount=0.01,
            rate=100.0,
            time_in_force="GTC",
            current_time=test_ts,
            entry_tag="trend_ema_cross_adx",
            side="long",
        )
        assert first is True, "with NULL decision, first call must proceed"

        # Step 2 — operator-equivalent: mark the signal vetoed.
        _set_claude_decision(test_pair, "veto")

        # Step 3 — re-call confirm_trade_entry on the same (pair, ts, side):
        # the ON CONFLICT path returns the same signal id, then the read sees
        # 'veto' and the call must abort.
        second = strat.confirm_trade_entry(
            pair=test_pair,
            order_type="limit",
            amount=0.01,
            rate=100.0,
            time_in_force="GTC",
            current_time=test_ts,
            entry_tag="trend_ema_cross_adx",
            side="long",
        )
        assert second is False, "veto must block the trade entry"
    finally:
        _cleanup_test_signal_if_safe(test_pair)


@pytest.mark.integration
def test_confirm_trade_entry_proceeds_on_approve() -> None:
    """An 'approve' decision must let confirm_trade_entry return True."""
    from strategies.ClaudeOversightStrategy import ClaudeOversightStrategy

    strat = ClaudeOversightStrategy({"runmode": "dry_run"})
    test_pair = f"APPR{os.getpid()}{uuid.uuid4().hex[:6]}/USDT"
    test_ts = datetime.now(tz=UTC)
    try:
        first = strat.confirm_trade_entry(
            pair=test_pair, order_type="limit", amount=0.01, rate=200.0,
            time_in_force="GTC", current_time=test_ts,
            entry_tag="trend_ema_cross_adx", side="long",
        )
        assert first is True
        _set_claude_decision(test_pair, "approve")
        second = strat.confirm_trade_entry(
            pair=test_pair, order_type="limit", amount=0.01, rate=200.0,
            time_in_force="GTC", current_time=test_ts,
            entry_tag="trend_ema_cross_adx", side="long",
        )
        assert second is True
    finally:
        _cleanup_test_signal_if_safe(test_pair)


@pytest.mark.integration
def test_confirm_trade_entry_proceeds_when_no_decision_yet() -> None:
    """NULL claude_decision (default) means rule-based default → proceed."""
    from strategies.ClaudeOversightStrategy import ClaudeOversightStrategy

    strat = ClaudeOversightStrategy({"runmode": "dry_run"})
    test_pair = f"NULL{os.getpid()}{uuid.uuid4().hex[:6]}/USDT"
    test_ts = datetime.now(tz=UTC)
    try:
        accepted = strat.confirm_trade_entry(
            pair=test_pair, order_type="limit", amount=0.01, rate=300.0,
            time_in_force="GTC", current_time=test_ts,
            entry_tag="trend_ema_cross_adx", side="long",
        )
        assert accepted is True
    finally:
        _cleanup_test_signal_if_safe(test_pair)
