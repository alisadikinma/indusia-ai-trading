"""Phase 9.5.A — diagnostic suite tests.

Covers ``infra.scripts.diagnose_backtest_failure`` — the automated diagnostic
that runs against a failed walk-forward ``brain.backtest_runs`` row and emits
a structured JSON report classifying the failure mode.

Phase 9.5 is CONDITIONAL — it only fires if the Phase 9 walk-forward gate
fails. This test file is the proactive scaffold so the diagnostic is ready
when needed (Iron Law 2 — no silent advance, but also no scrambling on
failure).

Mocking policy (Iron Law 3): the only mock allowed is the future Claude CLI
call (handled by the parent skill, NOT this script). The diagnostic itself
runs pure SQL against real Postgres; tests use a fixture transaction that
rolls back on teardown so the append-only ``brain.brain_journal`` trigger
(Iron Law 5) is not violated.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


def _postgres_dsn() -> str:
    return (
        f"postgresql://{os.environ['POSTGRES_USER']}:"
        f"{os.environ['POSTGRES_PASSWORD']}@"
        f"{os.environ['POSTGRES_HOST']}:"
        f"{os.environ['POSTGRES_PORT']}/"
        f"{os.environ['POSTGRES_DB']}"
    )


# ---------------------------------------------------------------------------
# RED step: importability test — the very first failing test of the TDD cycle.
# Fails with ImportError until ``DiagnosticEngine`` exists.
# ---------------------------------------------------------------------------
def test_imports() -> None:
    from infra.scripts.diagnose_backtest_failure import DiagnosticEngine  # noqa: F401


# ---------------------------------------------------------------------------
# Pure-logic tests (no DB) — overfit-gap classifier and JSON shape.
# ---------------------------------------------------------------------------
def test_overfit_classifier_flags_large_train_test_gap() -> None:
    """train_sharpe=2.5 vs test_sharpe=0.8 → gap 1.7 → flag overfit."""
    from infra.scripts.diagnose_backtest_failure import classify_overfit_gap

    result = classify_overfit_gap(train_sharpe=2.5, test_sharpe=0.8)
    assert result["is_overfit"] is True
    assert result["gap_pct"] >= 30.0
    # Sanity: identical metrics should NOT flag.
    clean = classify_overfit_gap(train_sharpe=1.6, test_sharpe=1.55)
    assert clean["is_overfit"] is False


def test_overfit_classifier_handles_zero_test_sharpe() -> None:
    """Edge case: test_sharpe near zero must not divide by zero."""
    from infra.scripts.diagnose_backtest_failure import classify_overfit_gap

    result = classify_overfit_gap(train_sharpe=2.0, test_sharpe=0.0)
    assert result["is_overfit"] is True
    assert result["gap_pct"] == pytest.approx(100.0, abs=1.0)


def test_hyperopt_stability_flags_high_variance() -> None:
    """Top-10 OOS sharpe variance > 0.5 across param sets → unstable."""
    from infra.scripts.diagnose_backtest_failure import classify_hyperopt_stability

    high_var = classify_hyperopt_stability(top_n_sharpes=[1.8, 0.4, 1.6, 0.3, 1.9, 0.5, 2.0, 0.2, 1.7, 0.6])
    assert high_var["is_unstable"] is True
    assert high_var["variance"] > 0.4

    low_var = classify_hyperopt_stability(top_n_sharpes=[1.55, 1.62, 1.58, 1.60, 1.57, 1.61, 1.56, 1.59, 1.63, 1.58])
    assert low_var["is_unstable"] is False


def test_hyperopt_stability_handles_too_few_rows() -> None:
    """Fewer than 3 hyperopt rows: cannot compute variance, must report skipped."""
    from infra.scripts.diagnose_backtest_failure import classify_hyperopt_stability

    skipped = classify_hyperopt_stability(top_n_sharpes=[1.5])
    assert skipped["is_unstable"] is False
    assert skipped["status"] == "insufficient_data"


def test_failure_mode_classification_priority() -> None:
    """Multiple sub-checks may fire; classification must follow documented priority:
    overfit > hyperopt_unstable > regime_specific > strategy_logic > underfit.
    """
    from infra.scripts.diagnose_backtest_failure import classify_failure_mode

    # Both overfit and hyperopt unstable → overfit wins (most actionable).
    mode = classify_failure_mode(
        overfit_flag=True,
        hyperopt_unstable_flag=True,
        regime_bleeder_flag=False,
        strategy_vs_ml_degraded=False,
    )
    assert mode == "overfit"

    # Only hyperopt unstable.
    mode2 = classify_failure_mode(
        overfit_flag=False,
        hyperopt_unstable_flag=True,
        regime_bleeder_flag=False,
        strategy_vs_ml_degraded=False,
    )
    assert mode2 == "hyperopt_unstable"

    # No flag fires → underfit (default catch-all when gate failed but no
    # specific cause identified).
    mode3 = classify_failure_mode(
        overfit_flag=False,
        hyperopt_unstable_flag=False,
        regime_bleeder_flag=False,
        strategy_vs_ml_degraded=False,
    )
    assert mode3 == "underfit"


# ---------------------------------------------------------------------------
# Integration: end-to-end against real Postgres with a synthetic failed run.
# ---------------------------------------------------------------------------
@pytest.fixture
def db_rollback() -> Any:
    """Open a real Postgres connection and ROLLBACK at the end.

    brain.brain_journal has an append-only trigger (Iron Law 5). The trigger
    fires on UPDATE/DELETE — NOT on transaction rollback — so this fixture is
    safe even when tests insert journal rows.
    """
    psycopg = pytest.importorskip("psycopg")
    conn = psycopg.connect(_postgres_dsn())
    conn.autocommit = False
    yield conn
    conn.rollback()
    conn.close()


def _insert_synthetic_failed_run(cur, *, strategy_version: str) -> list[int]:
    """Insert a 2-fold backtest run: fold 1 PASSES, fold 2 FAILS with overfit
    signal (large train/test sharpe gap). Returns list of inserted run ids.
    """
    ids: list[int] = []
    # Fold 1 — PASS: train_sharpe ~= test_sharpe.
    cur.execute(
        """
        INSERT INTO brain.backtest_runs
            (strategy_version, fold_index, train_start, train_end, test_start, test_end,
             parameters, metrics, gate_passed)
        VALUES (%s, 1,
                '2020-01-01'::timestamptz, '2022-01-01'::timestamptz,
                '2022-01-01'::timestamptz, '2023-01-01'::timestamptz,
                %s::jsonb, %s::jsonb, true)
        RETURNING id
        """,
        (
            strategy_version,
            json.dumps({"freqai_disabled": False, "lookback": 180}),
            json.dumps({
                "sharpe": 1.7, "sortino": 2.1, "max_dd": 0.18,
                "profit_factor": 1.6, "total_trades": 130, "win_rate": 0.54,
                "expectancy": 0.012, "train_sharpe": 1.75, "test_sharpe": 1.7,
            }),
        ),
    )
    ids.append(cur.fetchone()[0])

    # Fold 2 — FAIL with overfit signal: train 2.5 vs test 0.8 (gap 68%).
    cur.execute(
        """
        INSERT INTO brain.backtest_runs
            (strategy_version, fold_index, train_start, train_end, test_start, test_end,
             parameters, metrics, gate_passed)
        VALUES (%s, 2,
                '2020-01-01'::timestamptz, '2023-01-01'::timestamptz,
                '2023-01-01'::timestamptz, '2024-01-01'::timestamptz,
                %s::jsonb, %s::jsonb, false)
        RETURNING id
        """,
        (
            strategy_version,
            json.dumps({"freqai_disabled": False, "lookback": 180}),
            json.dumps({
                "sharpe": 0.8, "sortino": 1.0, "max_dd": 0.31,
                "profit_factor": 1.2, "total_trades": 110, "win_rate": 0.46,
                "expectancy": -0.003, "train_sharpe": 2.5, "test_sharpe": 0.8,
            }),
        ),
    )
    ids.append(cur.fetchone()[0])
    return ids


@pytest.mark.integration
def test_diagnostic_engine_runs_against_failed_run(db_rollback: Any, tmp_path: Path) -> None:
    """End-to-end: given the id of a failed backtest_runs row, the engine
    produces a JSON report with all 4 sub-checks present and classifies the
    failure_mode as 'overfit'.
    """
    from infra.scripts.diagnose_backtest_failure import DiagnosticEngine

    cur = db_rollback.cursor()
    strategy_version = "test-9.5a-overfit-vXYZ"
    run_ids = _insert_synthetic_failed_run(cur, strategy_version=strategy_version)
    failed_run_id = run_ids[1]  # fold 2 (the failed one)

    engine = DiagnosticEngine(connection=db_rollback, output_dir=tmp_path)
    report = engine.run(run_id=failed_run_id)

    # Required top-level keys.
    assert report["run_id"] == failed_run_id
    assert report["strategy_version"] == strategy_version
    assert "failure_mode" in report
    assert report["failure_mode"] in {
        "overfit", "underfit", "strategy_logic", "regime_specific", "hyperopt_unstable",
    }

    # All 4 sub-checks must be present (Iron Law 3 — no silent skips, but
    # checks may report status='skipped' with explicit reason).
    sub_checks = report["sub_checks"]
    assert "overfit" in sub_checks
    assert "strategy_vs_ml" in sub_checks
    assert "per_regime" in sub_checks
    assert "hyperopt_stability" in sub_checks

    # Overfit detection on this fixture: train 2.5 vs test 0.8 → MUST flag.
    assert sub_checks["overfit"]["is_overfit"] is True
    assert sub_checks["overfit"]["gap_pct"] >= 30.0

    # Strategy-vs-ML stub: should report it needs a separate non-FreqAI
    # backtest run (we didn't insert one).
    sml = sub_checks["strategy_vs_ml"]
    assert sml["status"] in {"needs_separate_backtest", "compared"}
    if sml["status"] == "needs_separate_backtest":
        assert "freqai_disabled" in sml["reason"].lower() or "no" in sml["reason"].lower()

    # Per-regime stub: brain.signals is empty for this fixture's window.
    pr = sub_checks["per_regime"]
    assert pr["status"] in {"unavailable_no_signals", "computed"}

    # Failure mode classification: overfit gap fired → mode must be 'overfit'.
    assert report["failure_mode"] == "overfit"


@pytest.mark.integration
def test_diagnostic_engine_writes_report_file(db_rollback: Any, tmp_path: Path) -> None:
    """The engine must write the report to docs/research/iterations/iteration-{id}-diagnostic.json
    under the configured output_dir."""
    from infra.scripts.diagnose_backtest_failure import DiagnosticEngine

    cur = db_rollback.cursor()
    run_ids = _insert_synthetic_failed_run(cur, strategy_version="test-9.5a-write-vABC")
    failed_run_id = run_ids[1]

    engine = DiagnosticEngine(connection=db_rollback, output_dir=tmp_path)
    engine.run(run_id=failed_run_id)

    out_file = tmp_path / f"iteration-{failed_run_id}-diagnostic.json"
    assert out_file.is_file(), f"diagnostic JSON not written to {out_file}"
    parsed = json.loads(out_file.read_text(encoding="utf-8"))
    assert parsed["run_id"] == failed_run_id


@pytest.mark.integration
def test_diagnostic_engine_hard_fails_on_unknown_run_id(db_rollback: Any, tmp_path: Path) -> None:
    """Per spec: must hard-fail (raise) when --run-id doesn't exist. No silent
    fallback (Iron Law 3)."""
    from infra.scripts.diagnose_backtest_failure import DiagnosticEngine

    engine = DiagnosticEngine(connection=db_rollback, output_dir=tmp_path)
    with pytest.raises((LookupError, ValueError)):
        engine.run(run_id=-99999999)


# ---------------------------------------------------------------------------
# Skill file presence — the analyst playbook must exist alongside the script.
# ---------------------------------------------------------------------------
def test_backtest_diagnostics_skill_exists() -> None:
    skill = REPO_ROOT / "crypto-bot" / "claude-routines" / "skills" / "backtest-diagnostics.md"
    assert skill.is_file(), f"{skill} missing — Phase 9.5.A scaffold incomplete"
    body = skill.read_text(encoding="utf-8")
    # YAML frontmatter present.
    assert body.startswith("---\n"), "skill must have YAML frontmatter"
    assert "name: backtest-diagnostics" in body
    # Required sections per spec.
    for section in (
        "## Inputs",
        "## How to analyze",
        "## What you must NOT do",
        "## Output format",
    ):
        assert section in body, f"backtest-diagnostics.md missing section: {section}"


def test_iterations_research_dir_exists() -> None:
    """The diagnostic writes per-iteration JSON to docs/research/iterations/.
    Directory must exist (with .gitkeep) so first iteration doesn't fail on
    missing parent."""
    iter_dir = REPO_ROOT / "docs" / "research" / "iterations"
    assert iter_dir.is_dir(), f"{iter_dir} missing"
