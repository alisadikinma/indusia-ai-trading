"""Phase 9 tests for the walk-forward backtest orchestrator.

The orchestrator under test lives at ``infra/backtest/walk_forward.py``. Its
job is to:

  1. Compute N expanding-window folds (delegating to
     ``infra.scripts.walkforward_folds.generate_folds`` so the regime-aware
     fold contract from Phase 0.5 is reused — single source of truth).
  2. Run a Freqtrade ``backtesting`` invocation per fold.
  3. Parse Freqtrade's JSON result, compute Sharpe/Sortino/MaxDD/profit
     factor/expectancy from the trade list, persist a row to
     ``brain.backtest_runs`` (one row per fold).
  4. Apply the Iron Law 2 gate (Sharpe>1.5, MaxDD<25%, PF>1.4, trades>=100
     in ALL folds) and emit a JSON verdict to stdout.
  5. Return exit code 0 on PASS, 2 on FAIL.

These tests cover the pure-Python pieces — fold computation degradation,
gate evaluation, and Postgres round-trip. The integration test that
actually drives Freqtrade backtesting is OUT OF SCOPE here (multi-hour
compute; the operator runs it manually per the plan §9 step 3).

Iron Law 3 enforcement: every test that touches Postgres uses a real
connection (``psycopg`` against the local trading db) wrapped in a
transaction that rolls back. No mocked DB fixtures.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import psycopg
import pytest


REPO_ROOT = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# Import surface — RED until infra/backtest/walk_forward.py exists.
# ---------------------------------------------------------------------------
def test_orchestrator_module_imports() -> None:
    """RED→GREEN: the orchestrator module must be importable."""
    from infra.backtest import walk_forward  # noqa: F401


def test_orchestrator_exposes_public_api() -> None:
    from infra.backtest import walk_forward as wf

    # Public surface used by main() and test suite.
    assert callable(getattr(wf, "compute_folds", None))
    assert callable(getattr(wf, "evaluate_gate", None))
    assert callable(getattr(wf, "metrics_from_trades", None))
    assert callable(getattr(wf, "main", None))
    # Gate thresholds — published as module constants for audit/citation.
    assert wf.MIN_SHARPE == 1.5
    assert wf.MAX_DRAWDOWN == 0.25
    assert wf.MIN_PROFIT_FACTOR == 1.4
    assert wf.MIN_TRADES_PER_FOLD == 100


# ---------------------------------------------------------------------------
# Fold computation — degradation and pass-through behaviour.
# ---------------------------------------------------------------------------
def test_compute_folds_full_range_yields_5() -> None:
    """When the data range covers 2018→2026, default plan returns 5 folds."""
    from infra.backtest import walk_forward as wf

    folds = wf.compute_folds(
        train_floor=date(2018, 1, 1),
        end=date(2026, 5, 7),
        n_folds=5,
        accept_degraded=False,
    )
    assert len(folds) == 5
    # Anchored mode: every fold's train_start pinned to floor.
    for f in folds:
        assert f.train_start == date(2018, 1, 1)


def test_compute_folds_short_range_degrades_when_accepted() -> None:
    """A tight ~2-year range (2024-01-01..2026-01-20, 751 days) cannot
    host 5×180d test windows + the initial 365-day training reservation
    (need >= 902 days), but it CAN host 3 folds (need >= 541 days). With
    ``accept_degraded=True`` and ``n_folds=3``, succeeds.

    ``post_etf_required=False`` is required because the ETF date
    (2024-01-11) lands inside the initial training window for this range
    and the regime-aware generator would otherwise refuse the plan
    altogether — orthogonal to the degradation behaviour under test.
    """
    from infra.backtest import walk_forward as wf

    # First confirm the strict 5-fold ask DOES fail (no silent degradation).
    with pytest.raises(wf.DegradedFoldPlan):
        wf.compute_folds(
            train_floor=date(2024, 1, 1),
            end=date(2026, 1, 20),
            n_folds=5,
            accept_degraded=False,
            post_etf_required=False,
        )

    # With accept_degraded=True and a fitting n_folds, succeeds.
    folds = wf.compute_folds(
        train_floor=date(2024, 1, 1),
        end=date(2026, 1, 20),
        n_folds=3,
        accept_degraded=True,
        post_etf_required=False,
    )
    assert len(folds) == 3


def test_compute_folds_degraded_without_accept_flag_fails_loud() -> None:
    """Iron Law 3: hard fail if data is short and operator hasn't opted in.

    Same too-tight range as the previous test (2024-01-01..2026-01-20
    cannot host 5 folds). The ``accept_degraded=False`` path must raise
    DegradedFoldPlan with a hint mentioning the flag name.
    """
    from infra.backtest import walk_forward as wf

    with pytest.raises(wf.DegradedFoldPlan) as exc:
        wf.compute_folds(
            train_floor=date(2024, 1, 1),
            end=date(2026, 1, 20),
            n_folds=5,
            accept_degraded=False,
            post_etf_required=False,
        )
    msg = str(exc.value).lower()
    assert "accept-degraded" in msg or "accept_degraded" in msg


def test_compute_folds_zero_folds_is_loud_error() -> None:
    """If math somehow yields 0 folds, error must surface — never silent [].

    This uses a range so short the underlying generator raises ValueError
    even with accept_degraded=True (n_folds=5 cannot fit 127 days). Our
    wrapper re-raises as DegradedFoldPlan; with accept_degraded=False it
    is the same exception, with accept_degraded=True it still raises.
    Either way, no silent empty list.
    """
    from infra.backtest import walk_forward as wf

    with pytest.raises(wf.DegradedFoldPlan):
        wf.compute_folds(
            train_floor=date(2026, 1, 1),
            end=date(2026, 5, 7),
            n_folds=5,
            accept_degraded=True,
        )


# ---------------------------------------------------------------------------
# Gate evaluation — pure function on a list of fold metrics dicts.
# ---------------------------------------------------------------------------
def _fold_metrics(
    *,
    sharpe: float = 1.8,
    max_dd: float = 0.18,
    profit_factor: float = 1.6,
    total_trades: int = 150,
) -> dict:
    return {
        "sharpe": sharpe,
        "sortino": sharpe * 1.2,  # plausible
        "max_dd": max_dd,
        "profit_factor": profit_factor,
        "total_trades": total_trades,
        "win_rate": 0.55,
        "expectancy": 0.012,
    }


def test_evaluate_gate_all_pass() -> None:
    from infra.backtest import walk_forward as wf

    folds = [
        {"fold_index": i, "metrics": _fold_metrics()} for i in range(1, 6)
    ]
    verdict = wf.evaluate_gate(folds)
    assert verdict["verdict"] == "PASS"
    assert verdict["criteria_failed"] == []


def test_evaluate_gate_low_sharpe_fold_fails() -> None:
    from infra.backtest import walk_forward as wf

    folds = [{"fold_index": i, "metrics": _fold_metrics()} for i in range(1, 6)]
    folds[2]["metrics"]["sharpe"] = 1.2  # below 1.5
    verdict = wf.evaluate_gate(folds)
    assert verdict["verdict"] == "FAIL"
    failed = verdict["criteria_failed"]
    assert any("sharpe" in c.lower() and "fold 3" in c.lower() for c in failed)


def test_evaluate_gate_excess_drawdown_fails() -> None:
    from infra.backtest import walk_forward as wf

    folds = [{"fold_index": i, "metrics": _fold_metrics()} for i in range(1, 6)]
    folds[0]["metrics"]["max_dd"] = 0.32  # > 25%
    verdict = wf.evaluate_gate(folds)
    assert verdict["verdict"] == "FAIL"
    assert any("drawdown" in c.lower() for c in verdict["criteria_failed"])


def test_evaluate_gate_low_profit_factor_fails() -> None:
    from infra.backtest import walk_forward as wf

    folds = [{"fold_index": i, "metrics": _fold_metrics()} for i in range(1, 6)]
    folds[4]["metrics"]["profit_factor"] = 1.1
    verdict = wf.evaluate_gate(folds)
    assert verdict["verdict"] == "FAIL"
    assert any(
        "profit_factor" in c.lower() or "profit factor" in c.lower()
        for c in verdict["criteria_failed"]
    )


def test_evaluate_gate_insufficient_trades_fails() -> None:
    from infra.backtest import walk_forward as wf

    folds = [{"fold_index": i, "metrics": _fold_metrics()} for i in range(1, 6)]
    folds[1]["metrics"]["total_trades"] = 80
    verdict = wf.evaluate_gate(folds)
    assert verdict["verdict"] == "FAIL"
    assert any("trade" in c.lower() for c in verdict["criteria_failed"])


def test_evaluate_gate_empty_input_is_loud() -> None:
    """Iron Law 3: never silently PASS on zero folds."""
    from infra.backtest import walk_forward as wf

    with pytest.raises(ValueError):
        wf.evaluate_gate([])


def test_evaluate_gate_multiple_failures_all_listed() -> None:
    from infra.backtest import walk_forward as wf

    folds = [{"fold_index": i, "metrics": _fold_metrics()} for i in range(1, 6)]
    folds[0]["metrics"]["sharpe"] = 1.0
    folds[2]["metrics"]["max_dd"] = 0.40
    folds[4]["metrics"]["total_trades"] = 50
    verdict = wf.evaluate_gate(folds)
    assert verdict["verdict"] == "FAIL"
    # All three distinct failures listed
    assert len(verdict["criteria_failed"]) >= 3


# ---------------------------------------------------------------------------
# Metrics from trades — pure function on a trades list.
# ---------------------------------------------------------------------------
def test_metrics_from_trades_zero_trades() -> None:
    from infra.backtest import walk_forward as wf

    m = wf.metrics_from_trades(trades=[], starting_balance=1000.0)
    assert m["total_trades"] == 0
    # When empty, sharpe/profit_factor undefined. Spec: must NOT silently
    # report 0 (Iron Law 3); use None and the gate will flag total_trades<100.
    assert m["sharpe"] is None
    assert m["profit_factor"] is None
    assert m["max_dd"] is None
    assert m["win_rate"] is None
    assert m["expectancy"] is None


def test_metrics_from_trades_realistic_pnl_series() -> None:
    """Known-input check — verifies sharpe/PF/MaxDD computation with a
    deterministic series of profits/losses that has a hand-computable answer."""
    from infra.backtest import walk_forward as wf

    # 10 trades, 6 wins of +20, 4 losses of -10 → net +80, PF = 120/40 = 3.0.
    # win_rate = 0.6, expectancy = +8.0.
    trades = []
    base_ts = datetime(2024, 1, 1, tzinfo=timezone.utc)
    pnl_series = [20.0, -10.0, 20.0, -10.0, 20.0, -10.0, 20.0, -10.0, 20.0, 20.0]
    for i, pnl in enumerate(pnl_series):
        trades.append(
            {
                "open_date": base_ts.replace(day=1 + i),
                "close_date": base_ts.replace(day=1 + i),
                "profit_abs": pnl,
            }
        )

    m = wf.metrics_from_trades(trades=trades, starting_balance=1000.0)
    assert m["total_trades"] == 10
    assert m["win_rate"] == pytest.approx(0.6, rel=1e-6)
    assert m["profit_factor"] == pytest.approx(3.0, rel=1e-6)
    assert m["expectancy"] == pytest.approx(8.0, rel=1e-6)
    # Max drawdown: lowest point of equity curve relative to running peak.
    # Equity curve: 1000+20=1020, 1010, 1030, 1020, 1040, 1030, 1050, 1040,
    # 1060, 1080. Drawdowns: 0, -10/1020, 0, -10/1030, 0, -10/1040, 0,
    # -10/1050, 0, 0. Max DD = 10/1050 ≈ 0.00952.
    assert m["max_dd"] is not None
    assert 0 < m["max_dd"] < 0.02
    # Sharpe is non-trivial; just sanity-check it's a finite float here.
    assert m["sharpe"] is not None
    assert m["sharpe"] > 0  # net positive series → positive sharpe


def test_metrics_from_trades_all_losses_pf_is_zero_or_none() -> None:
    """If every trade loses, gross_win=0; profit_factor must be 0.0
    (or None — orchestrator's choice). Must NOT raise division-by-zero."""
    from infra.backtest import walk_forward as wf

    trades = [
        {
            "open_date": datetime(2024, 1, 1, tzinfo=timezone.utc),
            "close_date": datetime(2024, 1, 2, tzinfo=timezone.utc),
            "profit_abs": -10.0,
        },
        {
            "open_date": datetime(2024, 1, 3, tzinfo=timezone.utc),
            "close_date": datetime(2024, 1, 4, tzinfo=timezone.utc),
            "profit_abs": -5.0,
        },
    ]
    m = wf.metrics_from_trades(trades=trades, starting_balance=1000.0)
    assert m["total_trades"] == 2
    assert m["profit_factor"] in (0.0, None)
    assert m["win_rate"] == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# Postgres round-trip — uses real DB, transaction-rollback isolated.
# ---------------------------------------------------------------------------
@pytest.fixture
def pg_conn():
    """Open a real psycopg connection. Skips if DB unreachable so CI without
    Postgres still passes the pure-Python tests."""
    try:
        conn = psycopg.connect(
            host=os.environ["POSTGRES_HOST"],
            port=os.environ["POSTGRES_PORT"],
            dbname=os.environ["POSTGRES_DB"],
            user=os.environ["POSTGRES_USER"],
            password=os.environ["POSTGRES_PASSWORD"],
        )
    except (KeyError, psycopg.OperationalError) as exc:
        pytest.skip(f"Postgres unreachable: {exc}")
    try:
        yield conn
    finally:
        conn.close()


@pytest.mark.integration
def test_persist_fold_result_round_trip(pg_conn: psycopg.Connection) -> None:
    """Insert a fold row via the orchestrator's persist function inside an
    explicit transaction, read it back, then ROLLBACK. Verifies schema match
    and JSONB column round-trip without polluting the real table."""
    from infra.backtest import walk_forward as wf

    fold_row = {
        "strategy_version": "test-v0.0-walkforward-roundtrip",
        "fold_index": 99,
        "train_start": datetime(2018, 1, 1, tzinfo=timezone.utc),
        "train_end": datetime(2022, 12, 31, tzinfo=timezone.utc),
        "test_start": datetime(2023, 1, 1, tzinfo=timezone.utc),
        "test_end": datetime(2023, 12, 31, tzinfo=timezone.utc),
        "parameters": {"buy_ema_fast": 21, "buy_ema_slow": 55},
        "metrics": _fold_metrics(),
        "equity_curve": [
            {"ts": "2023-01-01T00:00:00+00:00", "equity": 1000.0},
            {"ts": "2023-12-31T23:59:00+00:00", "equity": 1180.0},
        ],
        "trades": [],
        "gate_passed": True,
        "started_at": datetime(2026, 5, 8, tzinfo=timezone.utc),
        "completed_at": datetime(2026, 5, 8, tzinfo=timezone.utc),
        "notes": "round-trip test",
    }

    try:
        with pg_conn.cursor() as cur:
            inserted_id = wf.persist_fold(cur, fold_row)
            assert isinstance(inserted_id, int)
            cur.execute(
                "SELECT strategy_version, fold_index, parameters, metrics, "
                "equity_curve, gate_passed FROM brain.backtest_runs WHERE id = %s",
                (inserted_id,),
            )
            row = cur.fetchone()
            assert row is not None
            assert row[0] == "test-v0.0-walkforward-roundtrip"
            assert row[1] == 99
            assert row[2] == {"buy_ema_fast": 21, "buy_ema_slow": 55}
            assert row[3]["sharpe"] == pytest.approx(1.8)
            assert isinstance(row[4], list)
            assert row[5] is True
    finally:
        pg_conn.rollback()


# ---------------------------------------------------------------------------
# CLI smoke — --help works without env / freqtrade dependency probing.
# ---------------------------------------------------------------------------
def test_cli_help_runs_clean() -> None:
    """``python -m infra.backtest.walk_forward --help`` exits 0 with usage."""
    proc = subprocess.run(
        [sys.executable, "-m", "infra.backtest.walk_forward", "--help"],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, f"--help failed: stderr={proc.stderr}"
    out = proc.stdout.lower()
    assert "strategy-version" in out
    assert "accept-degraded" in out
    assert "n-folds" in out


def test_cli_emits_json_verdict_on_synthetic_metrics(tmp_path: Path) -> None:
    """Dry-run mode: orchestrator can be asked to evaluate a precomputed
    fold-metrics file without invoking Freqtrade. Used by spec to test the
    gate path end-to-end without running 30+ hours of compute."""
    metrics_file = tmp_path / "synthetic_folds.json"
    folds_payload = {
        "strategy_version": "synthetic-pass",
        "folds": [
            {
                "fold_index": i,
                "train_start": "2018-01-01T00:00:00+00:00",
                "train_end": "2022-12-31T00:00:00+00:00",
                "test_start": "2023-01-01T00:00:00+00:00",
                "test_end": "2023-12-31T00:00:00+00:00",
                "metrics": _fold_metrics(),
            }
            for i in range(1, 6)
        ],
    }
    metrics_file.write_text(json.dumps(folds_payload), encoding="utf-8")

    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "infra.backtest.walk_forward",
            "--evaluate-only",
            str(metrics_file),
        ],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, f"PASS run exited {proc.returncode}: {proc.stderr}"
    parsed = json.loads(proc.stdout)
    assert parsed["verdict"] == "PASS"
    assert parsed["criteria_failed"] == []


def test_cli_exit_code_2_on_fail(tmp_path: Path) -> None:
    """Synthetic FAIL → exit code 2."""
    metrics_file = tmp_path / "synthetic_fail.json"
    folds_payload = {
        "strategy_version": "synthetic-fail",
        "folds": [
            {
                "fold_index": i,
                "train_start": "2018-01-01T00:00:00+00:00",
                "train_end": "2022-12-31T00:00:00+00:00",
                "test_start": "2023-01-01T00:00:00+00:00",
                "test_end": "2023-12-31T00:00:00+00:00",
                "metrics": _fold_metrics(sharpe=0.8, total_trades=40),
            }
            for i in range(1, 6)
        ],
    }
    metrics_file.write_text(json.dumps(folds_payload), encoding="utf-8")

    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "infra.backtest.walk_forward",
            "--evaluate-only",
            str(metrics_file),
        ],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 2, (
        f"FAIL run should exit 2, got {proc.returncode}: stdout={proc.stdout}"
    )
    parsed = json.loads(proc.stdout)
    assert parsed["verdict"] == "FAIL"
    assert len(parsed["criteria_failed"]) >= 1
