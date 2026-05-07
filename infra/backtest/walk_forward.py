"""Phase 9 — Walk-forward backtest orchestrator + Iron Law 2 gate.

The script drives the production validation gate that gates Phase 10
(paper trade) and ultimately Phase 12 (live capital). It runs the
``ClaudeOversightStrategy`` against N expanding-window OOS folds, computes
the Iron Law 2 metrics per fold, persists each fold to
``brain.backtest_runs``, and emits a JSON verdict to stdout.

Per the plan §9 step 5 (verbatim):

    Sharpe   > 1.5  in all 5 OOS folds
    MaxDD    < 25%  in all 5 folds
    PF       > 1.4  in all 5 folds
    Trades  >= 100  per fold

Exit codes:

    0 — verdict PASS  (all four criteria green in every fold)
    2 — verdict FAIL  (one or more criteria red in any fold)
    1 — orchestrator-level error (bad args, freqtrade missing, etc.)

Three usage modes:

  1. Full run (intended; multi-hour compute)::

         python -m infra.backtest.walk_forward \\
             --strategy-version v1.0 \\
             --train-floor 2023-01-01 \\
             --end 2026-05-07 \\
             --n-folds 5 [--accept-degraded N] \\
             --pair BTC/USDT --timeframe 15m

     The orchestrator computes folds, invokes
     ``freqtrade backtesting`` once per fold, parses the JSON output,
     persists rows to ``brain.backtest_runs``, and prints the verdict.

  2. Evaluate-only — pure gate evaluation against precomputed metrics::

         python -m infra.backtest.walk_forward --evaluate-only metrics.json

     The JSON file must have shape ``{"strategy_version": "...",
     "folds": [{"fold_index": int, "metrics": {...}}, ...]}``. No DB
     writes, no Freqtrade invocation. Used by tests and operators
     replaying historical fold metrics through the gate.

  3. Plan-only — dry print the fold plan (no compute, no DB)::

         python -m infra.backtest.walk_forward --plan-only \\
             --train-floor 2023-01-01 --end 2026-05-07 --n-folds 5 \\
             --accept-degraded 3

Operator must run with the project venv so ``freqtrade`` is on the path
and ``POSTGRES_*`` env vars are set (the loader in
``tests/conftest.py`` reads ``.env`` automatically; for production runs
source ``.env`` first).

Iron Law 3: every Postgres connection uses ``os.environ[...]`` directly
(no silent fallback). Iron Law 2: the gate cannot be bypassed —
``--evaluate-only`` is purely a replay of precomputed metrics and still
returns FAIL on red criteria.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import shutil
import statistics
import subprocess
import sys
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from infra.scripts.walkforward_folds import generate_folds as _generate_folds_raw


# ---------------------------------------------------------------------------
# Iron Law 2 gate thresholds — published as module constants for audit.
#
# Source: docs/plans/2026-05-06-ai-trading-247.md Phase 9 step 5.
# Mirrored in CLAUDE.md "Iron Law 2". Drift would silently soften the
# gate, so they live here once and only once.
# ---------------------------------------------------------------------------
MIN_SHARPE: float = 1.5
MAX_DRAWDOWN: float = 0.25  # absolute fraction (25%)
MIN_PROFIT_FACTOR: float = 1.4
MIN_TRADES_PER_FOLD: int = 100

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


# ---------------------------------------------------------------------------
# Fold computation — wraps the Phase 0.5 generator with degradation guard.
# ---------------------------------------------------------------------------
class DegradedFoldPlan(RuntimeError):
    """Raised when the requested fold count cannot be computed from the
    available data range AND the operator has not explicitly opted in via
    ``--accept-degraded N``.

    Iron Law 3: silently degrading from 5 folds to 3 would weaken the
    Iron Law 2 gate — the operator must acknowledge the reduced
    statistical power explicitly.
    """


@dataclass(frozen=True)
class FoldSpec:
    """Lightweight projection of ``infra.scripts.walkforward_folds.Fold``
    so callers don't depend on the underlying dataclass shape (and so the
    orchestrator stays decoupled from the fold-generator's internals)."""

    fold_index: int
    train_start: date
    train_end: date
    test_start: date
    test_end: date


def compute_folds(
    *,
    train_floor: date,
    end: date,
    n_folds: int,
    accept_degraded: bool,
    mode: str = "anchored",
    post_etf_required: bool = True,
) -> list[FoldSpec]:
    """Compute N OOS folds, raising :class:`DegradedFoldPlan` if the data
    range cannot host that many and the operator has not opted in.

    Delegates the actual math to
    :func:`infra.scripts.walkforward_folds.generate_folds` so the
    regime-aware contract (post-ETF straddle, 180-day minimum test
    window) is preserved. This wrapper adds:

      * Hard fail when the underlying generator raises (re-wrapped as
        :class:`DegradedFoldPlan` so the operator sees the actionable
        ``--accept-degraded`` hint).
      * Refuses to silently return ``[]`` — zero folds is always a
        :class:`ValueError`.

    Iron Law 2: ``post_etf_required`` defaults to ``True``. The Spot BTC
    ETF approval (2024-01-11) is a documented Chow Test break (p=0.004)
    per ``references/crypto/regime-taxonomy.md`` Topic 7; a 5-fold
    backtest that ignores it has a known OOS blind spot.
    """
    if n_folds < 1:
        raise ValueError(f"n_folds must be >= 1, got {n_folds}")
    if end <= train_floor:
        raise ValueError(
            f"end {end} must be after train_floor {train_floor}"
        )

    try:
        raw = _generate_folds_raw(
            start=train_floor,
            end=end,
            n_folds=n_folds,
            mode=mode,
            post_etf_required=post_etf_required,
        )
    except ValueError as exc:
        # Generator raises ValueError for "data too short for N folds"
        # AND for "ETF date cannot be straddled". Both are operator-actionable
        # and both should surface as DegradedFoldPlan so the operator gets
        # the --accept-degraded hint.
        if accept_degraded:
            # Operator opted in but the requested n_folds STILL doesn't
            # fit. We don't auto-pick a smaller N — that would also be a
            # silent degradation. Re-raise as DegradedFoldPlan with the
            # original message, plus suggest a smaller --n-folds.
            raise DegradedFoldPlan(
                f"{exc}. Re-run with a smaller --n-folds "
                f"(currently {n_folds}) and the same --accept-degraded flag."
            ) from exc
        raise DegradedFoldPlan(
            f"{exc}. Pass --accept-degraded N (with N matching a fold "
            f"count that fits the data) to acknowledge the reduced "
            f"statistical power."
        ) from exc

    folds: list[FoldSpec] = [
        FoldSpec(
            fold_index=f.fold_index,
            train_start=f.train_start,
            train_end=f.train_end,
            test_start=f.test_start,
            test_end=f.test_end,
        )
        for f in raw
    ]
    if not folds:
        # Defense in depth — generate_folds either raises or returns >=1
        # fold, but if some upstream change ever produces an empty list
        # we crash loud rather than silently passing an empty plan
        # downstream (Iron Law 3).
        raise ValueError(
            f"compute_folds produced 0 folds for "
            f"train_floor={train_floor} end={end} n_folds={n_folds} — "
            f"refusing to advance with empty plan"
        )
    return folds


# ---------------------------------------------------------------------------
# Metrics from per-trade list — pure function, deterministic.
# ---------------------------------------------------------------------------
def metrics_from_trades(
    *,
    trades: list[dict[str, Any]],
    starting_balance: float,
) -> dict[str, Any]:
    """Compute Iron Law 2 metrics from a list of closed trades.

    Each trade dict must have at least ``profit_abs`` (signed PnL in the
    starting-balance unit). ``open_date`` / ``close_date`` are accepted
    but not required for these metrics.

    Returns ``{sharpe, sortino, max_dd, profit_factor, total_trades,
    win_rate, expectancy}``. Empty trade list returns ``None`` for the
    ratio metrics — never silently zero (Iron Law 3 / no fake green).
    """
    n = len(trades)
    if n == 0:
        return {
            "total_trades": 0,
            "sharpe": None,
            "sortino": None,
            "max_dd": None,
            "profit_factor": None,
            "win_rate": None,
            "expectancy": None,
        }

    pnls = [float(t["profit_abs"]) for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    gross_win = sum(wins)
    gross_loss = -sum(losses)  # positive number
    if gross_loss > 0:
        profit_factor = float(gross_win / gross_loss)
    else:
        # No losing trades → infinite PF mathematically. Treating as None
        # would mark the fold as "undefined" against the gate; treating
        # as a very large number would silently green-light. We choose
        # 0.0 ONLY when gross_win is also 0; otherwise return None and
        # let the gate fail the fold for "PF undefined" which surfaces
        # the data quality issue (every backtest with >=100 trades
        # should have at least one loser).
        profit_factor = 0.0 if gross_win == 0 else None

    win_rate = len(wins) / n
    expectancy = sum(pnls) / n

    # Equity curve + max drawdown
    equity = [starting_balance]
    for pnl in pnls:
        equity.append(equity[-1] + pnl)
    peak = equity[0]
    max_dd = 0.0
    for e in equity:
        if e > peak:
            peak = e
        dd = (peak - e) / peak if peak > 0 else 0.0
        if dd > max_dd:
            max_dd = dd

    # Sharpe + Sortino — daily-equivalent annualisation is unstable for
    # small N; we compute the per-trade Sharpe (mean / stdev of trade
    # PnLs) which is the convention Freqtrade's
    # SharpeHyperOptLossDaily uses internally for hyperopt, but here we
    # do not annualise because trade frequency varies fold-to-fold. The
    # Iron Law 2 threshold (>1.5) is calibrated against this convention.
    if n < 2:
        sharpe = None
        sortino = None
    else:
        mean = expectancy
        stdev = statistics.stdev(pnls)
        if stdev > 0:
            sharpe = mean / stdev
        else:
            # Constant pnl series — meaningless sharpe.
            sharpe = None
        downside = [p for p in pnls if p < 0]
        if len(downside) >= 2:
            d_stdev = statistics.stdev(downside)
            sortino = mean / d_stdev if d_stdev > 0 else None
        elif len(downside) == 1:
            # Single downside; sortino is degenerate. Use abs(downside[0])
            # as proxy stdev so we report a finite value rather than None.
            sortino = mean / abs(downside[0]) if downside[0] != 0 else None
        else:
            # Zero downside — no losers. Same reasoning as profit_factor:
            # mark as None so the gate fails-loud on the data shape.
            sortino = None

    return {
        "total_trades": int(n),
        "sharpe": float(sharpe) if sharpe is not None else None,
        "sortino": float(sortino) if sortino is not None else None,
        "max_dd": float(max_dd),
        "profit_factor": (
            float(profit_factor) if profit_factor is not None else None
        ),
        "win_rate": float(win_rate),
        "expectancy": float(expectancy),
    }


# ---------------------------------------------------------------------------
# Iron Law 2 gate — pure function over per-fold metrics.
# ---------------------------------------------------------------------------
def evaluate_gate(folds: list[dict[str, Any]]) -> dict[str, Any]:
    """Apply Phase 9 step 5 criteria. Each input dict must have
    ``fold_index`` and ``metrics`` (the dict returned by
    :func:`metrics_from_trades`).

    Returns ``{"verdict": "PASS"|"FAIL", "criteria_failed": [str, ...],
    "fold_summary": [...]}`` where ``criteria_failed`` is a flat list
    of human-readable failure descriptions (one per (fold, criterion)
    pair that failed).

    Iron Law 3: empty input is :class:`ValueError`, never silent PASS.
    """
    if not folds:
        raise ValueError(
            "evaluate_gate called with zero folds — refusing to emit "
            "PASS on empty input (Iron Law 3 / Iron Law 2 gate must "
            "see at least one fold)"
        )

    failed: list[str] = []
    summary: list[dict[str, Any]] = []
    for f in folds:
        idx = int(f["fold_index"])
        m = f["metrics"]
        sharpe = m.get("sharpe")
        max_dd = m.get("max_dd")
        pf = m.get("profit_factor")
        n_trades = m.get("total_trades")

        fold_failures: list[str] = []
        if sharpe is None or sharpe <= MIN_SHARPE:
            fold_failures.append(
                f"fold {idx}: sharpe={sharpe} <= {MIN_SHARPE} "
                f"(Iron Law 2 requires > {MIN_SHARPE})"
            )
        if max_dd is None or max_dd >= MAX_DRAWDOWN:
            fold_failures.append(
                f"fold {idx}: max_drawdown={max_dd} >= {MAX_DRAWDOWN} "
                f"(Iron Law 2 requires < {MAX_DRAWDOWN})"
            )
        if pf is None or pf <= MIN_PROFIT_FACTOR:
            fold_failures.append(
                f"fold {idx}: profit_factor={pf} <= {MIN_PROFIT_FACTOR} "
                f"(Iron Law 2 requires > {MIN_PROFIT_FACTOR})"
            )
        if n_trades is None or n_trades < MIN_TRADES_PER_FOLD:
            fold_failures.append(
                f"fold {idx}: total_trades={n_trades} < "
                f"{MIN_TRADES_PER_FOLD} (Iron Law 2 requires >= "
                f"{MIN_TRADES_PER_FOLD} per fold for statistical "
                f"significance)"
            )

        failed.extend(fold_failures)
        summary.append(
            {
                "fold_index": idx,
                "sharpe": sharpe,
                "max_dd": max_dd,
                "profit_factor": pf,
                "total_trades": n_trades,
                "fold_passed": not fold_failures,
            }
        )

    verdict = "PASS" if not failed else "FAIL"
    return {
        "verdict": verdict,
        "criteria_failed": failed,
        "fold_summary": summary,
    }


# ---------------------------------------------------------------------------
# Postgres connection + persistence.
# ---------------------------------------------------------------------------
def _connect() -> psycopg.Connection:
    """Open a psycopg connection from POSTGRES_* env vars.

    Iron Law 3: ``os.environ[...]`` raises :class:`KeyError` on missing
    env (no silent fallback).
    """
    return psycopg.connect(
        host=os.environ["POSTGRES_HOST"],
        port=os.environ["POSTGRES_PORT"],
        dbname=os.environ["POSTGRES_DB"],
        user=os.environ["POSTGRES_USER"],
        password=os.environ["POSTGRES_PASSWORD"],
    )


_INSERT_SQL = """
INSERT INTO brain.backtest_runs (
    started_at, completed_at, strategy_version, fold_index,
    train_start, train_end, test_start, test_end,
    parameters, metrics, equity_curve, trades, gate_passed, notes
)
VALUES (
    %(started_at)s, %(completed_at)s, %(strategy_version)s, %(fold_index)s,
    %(train_start)s, %(train_end)s, %(test_start)s, %(test_end)s,
    %(parameters)s, %(metrics)s, %(equity_curve)s, %(trades)s,
    %(gate_passed)s, %(notes)s
)
RETURNING id
"""


def persist_fold(
    cur: psycopg.Cursor, row: dict[str, Any]
) -> int:
    """Insert a single fold result and return the new row id.

    Caller controls the transaction boundary (commit/rollback). The
    orchestrator commits per-fold so a multi-hour run that crashes mid-
    way doesn't lose the completed folds. The persistence test rolls
    back so it never pollutes the real table.
    """
    payload = {
        "started_at": row["started_at"],
        "completed_at": row.get("completed_at"),
        "strategy_version": row["strategy_version"],
        "fold_index": int(row["fold_index"]),
        "train_start": row["train_start"],
        "train_end": row["train_end"],
        "test_start": row["test_start"],
        "test_end": row["test_end"],
        "parameters": Jsonb(row["parameters"]),
        "metrics": Jsonb(row["metrics"]),
        "equity_curve": (
            Jsonb(row["equity_curve"])
            if row.get("equity_curve") is not None
            else None
        ),
        "trades": (
            Jsonb(row["trades"]) if row.get("trades") is not None else None
        ),
        "gate_passed": bool(row.get("gate_passed", False)),
        "notes": row.get("notes"),
    }
    cur.execute(_INSERT_SQL, payload)
    fetched = cur.fetchone()
    if fetched is None:
        raise RuntimeError(
            "persist_fold: INSERT ... RETURNING produced no row"
        )
    return int(fetched[0])


# ---------------------------------------------------------------------------
# Freqtrade invocation per fold.
# ---------------------------------------------------------------------------
def _freqtrade_binary() -> str:
    """Locate the ``freqtrade`` executable. Hard-fail if missing
    (Iron Law 3)."""
    binary = shutil.which("freqtrade")
    if binary is None:
        raise RuntimeError(
            "freqtrade binary not found on PATH. Activate the project "
            "venv (`pip install -e freqtrade-fork`) before running the "
            "walk-forward orchestrator."
        )
    return binary


def _run_freqtrade_backtest(
    *,
    config_path: Path,
    strategy: str,
    timerange: str,
    pair: str,
    timeframe: str,
    export_dir: Path,
) -> Path:
    """Invoke ``freqtrade backtesting`` for a single fold timerange and
    return the path to the freqtrade JSON result file.

    Raises :class:`subprocess.CalledProcessError` on non-zero exit so
    the orchestrator stops the loop loudly rather than persisting a
    fake-green row.
    """
    export_dir.mkdir(parents=True, exist_ok=True)
    export_filename = export_dir / f"backtest_{timerange}.json"
    cmd = [
        _freqtrade_binary(),
        "backtesting",
        "--config", str(config_path),
        "--strategy", strategy,
        "--timerange", timerange,
        "--pairs", pair,
        "--timeframe", timeframe,
        "--export", "trades",
        "--export-filename", str(export_filename),
    ]
    print(f"[walk_forward]   $ {' '.join(cmd)}", file=sys.stderr)
    subprocess.run(cmd, check=True)
    if not export_filename.is_file():
        raise RuntimeError(
            f"freqtrade backtesting completed (exit 0) but export file "
            f"{export_filename} was not produced"
        )
    return export_filename


def _parse_freqtrade_result(
    result_path: Path, *, strategy: str
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    """Read Freqtrade's backtest result JSON and return (trades, raw_strategy_block).

    Freqtrade's JSON layout (verified against backtest_results in the
    fork): ``{"strategy": {"<StrategyName>": {"trades": [...],
    "results_per_pair": [...], ...}}}``. We extract the trade list and
    pass the raw strategy dict back so the caller can stash it as the
    ``trades``/``equity_curve`` JSONB if desired.
    """
    raw = json.loads(result_path.read_text(encoding="utf-8"))
    strat_block = raw.get("strategy", {}).get(strategy)
    if strat_block is None:
        raise RuntimeError(
            f"freqtrade result {result_path} has no 'strategy.{strategy}' "
            f"block; available keys: {list(raw.get('strategy', {}).keys())}"
        )
    trades_raw = strat_block.get("trades", [])
    # Normalise to the shape metrics_from_trades expects.
    trades: list[dict[str, Any]] = []
    for t in trades_raw:
        if "profit_abs" not in t:
            raise RuntimeError(
                f"freqtrade trade row missing 'profit_abs': {t}"
            )
        trades.append(t)
    return trades, strat_block


# ---------------------------------------------------------------------------
# Full-run orchestration.
# ---------------------------------------------------------------------------
def _full_run(args: argparse.Namespace) -> int:
    """Execute steps 1-2-3 of plan §9: compute folds, run freqtrade per
    fold, persist, then evaluate gate."""
    train_floor = datetime.fromisoformat(args.train_floor).date()
    end = datetime.fromisoformat(args.end).date()

    # Fold computation
    try:
        folds = compute_folds(
            train_floor=train_floor,
            end=end,
            n_folds=args.n_folds,
            accept_degraded=args.accept_degraded is not None,
            mode=args.mode,
            post_etf_required=args.post_etf_required,
        )
    except DegradedFoldPlan as exc:
        print(f"[walk_forward] FOLD PLAN ERROR: {exc}", file=sys.stderr)
        return 1

    # If --accept-degraded N was given, enforce N matches what we got.
    if args.accept_degraded is not None and len(folds) != args.accept_degraded:
        print(
            f"[walk_forward] FOLD COUNT MISMATCH: --accept-degraded "
            f"{args.accept_degraded} but compute_folds returned "
            f"{len(folds)} folds. Aborting (Iron Law 3 — operator "
            f"must explicitly acknowledge the actual fold count).",
            file=sys.stderr,
        )
        return 1

    print(
        f"[walk_forward] strategy_version={args.strategy_version} "
        f"folds={len(folds)} pair={args.pair} tf={args.timeframe}",
        file=sys.stderr,
    )
    if len(folds) < 5:
        print(
            f"[walk_forward] WARNING: only {len(folds)} folds (data range "
            f"{train_floor}..{end} too short for canonical 5). The Iron "
            f"Law 2 gate will still apply to all folds, but statistical "
            f"power is reduced. Operator opted in via --accept-degraded.",
            file=sys.stderr,
        )

    config_path = (
        REPO_ROOT / "crypto-bot" / "freqtrade-config" / "config.json"
    )
    if not config_path.is_file():
        print(
            f"[walk_forward] config not found: {config_path}",
            file=sys.stderr,
        )
        return 1

    export_dir = REPO_ROOT / args.export_dir
    fold_results: list[dict[str, Any]] = []

    with _connect() as conn:
        for fold in folds:
            timerange = (
                f"{fold.test_start.strftime('%Y%m%d')}-"
                f"{fold.test_end.strftime('%Y%m%d')}"
            )
            started_at = datetime.now(tz=timezone.utc)
            print(
                f"[walk_forward] fold {fold.fold_index}/{len(folds)}: "
                f"train {fold.train_start}..{fold.train_end}, test "
                f"{fold.test_start}..{fold.test_end}",
                file=sys.stderr,
            )
            try:
                result_path = _run_freqtrade_backtest(
                    config_path=config_path,
                    strategy=args.strategy,
                    timerange=timerange,
                    pair=args.pair,
                    timeframe=args.timeframe,
                    export_dir=export_dir,
                )
            except (subprocess.CalledProcessError, RuntimeError) as exc:
                print(
                    f"[walk_forward] fold {fold.fold_index} FAILED: {exc}",
                    file=sys.stderr,
                )
                return 1
            trades, strat_block = _parse_freqtrade_result(
                result_path, strategy=args.strategy
            )
            metrics = metrics_from_trades(
                trades=trades, starting_balance=args.starting_balance
            )
            completed_at = datetime.now(tz=timezone.utc)

            row = {
                "started_at": started_at,
                "completed_at": completed_at,
                "strategy_version": args.strategy_version,
                "fold_index": fold.fold_index,
                "train_start": datetime.combine(
                    fold.train_start, datetime.min.time(), tzinfo=timezone.utc
                ),
                "train_end": datetime.combine(
                    fold.train_end, datetime.min.time(), tzinfo=timezone.utc
                ),
                "test_start": datetime.combine(
                    fold.test_start, datetime.min.time(), tzinfo=timezone.utc
                ),
                "test_end": datetime.combine(
                    fold.test_end, datetime.min.time(), tzinfo=timezone.utc
                ),
                "parameters": (
                    strat_block.get("run_id_metadata", {})
                    if strat_block is not None
                    else {}
                ),
                "metrics": metrics,
                "equity_curve": None,  # Freqtrade exports per-trade not per-bar; UI computes from trades
                "trades": trades,
                "gate_passed": False,  # set after evaluate_gate below
                "notes": (
                    f"freqtrade result: {result_path.name}; "
                    f"timerange={timerange}"
                ),
            }
            with conn.cursor() as cur:
                row_id = persist_fold(cur, row)
            conn.commit()
            print(
                f"[walk_forward]   persisted brain.backtest_runs.id={row_id} "
                f"trades={metrics['total_trades']} sharpe={metrics['sharpe']} "
                f"max_dd={metrics['max_dd']} pf={metrics['profit_factor']}",
                file=sys.stderr,
            )

            fold_results.append(
                {
                    "fold_index": fold.fold_index,
                    "metrics": metrics,
                    "_row_id": row_id,
                    "_timerange": timerange,
                }
            )

        # Gate evaluation
        gate = evaluate_gate(fold_results)

        # Update gate_passed flag per row to reflect the per-fold result
        # (so the UI / brain.backtest_runs query can filter on it).
        with conn.cursor() as cur:
            for fr in fold_results:
                idx = fr["fold_index"]
                summary = next(
                    s for s in gate["fold_summary"] if s["fold_index"] == idx
                )
                cur.execute(
                    "UPDATE brain.backtest_runs SET gate_passed = %s "
                    "WHERE id = %s",
                    (bool(summary["fold_passed"]), fr["_row_id"]),
                )
            conn.commit()

    print(json.dumps(gate, default=str, indent=2))
    return 0 if gate["verdict"] == "PASS" else 2


# ---------------------------------------------------------------------------
# Evaluate-only mode — apply gate to a precomputed metrics file.
# ---------------------------------------------------------------------------
def _evaluate_only(args: argparse.Namespace) -> int:
    path = Path(args.evaluate_only)
    if not path.is_file():
        print(f"[walk_forward] file not found: {path}", file=sys.stderr)
        return 1
    payload = json.loads(path.read_text(encoding="utf-8"))
    folds = payload.get("folds")
    if not isinstance(folds, list) or not folds:
        print(
            f"[walk_forward] {path} has no non-empty 'folds' array",
            file=sys.stderr,
        )
        return 1
    try:
        gate = evaluate_gate(folds)
    except ValueError as exc:
        print(f"[walk_forward] gate evaluation error: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(gate, default=str, indent=2))
    return 0 if gate["verdict"] == "PASS" else 2


# ---------------------------------------------------------------------------
# Plan-only mode — print fold plan, no compute, no DB.
# ---------------------------------------------------------------------------
def _plan_only(args: argparse.Namespace) -> int:
    train_floor = datetime.fromisoformat(args.train_floor).date()
    end = datetime.fromisoformat(args.end).date()
    try:
        folds = compute_folds(
            train_floor=train_floor,
            end=end,
            n_folds=args.n_folds,
            accept_degraded=args.accept_degraded is not None,
            mode=args.mode,
            post_etf_required=args.post_etf_required,
        )
    except DegradedFoldPlan as exc:
        print(f"[walk_forward] FOLD PLAN ERROR: {exc}", file=sys.stderr)
        return 1
    plan = {
        "input": {
            "train_floor": train_floor.isoformat(),
            "end": end.isoformat(),
            "n_folds": args.n_folds,
            "mode": args.mode,
            "post_etf_required": args.post_etf_required,
            "accept_degraded": args.accept_degraded,
        },
        "fold_count": len(folds),
        "folds": [
            {
                "fold_index": f.fold_index,
                "train_start": f.train_start.isoformat(),
                "train_end": f.train_end.isoformat(),
                "test_start": f.test_start.isoformat(),
                "test_end": f.test_end.isoformat(),
            }
            for f in folds
        ],
    }
    print(json.dumps(plan, indent=2))
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m infra.backtest.walk_forward",
        description=(
            "Phase 9 walk-forward orchestrator. Runs ClaudeOversightStrategy "
            "across N OOS folds, persists results to brain.backtest_runs, "
            "and emits a Iron Law 2 gate verdict (exit 0 PASS, exit 2 FAIL)."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        "--strategy-version",
        default=None,
        help=(
            "Tag persisted to brain.backtest_runs.strategy_version "
            "(e.g. 'v1.0' or 'v1.2-iter-1'). Required for full-run mode."
        ),
    )
    p.add_argument(
        "--strategy",
        default="ClaudeOversightStrategy",
        help="Freqtrade strategy class name. Default ClaudeOversightStrategy.",
    )
    p.add_argument("--pair", default="BTC/USDT")
    p.add_argument("--timeframe", default="15m")
    p.add_argument(
        "--train-floor",
        default=None,
        help=(
            "ISO date (YYYY-MM-DD) for the earliest train_start. Plan §9 "
            "specifies '2018-01-01'; for the local Postgres which only "
            "has data from 2023-01-01, use that. Required for full-run "
            "and plan-only modes."
        ),
    )
    p.add_argument(
        "--end",
        default=None,
        help=(
            "ISO date (YYYY-MM-DD) for the latest test_end. Required for "
            "full-run and plan-only modes."
        ),
    )
    p.add_argument(
        "--n-folds",
        type=int,
        default=5,
        help="Number of OOS folds. Default 5 per Iron Law 2.",
    )
    p.add_argument(
        "--mode",
        choices=("anchored", "rolling"),
        default="anchored",
        help=(
            "anchored: train_start pinned to --train-floor (expanding window). "
            "rolling: fixed-length sliding train. Default anchored per plan §6."
        ),
    )
    p.add_argument(
        "--post-etf-required",
        action="store_true",
        default=True,
        help=(
            "Assert at least one fold's test window straddles 2024-01-11 "
            "(Spot BTC ETF approval). Default True per "
            "references/crypto/regime-taxonomy.md Topic 7."
        ),
    )
    p.add_argument(
        "--no-post-etf-required",
        dest="post_etf_required",
        action="store_false",
        help="Disable post-ETF straddle requirement (operator override).",
    )
    p.add_argument(
        "--accept-degraded",
        type=int,
        default=None,
        metavar="N",
        help=(
            "Acknowledge that the data range cannot host the requested "
            "fold count and accept N folds instead. Without this flag, a "
            "degraded fold plan is a hard error (Iron Law 3). Pass the "
            "actual N expected; orchestrator hard-fails if compute_folds "
            "returns a different count."
        ),
    )
    p.add_argument(
        "--starting-balance",
        type=float,
        default=1000.0,
        help="Starting balance for fold-level metrics. Default 1000.",
    )
    p.add_argument(
        "--export-dir",
        default="user_data/backtest_results/walkforward",
        help=(
            "Directory (relative to repo root) for freqtrade JSON exports. "
            "Default user_data/backtest_results/walkforward."
        ),
    )
    p.add_argument(
        "--evaluate-only",
        default=None,
        metavar="METRICS_FILE",
        help=(
            "Replay mode: read precomputed fold metrics from this JSON "
            "file and apply the gate. No Freqtrade invocation, no DB write. "
            "File shape: {strategy_version, folds: [{fold_index, metrics}]}."
        ),
    )
    p.add_argument(
        "--plan-only",
        action="store_true",
        default=False,
        help=(
            "Print the fold plan (train/test windows) as JSON and exit. "
            "No Freqtrade invocation, no DB write."
        ),
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    if args.evaluate_only is not None:
        return _evaluate_only(args)

    if args.plan_only:
        if not args.train_floor or not args.end:
            print(
                "[walk_forward] --plan-only requires --train-floor and --end",
                file=sys.stderr,
            )
            return 1
        return _plan_only(args)

    # Full run — require strategy-version + dates.
    missing = [
        flag
        for flag, val in [
            ("--strategy-version", args.strategy_version),
            ("--train-floor", args.train_floor),
            ("--end", args.end),
        ]
        if not val
    ]
    if missing:
        print(
            f"[walk_forward] full run requires: {', '.join(missing)} "
            f"(or use --evaluate-only / --plan-only)",
            file=sys.stderr,
        )
        return 1
    return _full_run(args)


if __name__ == "__main__":
    sys.exit(main())
