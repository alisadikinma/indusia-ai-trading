"""Phase 0.5 tests for the regime-aware walk-forward fold orchestrator.

These tests guard Iron Law 2: a strategy whose 5-fold backtest does NOT
include the post-2024-01-11 (Spot BTC ETF approval) regime cannot pass
production capital protection. The Chow Test break (p=0.004) per
references/crypto/regime-taxonomy.md Topic 7 means momentum signals went
extinct after the ETF approval — any backtest that ignores this is a
silent OOS blind spot.

The script under test lives at infra/scripts/walkforward_folds.py and is
invoked via subprocess (mirrors tests/test_compile_refs.py invocation
pattern).
"""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "infra" / "scripts" / "walkforward_folds.py"

ETF_DATE = date(2024, 1, 11)


def _iso(d: str) -> date:
    return datetime.fromisoformat(d).date()


def _run(args: list[str], cwd: Path = REPO_ROOT) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        cwd=str(cwd),
    )


@pytest.fixture(scope="module")
def standard_folds(tmp_path_factory: pytest.TempPathFactory) -> dict:
    """Run the script once with the canonical happy-path args and return parsed JSON."""
    out = tmp_path_factory.mktemp("wf") / "folds.json"
    result = _run(
        [
            "--start", "2018-01-01",
            "--end", "2026-05-07",
            "--n-folds", "5",
            "--mode", "anchored",
            "--post-etf-required",
            "--output", str(out),
        ]
    )
    assert result.returncode == 0, (
        f"walkforward_folds.py failed (exit {result.returncode}). "
        f"stderr:\n{result.stderr}\nstdout:\n{result.stdout}"
    )
    assert out.is_file(), f"output file {out} not created"
    return json.loads(out.read_text(encoding="utf-8"))


def test_script_exists() -> None:
    assert SCRIPT.is_file(), f"{SCRIPT.relative_to(REPO_ROOT)} missing"


def test_happy_path_validation_all_green(standard_folds: dict) -> None:
    v = standard_folds["validation"]
    assert v["post_etf_fold_present"] is True
    assert v["all_folds_have_min_180_days_test"] is True
    assert v["no_overlap_between_folds"] is True
    assert isinstance(v["post_etf_fold_index"], int)
    assert 1 <= v["post_etf_fold_index"] <= 5


def test_produces_n_folds(standard_folds: dict) -> None:
    folds = standard_folds["folds"]
    assert len(folds) == 5
    for i, f in enumerate(folds, start=1):
        assert f["fold_index"] == i


def test_post_etf_fold_straddles_2024_01_11(standard_folds: dict) -> None:
    idx = standard_folds["validation"]["post_etf_fold_index"]
    fold = standard_folds["folds"][idx - 1]
    test_start = _iso(fold["test_start"])
    test_end = _iso(fold["test_end"])
    assert test_start <= ETF_DATE <= test_end, (
        f"fold #{idx} test window {test_start}..{test_end} does NOT straddle "
        f"2024-01-11; Iron Law 2 gate would not detect post-ETF regime"
    )


@pytest.mark.parametrize("fold_index", [1, 2, 3, 4, 5])
def test_each_fold_has_min_180_days_test_window(
    standard_folds: dict, fold_index: int
) -> None:
    fold = standard_folds["folds"][fold_index - 1]
    span = (_iso(fold["test_end"]) - _iso(fold["test_start"])).days + 1
    assert span >= 180, (
        f"fold #{fold_index} test window only {span} days; need >=180 to give "
        f"daily-tf strategies a shot at >=100 trades (Iron Law 2 gate)"
    )


def test_no_overlap_between_test_windows(standard_folds: dict) -> None:
    folds = standard_folds["folds"]
    for i, a in enumerate(folds):
        for b in folds[i + 1 :]:
            a_s, a_e = _iso(a["test_start"]), _iso(a["test_end"])
            b_s, b_e = _iso(b["test_start"]), _iso(b["test_end"])
            assert a_e < b_s or b_e < a_s, (
                f"fold #{a['fold_index']} test {a_s}..{a_e} overlaps "
                f"fold #{b['fold_index']} test {b_s}..{b_e}"
            )


def test_anchored_mode_shares_train_start(standard_folds: dict) -> None:
    starts = {f["train_start"] for f in standard_folds["folds"]}
    assert starts == {"2018-01-01"}, (
        f"anchored mode should pin train_start; got {starts}"
    )


def test_anchored_mode_train_end_is_day_before_test_start(standard_folds: dict) -> None:
    for f in standard_folds["folds"]:
        gap = (_iso(f["test_start"]) - _iso(f["train_end"])).days
        assert gap == 1, (
            f"fold #{f['fold_index']}: train_end {f['train_end']} "
            f"-> test_start {f['test_start']} gap = {gap} days (need 1)"
        )


def test_rolling_mode_consistent_train_length(tmp_path: Path) -> None:
    out = tmp_path / "rolling.json"
    result = _run(
        [
            "--start", "2018-01-01",
            "--end", "2026-05-07",
            "--n-folds", "5",
            "--mode", "rolling",
            "--post-etf-required",
            "--output", str(out),
        ]
    )
    assert result.returncode == 0, f"rolling mode failed: {result.stderr}"
    data = json.loads(out.read_text(encoding="utf-8"))
    train_lengths = [
        (_iso(f["train_end"]) - _iso(f["train_start"])).days
        for f in data["folds"]
    ]
    # Allow at most 1-day variance from boundary rounding
    assert max(train_lengths) - min(train_lengths) <= 1, (
        f"rolling mode train lengths inconsistent: {train_lengths}"
    )


def test_post_etf_required_fails_when_range_excludes_etf(tmp_path: Path) -> None:
    out = tmp_path / "fail.json"
    result = _run(
        [
            "--start", "2018-01-01",
            "--end", "2023-12-31",
            "--n-folds", "5",
            "--mode", "anchored",
            "--post-etf-required",
            "--output", str(out),
        ]
    )
    assert result.returncode != 0, (
        f"script must hard-fail when --post-etf-required cannot be satisfied; "
        f"got exit={result.returncode} stdout={result.stdout}"
    )
    blob = (result.stderr + result.stdout).lower()
    assert any(
        marker in blob for marker in ("etf", "2024-01-11", "post-etf")
    ), f"stderr should mention ETF/2024-01-11/post-ETF; got: {result.stderr}"


def test_json_schema_required_keys(standard_folds: dict) -> None:
    for top_key in ("input", "structural_breaks", "folds", "validation"):
        assert top_key in standard_folds, f"missing top-level key: {top_key}"
    inp = standard_folds["input"]
    for k in ("start", "end", "n_folds", "mode", "post_etf_required"):
        assert k in inp, f"input missing key: {k}"
    for br in standard_folds["structural_breaks"]:
        assert "date" in br and "event" in br
    for f in standard_folds["folds"]:
        for k in (
            "fold_index",
            "train_start",
            "train_end",
            "test_start",
            "test_end",
            "structural_breaks_in_test",
            "post_etf_window",
        ):
            assert k in f, f"fold missing key: {k}"


def test_structural_breaks_includes_etf_date(standard_folds: dict) -> None:
    dates = {b["date"] for b in standard_folds["structural_breaks"]}
    required = {
        "2017-12-15",
        "2020-03-12",
        "2022-05-08",
        "2022-11-08",
        "2024-01-11",
        "2024-04-19",
    }
    missing = required - dates
    assert not missing, f"structural_breaks missing required dates: {missing}"


def test_determinism_same_args_same_output(tmp_path: Path) -> None:
    out_a = tmp_path / "a.json"
    out_b = tmp_path / "b.json"
    args = [
        "--start", "2018-01-01",
        "--end", "2026-05-07",
        "--n-folds", "5",
        "--mode", "anchored",
        "--post-etf-required",
    ]
    r_a = _run([*args, "--output", str(out_a)])
    r_b = _run([*args, "--output", str(out_b)])
    assert r_a.returncode == 0 and r_b.returncode == 0
    a_obj = json.loads(out_a.read_text(encoding="utf-8"))
    b_obj = json.loads(out_b.read_text(encoding="utf-8"))
    assert a_obj == b_obj, "non-deterministic output across identical invocations"


def test_post_etf_window_flag_set_correctly(standard_folds: dict) -> None:
    for f in standard_folds["folds"]:
        ts = _iso(f["test_start"])
        te = _iso(f["test_end"])
        straddles = ts <= ETF_DATE <= te
        assert f["post_etf_window"] is straddles, (
            f"fold #{f['fold_index']} post_etf_window={f['post_etf_window']} "
            f"but test {ts}..{te} straddles_etf={straddles}"
        )


def test_structural_breaks_in_test_correctness(standard_folds: dict) -> None:
    breaks = {b["date"]: b["event"] for b in standard_folds["structural_breaks"]}
    for f in standard_folds["folds"]:
        ts = _iso(f["test_start"])
        te = _iso(f["test_end"])
        expected = sorted(
            d for d in breaks if ts <= _iso(d) <= te
        )
        actual = sorted(f["structural_breaks_in_test"])
        assert actual == expected, (
            f"fold #{f['fold_index']}: structural_breaks_in_test={actual} "
            f"but expected {expected} for window {ts}..{te}"
        )


def test_stdout_default_when_no_output_arg(tmp_path: Path) -> None:
    """When --output omitted, JSON goes to stdout."""
    result = _run(
        [
            "--start", "2018-01-01",
            "--end", "2026-05-07",
            "--n-folds", "5",
            "--mode", "anchored",
            "--post-etf-required",
        ]
    )
    assert result.returncode == 0, f"stderr={result.stderr}"
    parsed = json.loads(result.stdout)
    assert parsed["validation"]["post_etf_fold_present"] is True
