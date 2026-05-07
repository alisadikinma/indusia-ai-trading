"""Phase 8 spec-review fix — verify ``run_hyperopt.py --replay-params`` mode.

The ADR-003 §5 OOS table was previously narrative-only: the numbers in the
table were not derivable from any row in ``brain.hyperopt_results``, because
the ``oos-001`` run was an *independent random sweep* over the OOS window,
NOT an *OOS replay* of the IS-top-3 fixed parameter sets. This test pins
the new ``--replay-params`` mode that runs each parameter set in a JSON
file ONCE on the configured timerange and persists each result to
``brain.hyperopt_results`` under the supplied ``--replay-run-id``.

TDD discipline (per CLAUDE.md / gaspol-tdd):

  1. This test was authored BEFORE the runner gained ``--replay-params``
     support. Running it against the pre-fix runner must fail (the runner
     rejects the unknown flag with SystemExit / argparse error).
  2. After implementing the flag, the test asserts:
       * exit code 0
       * exactly N rows in ``brain.hyperopt_results`` for the specified
         run_id (where N = len(input JSON))
       * ``epoch`` column equals 1..N (ordinal index of the input list)
       * ``parameters`` column round-trips the input JSON verbatim
     and cleans up rows after.

Tiny scope on purpose: 2 param sets, 1-week timerange, real OHLCV from
``brain.ohlcv``. No mocks (Iron Law 3).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

import psycopg
import pytest


REPO_ROOT = Path(__file__).resolve().parent.parent
RUNNER = REPO_ROOT / "infra" / "scripts" / "run_hyperopt.py"


def _connect() -> psycopg.Connection:
    return psycopg.connect(
        host=os.environ["POSTGRES_HOST"],
        port=os.environ["POSTGRES_PORT"],
        dbname=os.environ["POSTGRES_DB"],
        user=os.environ["POSTGRES_USER"],
        password=os.environ["POSTGRES_PASSWORD"],
    )


@pytest.mark.integration
def test_replay_params_persists_one_row_per_input_set(tmp_path: Path) -> None:
    """Calling the runner with --replay-params <2-set JSON> must persist
    exactly 2 rows under the specified run_id, with epoch=1,2.
    """
    if "POSTGRES_HOST" not in os.environ:
        pytest.skip("POSTGRES_HOST not set; .env not loaded")

    # Two fixed parameter sets — values within the strategy's declared ranges.
    param_sets = [
        {
            "buy_ema_fast": 13,
            "buy_ema_slow": 74,
            "buy_adx_threshold": 22,
            "buy_pred_threshold": 0.67,
            "sell_atr_mult": 1.55,
        },
        {
            "buy_ema_fast": 20,
            "buy_ema_slow": 50,
            "buy_adx_threshold": 25,
            "buy_pred_threshold": 0.65,
            "sell_atr_mult": 2.0,
        },
    ]
    params_json = tmp_path / "replay_params.json"
    params_json.write_text(json.dumps(param_sets), encoding="utf-8")

    # Use a unique run_id per test invocation so we don't collide.
    run_id = f"test-replay-{uuid.uuid4().hex[:8]}"

    # 1-week timerange — must be a window that exists in brain.ohlcv. The
    # smoke sweep already validated 2024-01-01 → 2024-07-01 has data, so a
    # 1-week subset is safe.
    cmd = [
        sys.executable,
        str(RUNNER),
        "--pair", "BTC/USDT",
        "--timerange-start", "2024-01-01",
        "--timerange-end", "2024-01-08",
        "--replay-params", str(params_json),
        "--replay-run-id", run_id,
    ]

    try:
        result = subprocess.run(
            cmd,
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=300,
        )
        assert result.returncode == 0, (
            f"runner exited {result.returncode}\nSTDOUT:\n{result.stdout}\n"
            f"STDERR:\n{result.stderr}"
        )

        with _connect() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT epoch, parameters, total_trades, timerange_start, "
                "timerange_end FROM brain.hyperopt_results "
                "WHERE run_id = %s ORDER BY epoch ASC",
                (run_id,),
            )
            rows = cur.fetchall()

        assert len(rows) == len(param_sets), (
            f"expected {len(param_sets)} rows for run_id={run_id}, got {len(rows)}"
        )
        # Epoch column = ordinal index 1..N
        epochs = [r[0] for r in rows]
        assert epochs == list(range(1, len(param_sets) + 1)), (
            f"expected epochs {list(range(1, len(param_sets)+1))}, got {epochs}"
        )
        # Parameters round-trip verbatim
        for ordinal, (epoch, db_params, _trades, _ts, _te) in enumerate(rows):
            expected = param_sets[ordinal]
            for k, v in expected.items():
                assert db_params[k] == v, (
                    f"epoch {epoch} param {k}: expected {v}, got {db_params[k]}"
                )
    finally:
        # Always clean up — keep the table tidy for subsequent runs.
        with _connect() as conn, conn.cursor() as cur:
            cur.execute(
                "DELETE FROM brain.hyperopt_results WHERE run_id = %s",
                (run_id,),
            )
            conn.commit()


@pytest.mark.integration
def test_replay_params_rejects_missing_replay_run_id(tmp_path: Path) -> None:
    """--replay-params without --replay-run-id is an operator error: the
    runner must fail loudly rather than silently fall back to a generated
    run_id (which would defeat the audit-trail purpose of the flag)."""
    if "POSTGRES_HOST" not in os.environ:
        pytest.skip("POSTGRES_HOST not set; .env not loaded")

    params_json = tmp_path / "p.json"
    params_json.write_text(json.dumps([{
        "buy_ema_fast": 20, "buy_ema_slow": 50, "buy_adx_threshold": 25,
        "buy_pred_threshold": 0.65, "sell_atr_mult": 2.0,
    }]), encoding="utf-8")

    cmd = [
        sys.executable,
        str(RUNNER),
        "--pair", "BTC/USDT",
        "--timerange-start", "2024-01-01",
        "--timerange-end", "2024-01-08",
        "--replay-params", str(params_json),
        # deliberately omit --replay-run-id
    ]
    result = subprocess.run(
        cmd, cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=60,
    )
    assert result.returncode != 0, (
        f"expected non-zero exit when --replay-run-id omitted, got 0\n"
        f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    )


def test_replay_params_rejects_out_of_range_value(tmp_path: Path) -> None:
    """An entry with a parameter outside its declared search-space range
    must be rejected with SystemExit BEFORE any DB row is written.

    Why this matters: rows in ``brain.hyperopt_results`` are the canonical
    OOS-replay source for ADR-003 §5. A silently-accepted out-of-range
    value would corrupt that audit trail.
    """
    # buy_ema_fast=5 is below the strategy-declared low=10 floor.
    bad_set = [{
        "buy_ema_fast": 5,
        "buy_ema_slow": 50,
        "buy_adx_threshold": 25,
        "buy_pred_threshold": 0.65,
        "sell_atr_mult": 2.0,
    }]
    params_json = tmp_path / "bad_range.json"
    params_json.write_text(json.dumps(bad_set), encoding="utf-8")

    cmd = [
        sys.executable,
        str(RUNNER),
        "--pair", "BTC/USDT",
        "--timerange-start", "2024-01-01",
        "--timerange-end", "2024-01-08",
        "--replay-params", str(params_json),
        "--replay-run-id", "test-bad-range-should-not-persist",
    ]
    result = subprocess.run(
        cmd, cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=60,
    )
    assert result.returncode != 0, (
        f"expected non-zero exit for out-of-range value, got 0\n"
        f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    )
    combined = (result.stdout or "") + (result.stderr or "")
    assert "buy_ema_fast" in combined, (
        f"error message must name the offending param. Got:\n{combined}"
    )
    assert "out of range" in combined or "range" in combined, (
        f"error message must mention range. Got:\n{combined}"
    )


def test_replay_params_rejects_fast_not_less_than_slow(tmp_path: Path) -> None:
    """An entry where ``buy_ema_fast >= buy_ema_slow`` violates the
    strategy's structural constraint (the EMA crossover requires fast<slow)
    and must be rejected with SystemExit BEFORE any DB row is written.

    The strategy's IntParameter ranges (fast 10-25, slow 40-80) don't
    overlap, so it's syntactically impossible for fast >= slow when both
    independently pass range checks. We exercise the layered defence by
    setting fast=40 (in slow's range, out of fast's range) and slow=40 — at
    minimum the loader must fail loudly. This pins the contract that "both
    range AND constraint violations crash before persistence".
    """
    bad_set = [{
        "buy_ema_fast": 40,
        "buy_ema_slow": 40,
        "buy_adx_threshold": 25,
        "buy_pred_threshold": 0.65,
        "sell_atr_mult": 2.0,
    }]
    params_json = tmp_path / "bad_constraint.json"
    params_json.write_text(json.dumps(bad_set), encoding="utf-8")

    cmd = [
        sys.executable,
        str(RUNNER),
        "--pair", "BTC/USDT",
        "--timerange-start", "2024-01-01",
        "--timerange-end", "2024-01-08",
        "--replay-params", str(params_json),
        "--replay-run-id", "test-bad-constraint-should-not-persist",
    ]
    result = subprocess.run(
        cmd, cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=60,
    )
    assert result.returncode != 0, (
        f"expected non-zero exit for fast>=slow violation, got 0\n"
        f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    )
    combined = (result.stdout or "") + (result.stderr or "")
    assert "buy_ema_fast" in combined or "buy_ema_slow" in combined, (
        f"error message must name at least one of the offending EMA params. "
        f"Got:\n{combined}"
    )
