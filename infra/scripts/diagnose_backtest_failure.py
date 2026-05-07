"""Phase 9.5.A — automated diagnostic suite for failed walk-forward backtests.

Triggered by the operator when Phase 9 fails (any of the 4 gate criteria —
Sharpe>1.5, MaxDD<25%, PF>1.4, trades>=100 — does not hold across all 5 OOS
folds). Reads a row from ``brain.backtest_runs`` and produces a structured
JSON diagnostic report classifying the failure mode into one of:

  * ``overfit``           — large train_sharpe vs test_sharpe gap per fold
  * ``underfit``          — default catch-all when no specific cause fires
  * ``strategy_logic``    — pure rule-based variant beats FreqAI-gated variant
  * ``regime_specific``   — single regime is the bleeder
  * ``hyperopt_unstable`` — top-10 OOS sharpe variance > 0.5 (lucky params)

The report drives the next step (``backtest-diagnostics.md`` skill — the
Claude analyst playbook), which proposes 1-3 hypotheses for the iteration
fix.

Iron Laws:
  * **Iron Law 3 (anti-placeholder):** no mock data; real psycopg connection;
    hard-fail on missing ``--run-id`` or non-existent run id.
  * **Iron Law 4:** does NOT auto-edit any operator-only file (config.json,
    skills/, ADRs, references/). Output is read-only JSON.
  * **Iron Law 5:** does NOT write to ``brain.brain_journal`` (only the
    runtime oversight loop and post-mortem cron do).

Usage::

    python -m infra.scripts.diagnose_backtest_failure --run-id 42

Output:
  * stdout: the diagnostic JSON, pretty-printed
  * file:   ``docs/research/iterations/iteration-{run_id}-diagnostic.json``

Exit codes:
  0: success (report produced, regardless of failure_mode classification)
  1: any failure (DB error, missing run id, malformed metrics)
"""
from __future__ import annotations

import argparse
import contextlib
import json
import logging
import os
import statistics
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger("diagnose_backtest_failure")

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_OUTPUT_DIR = REPO_ROOT / "docs" / "research" / "iterations"

# Classifier thresholds — these are documented numerical decisions per
# CLAUDE.md "no hardcoded thresholds outside config" rule. They live here
# (not config.json) because they govern an INTERNAL diagnostic, not a
# trading risk rail. Operator-tunable by editing this constant block.
OVERFIT_GAP_PCT_THRESHOLD: float = 30.0    # train/test sharpe gap > 30% = overfit signal
HYPEROPT_VARIANCE_THRESHOLD: float = 0.5   # top-N sharpe variance > 0.5 = unstable
HYPEROPT_MIN_ROWS: int = 3                 # need >=3 hyperopt rows to compute variance


# ---------------------------------------------------------------------------
# Pure classifiers (no DB) — unit-testable
# ---------------------------------------------------------------------------
def classify_overfit_gap(*, train_sharpe: float, test_sharpe: float) -> dict[str, Any]:
    """Compare train vs test Sharpe per fold. Gap >30% flags overfit.

    The gap is computed as ``|train - test| / max(|train|, eps)`` to avoid
    division by zero when test_sharpe collapses to zero. Returns a dict with
    ``is_overfit`` (bool), ``gap_pct`` (float), and the raw inputs for the
    report.
    """
    eps = 1e-9
    denom = max(abs(train_sharpe), eps)
    gap_pct = abs(train_sharpe - test_sharpe) / denom * 100.0
    return {
        "train_sharpe": float(train_sharpe),
        "test_sharpe": float(test_sharpe),
        "gap_pct": round(gap_pct, 2),
        "threshold_pct": OVERFIT_GAP_PCT_THRESHOLD,
        "is_overfit": gap_pct > OVERFIT_GAP_PCT_THRESHOLD,
    }


def classify_hyperopt_stability(*, top_n_sharpes: list[float]) -> dict[str, Any]:
    """Compute population variance of top-N hyperopt OOS Sharpes. High
    variance = lucky params (different param sets give wildly different OOS
    results). Threshold from spec: variance > 0.5 = unstable.
    """
    if len(top_n_sharpes) < HYPEROPT_MIN_ROWS:
        return {
            "status": "insufficient_data",
            "reason": (
                f"need >= {HYPEROPT_MIN_ROWS} hyperopt rows; got {len(top_n_sharpes)}"
            ),
            "is_unstable": False,
            "variance": None,
            "n_samples": len(top_n_sharpes),
        }
    variance = statistics.pvariance(top_n_sharpes)
    return {
        "status": "computed",
        "n_samples": len(top_n_sharpes),
        "variance": round(variance, 4),
        "threshold": HYPEROPT_VARIANCE_THRESHOLD,
        "is_unstable": variance > HYPEROPT_VARIANCE_THRESHOLD,
        "min": round(min(top_n_sharpes), 4),
        "max": round(max(top_n_sharpes), 4),
    }


def classify_failure_mode(
    *,
    overfit_flag: bool,
    hyperopt_unstable_flag: bool,
    regime_bleeder_flag: bool,
    strategy_vs_ml_degraded: bool,
) -> str:
    """Combine sub-check flags into a single classification.

    Priority order (most actionable → least): overfit > hyperopt_unstable >
    regime_specific > strategy_logic > underfit.

    ``underfit`` is the default catch-all when no specific cause was
    identified but the gate failed; the operator must inspect features /
    model capacity manually in that case.
    """
    if overfit_flag:
        return "overfit"
    if hyperopt_unstable_flag:
        return "hyperopt_unstable"
    if regime_bleeder_flag:
        return "regime_specific"
    if strategy_vs_ml_degraded:
        return "strategy_logic"
    return "underfit"


# ---------------------------------------------------------------------------
# Postgres connection
# ---------------------------------------------------------------------------
def _postgres_dsn() -> str:
    """Build DSN from required env. Hard-fail (KeyError) if any var missing.
    No silent fallbacks (Iron Law 3, CLAUDE.md anti-placeholder rule §5).
    """
    return (
        f"postgresql://{os.environ['POSTGRES_USER']}:"
        f"{os.environ['POSTGRES_PASSWORD']}@"
        f"{os.environ['POSTGRES_HOST']}:"
        f"{os.environ['POSTGRES_PORT']}/"
        f"{os.environ['POSTGRES_DB']}"
    )


def _connect() -> Any:
    import psycopg
    return psycopg.connect(_postgres_dsn())


# ---------------------------------------------------------------------------
# DiagnosticEngine
# ---------------------------------------------------------------------------
@dataclass
class DiagnosticEngine:
    """Run the 4 sub-checks for a given ``brain.backtest_runs.id``.

    Sub-checks:
      1. Overfit gap            — full impl (reads metrics JSONB)
      2. Strategy-vs-ML compare — stub: looks for a sibling run with
                                   ``parameters->>'freqai_disabled' = 'true'``;
                                   reports ``needs_separate_backtest`` if none.
      3. Per-regime breakdown   — stub: joins brain.signals on the test
                                   window; reports ``unavailable_no_signals``
                                   when empty (Phase 6 cron not yet running).
      4. Hyperopt stability     — full impl (reads brain.hyperopt_results
                                   for the same strategy_version, top-N by loss).
    """

    connection: Any
    output_dir: Path = field(default=DEFAULT_OUTPUT_DIR)
    top_n_hyperopt: int = 10

    def run(self, *, run_id: int) -> dict[str, Any]:
        run_row = self._load_run(run_id)
        if run_row is None:
            raise LookupError(
                f"brain.backtest_runs.id={run_id} not found — cannot diagnose."
            )

        sub_overfit = self._check_overfit(run_row)
        sub_strategy_vs_ml = self._check_strategy_vs_ml(run_row)
        sub_per_regime = self._check_per_regime(run_row)
        sub_hyperopt = self._check_hyperopt_stability(run_row)

        failure_mode = classify_failure_mode(
            overfit_flag=bool(sub_overfit.get("is_overfit", False)),
            hyperopt_unstable_flag=bool(sub_hyperopt.get("is_unstable", False)),
            regime_bleeder_flag=bool(sub_per_regime.get("has_bleeder", False)),
            strategy_vs_ml_degraded=bool(sub_strategy_vs_ml.get("ml_helps", False) is False
                                         and sub_strategy_vs_ml.get("status") == "compared"),
        )

        report: dict[str, Any] = {
            "run_id": run_row["id"],
            "strategy_version": run_row["strategy_version"],
            "fold_index": run_row["fold_index"],
            "gate_passed": run_row["gate_passed"],
            "metrics": run_row["metrics"],
            "failure_mode": failure_mode,
            "sub_checks": {
                "overfit": sub_overfit,
                "strategy_vs_ml": sub_strategy_vs_ml,
                "per_regime": sub_per_regime,
                "hyperopt_stability": sub_hyperopt,
            },
            "next_step": (
                "Invoke Claude with skill backtest-diagnostics.md to propose "
                "1-3 hypotheses. See "
                "crypto-bot/claude-routines/skills/backtest-diagnostics.md."
            ),
        }

        self._write_report(run_id=run_row["id"], report=report)
        return report

    # ------------------------------------------------------------------
    # DB readers
    # ------------------------------------------------------------------
    def _load_run(self, run_id: int) -> dict[str, Any] | None:
        with self.connection.cursor() as cur:
            cur.execute(
                """
                SELECT id, strategy_version, fold_index,
                       train_start, train_end, test_start, test_end,
                       parameters, metrics, gate_passed
                FROM brain.backtest_runs
                WHERE id = %s
                """,
                (run_id,),
            )
            row = cur.fetchone()
        if row is None:
            return None
        return {
            "id": int(row[0]),
            "strategy_version": str(row[1]),
            "fold_index": int(row[2]),
            "train_start": row[3],
            "train_end": row[4],
            "test_start": row[5],
            "test_end": row[6],
            "parameters": row[7] if isinstance(row[7], dict) else json.loads(row[7]),
            "metrics": row[8] if isinstance(row[8], dict) else json.loads(row[8]),
            "gate_passed": bool(row[9]),
        }

    # ------------------------------------------------------------------
    # Sub-check 1: overfit gap (full impl)
    # ------------------------------------------------------------------
    def _check_overfit(self, run_row: dict[str, Any]) -> dict[str, Any]:
        metrics = run_row["metrics"] or {}
        train = metrics.get("train_sharpe")
        test = metrics.get("test_sharpe")
        if train is None or test is None:
            return {
                "status": "metrics_missing",
                "reason": (
                    "metrics JSONB missing train_sharpe and/or test_sharpe — "
                    "the walk-forward orchestrator must persist both per fold "
                    "(Phase 9 spec). Re-run with the patched orchestrator."
                ),
                "is_overfit": False,
            }
        result = classify_overfit_gap(
            train_sharpe=float(train), test_sharpe=float(test)
        )
        result["status"] = "computed"
        return result

    # ------------------------------------------------------------------
    # Sub-check 2: strategy-vs-ML (stub — needs separate backtest)
    # ------------------------------------------------------------------
    def _check_strategy_vs_ml(self, run_row: dict[str, Any]) -> dict[str, Any]:
        """Look for a sibling run with FreqAI disabled. If found, compare
        Sharpe; otherwise report ``needs_separate_backtest``.

        We do NOT auto-trigger a backtest here — that's an operator-driven
        action (the spec is explicit). The stub provides a structured TODO
        the operator/Claude can act on.
        """
        params = run_row.get("parameters") or {}
        if params.get("freqai_disabled") is True:
            # The supplied run IS the no-FreqAI variant — the comparison must
            # be done against a different (FreqAI-enabled) sibling instead.
            return {
                "status": "needs_separate_backtest",
                "reason": (
                    "the supplied run already has freqai_disabled=true; "
                    "operator must supply the FreqAI-enabled sibling run id "
                    "for a meaningful comparison."
                ),
                "ml_helps": None,
            }

        # Try to find a no-FreqAI sibling for the same strategy_version + fold.
        with self.connection.cursor() as cur:
            cur.execute(
                """
                SELECT id, metrics
                FROM brain.backtest_runs
                WHERE strategy_version = %s
                  AND fold_index = %s
                  AND (parameters->>'freqai_disabled')::boolean = true
                ORDER BY started_at DESC
                LIMIT 1
                """,
                (run_row["strategy_version"], run_row["fold_index"]),
            )
            sibling = cur.fetchone()

        if sibling is None:
            return {
                "status": "needs_separate_backtest",
                "reason": (
                    "no sibling run with parameters.freqai_disabled=true "
                    "exists for this strategy_version + fold_index. Operator "
                    "must run the no-FreqAI variant before this check is "
                    "meaningful (the diagnostic does NOT auto-trigger a "
                    "backtest — see Phase 9.5.A spec)."
                ),
                "ml_helps": None,
                "todo_command": (
                    f"freqtrade backtesting --strategy-version "
                    f"{run_row['strategy_version']}-no-freqai "
                    f"--timerange {run_row['test_start']}-{run_row['test_end']}"
                ),
            }

        sibling_metrics = sibling[1] if isinstance(sibling[1], dict) else json.loads(sibling[1])
        ml_sharpe = (run_row["metrics"] or {}).get("sharpe")
        plain_sharpe = sibling_metrics.get("sharpe")
        if ml_sharpe is None or plain_sharpe is None:
            return {
                "status": "needs_separate_backtest",
                "reason": "sibling found but missing sharpe in metrics JSONB",
                "ml_helps": None,
            }
        ml_helps = float(ml_sharpe) > float(plain_sharpe)
        return {
            "status": "compared",
            "ml_sharpe": float(ml_sharpe),
            "plain_sharpe": float(plain_sharpe),
            "ml_helps": ml_helps,
            "sibling_run_id": int(sibling[0]),
        }

    # ------------------------------------------------------------------
    # Sub-check 3: per-regime breakdown (stub — empty signals path)
    # ------------------------------------------------------------------
    def _check_per_regime(self, run_row: dict[str, Any]) -> dict[str, Any]:
        """Group brain.signals.regime over the test window. If brain.signals
        is empty for that window (Phase 6 cron hasn't populated yet), report
        unavailable.
        """
        with self.connection.cursor() as cur:
            cur.execute(
                """
                SELECT
                    COALESCE(j.regime, 'unknown') AS regime,
                    COUNT(*)::int                 AS n_signals,
                    AVG(j.actual_pnl_pct)::float  AS avg_pnl,
                    SUM(CASE WHEN j.actual_pnl_pct > 0 THEN 1 ELSE 0 END)::int AS wins
                FROM brain.signals s
                LEFT JOIN brain.brain_journal j ON j.signal_id = s.id
                WHERE s.ts >= %s AND s.ts < %s
                GROUP BY 1
                """,
                (run_row["test_start"], run_row["test_end"]),
            )
            rows = cur.fetchall()

        if not rows:
            return {
                "status": "unavailable_no_signals",
                "reason": (
                    "brain.signals has zero rows in the test window "
                    f"[{run_row['test_start']}, {run_row['test_end']}); "
                    "per-regime breakdown unavailable until Phase 6 "
                    "post-mortem cron + Phase 5 oversight loop have populated "
                    "the journal. This is expected before live/paper-trade."
                ),
                "has_bleeder": False,
            }

        breakdown: list[dict[str, Any]] = []
        for regime, n_signals, avg_pnl, wins in rows:
            n = int(n_signals)
            breakdown.append({
                "regime": str(regime),
                "n_signals": n,
                "avg_pnl_pct": float(avg_pnl) if avg_pnl is not None else None,
                "win_rate": (float(wins) / n) if n > 0 else None,
            })
        # Bleeder = any regime with avg_pnl < -1.0% AND >= 10 signals (statistical floor).
        bleeders = [
            r for r in breakdown
            if r["avg_pnl_pct"] is not None
            and r["avg_pnl_pct"] < -1.0
            and r["n_signals"] >= 10
        ]
        return {
            "status": "computed",
            "breakdown": breakdown,
            "bleeders": bleeders,
            "has_bleeder": bool(bleeders),
        }

    # ------------------------------------------------------------------
    # Sub-check 4: hyperopt stability (full impl)
    # ------------------------------------------------------------------
    def _check_hyperopt_stability(self, run_row: dict[str, Any]) -> dict[str, Any]:
        with self.connection.cursor() as cur:
            cur.execute(
                """
                SELECT sharpe
                FROM brain.hyperopt_results
                WHERE strategy_version = %s
                  AND sharpe IS NOT NULL
                ORDER BY loss ASC
                LIMIT %s
                """,
                (run_row["strategy_version"], self.top_n_hyperopt),
            )
            rows = cur.fetchall()
        sharpes = [float(r[0]) for r in rows]
        result = classify_hyperopt_stability(top_n_sharpes=sharpes)
        result["strategy_version"] = run_row["strategy_version"]
        result["top_n_requested"] = self.top_n_hyperopt
        return result

    # ------------------------------------------------------------------
    # Output
    # ------------------------------------------------------------------
    def _write_report(self, *, run_id: int, report: dict[str, Any]) -> None:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        out = self.output_dir / f"iteration-{run_id}-diagnostic.json"
        out.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
        logger.info("diagnostic report written to %s", out)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="diagnose_backtest_failure",
        description=(
            "Phase 9.5.A — produce a structured JSON diagnostic for a failed "
            "walk-forward backtest_runs row. Hard-fails if --run-id missing "
            "or non-existent."
        ),
    )
    p.add_argument(
        "--run-id",
        type=int,
        required=True,
        help="brain.backtest_runs.id of the failed fold to diagnose.",
    )
    p.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=(
            "Directory for iteration-{id}-diagnostic.json. Default: "
            "docs/research/iterations/."
        ),
    )
    p.add_argument(
        "--top-n-hyperopt",
        type=int,
        default=10,
        help="Top-N hyperopt rows to include in the variance check. Default: 10.",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    args = _parse_args(argv)
    try:
        conn = _connect()
    except KeyError as exc:
        logger.error("missing required env var %s — refusing to silently default", exc)
        return 1
    try:
        engine = DiagnosticEngine(connection=conn, output_dir=args.output_dir,
                                  top_n_hyperopt=args.top_n_hyperopt)
        report = engine.run(run_id=args.run_id)
    except LookupError as exc:
        logger.error("%s", exc)
        return 1
    except Exception:
        logger.exception("diagnostic failed")
        return 1
    finally:
        with contextlib.suppress(Exception):
            conn.close()

    print(json.dumps(report, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
