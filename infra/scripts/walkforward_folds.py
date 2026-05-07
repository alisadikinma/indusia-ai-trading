"""Regime-aware walk-forward fold orchestrator.

Generates N OOS folds for backtest harnesses, ensuring at least one fold's
test window straddles the 2024-01-11 Spot BTC ETF approval (when
``--post-etf-required`` is set). The Chow Test break with p=0.004 documented
in ``references/crypto/regime-taxonomy.md`` Topic 7 means momentum signals
went extinct after that date — a 5-fold backtest whose test windows all
end pre-2024-01-11 would silently fail Iron Law 2 by construction.

Output JSON is the machine-readable input contract for backtest harnesses
that populate ``brain.backtest_runs.fold_index`` per
``infra/migrations/000_bootstrap_schemas.sql``.

Design references:
  - ``CLAUDE.md`` Iron Law 2 (no live trade without backtest sign-off)
  - ``docs/decisions/2026-05-07-002-references-rag-layer.md`` (ADR-002)
  - ``references/crypto/regime-taxonomy.md`` Topic 7
  - ``docs/plans/2026-05-06-ai-trading-247.md`` Phase 9

Usage::

    python infra/scripts/walkforward_folds.py \\
        --start 2018-01-01 \\
        --end 2026-05-07 \\
        --n-folds 5 \\
        --mode anchored \\
        --post-etf-required \\
        --output folds.json
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Sequence


# Hardcoded structural breaks (per references/crypto/regime-taxonomy.md +
# project plan). Order is chronological; sourced from cited research, NOT
# magic numbers — each entry has a verifiable historical referent.
STRUCTURAL_BREAKS: tuple[tuple[str, str], ...] = (
    ("2017-12-15", "ICO bubble peak/pop — sentiment regime change"),
    ("2020-03-12", "COVID crash + global liquidity shock — macro correlation spike"),
    ("2022-05-08", "Terra/Luna collapse — stablecoin trust break"),
    ("2022-11-08", "FTX collapse — centralized exchange trust break"),
    ("2024-01-11", "Spot BTC ETF approval — momentum->mean-reversion regime flip (Chow p=0.004)"),
    ("2024-04-19", "BTC halving — supply-side regime"),
)

ETF_DATE: date = date(2024, 1, 11)
MIN_TEST_DAYS: int = 180


@dataclass(frozen=True)
class Fold:
    fold_index: int
    train_start: date
    train_end: date
    test_start: date
    test_end: date

    def to_dict(self) -> dict:
        return {
            "fold_index": self.fold_index,
            "train_start": self.train_start.isoformat(),
            "train_end": self.train_end.isoformat(),
            "test_start": self.test_start.isoformat(),
            "test_end": self.test_end.isoformat(),
            "structural_breaks_in_test": _breaks_in(self.test_start, self.test_end),
            "post_etf_window": self.test_start <= ETF_DATE <= self.test_end,
        }


def _breaks_in(start: date, end: date) -> list[str]:
    return [d for d, _ in STRUCTURAL_BREAKS if start <= _parse(d) <= end]


def _parse(s: str) -> date:
    return datetime.fromisoformat(s).date()


def _build_test_segments(
    test_region_start: date, test_region_end: date, n_folds: int
) -> list[tuple[date, date]]:
    """Slice [test_region_start, test_region_end] into n_folds disjoint equal
    segments. Endpoints are integer day offsets so output is deterministic and
    fully covers the region with no overlap."""
    total_days = (test_region_end - test_region_start).days + 1
    if total_days < n_folds * MIN_TEST_DAYS:
        raise ValueError(
            f"test region {test_region_start}..{test_region_end} = {total_days} days "
            f"cannot accommodate {n_folds} folds of >={MIN_TEST_DAYS} days each "
            f"(need >= {n_folds * MIN_TEST_DAYS}). Widen --start/--end."
        )
    base = total_days // n_folds
    extra = total_days % n_folds  # distribute leftover days to FIRST `extra` folds
    segments: list[tuple[date, date]] = []
    cursor = test_region_start
    for i in range(n_folds):
        size = base + (1 if i < extra else 0)
        seg_start = cursor
        seg_end = cursor + timedelta(days=size - 1)
        segments.append((seg_start, seg_end))
        cursor = seg_end + timedelta(days=1)
    return segments


def _segments_have_etf_straddle(segments: Sequence[tuple[date, date]]) -> bool:
    return any(s <= ETF_DATE <= e for s, e in segments)


def _shift_segments_to_straddle_etf(
    segments: list[tuple[date, date]],
    region_start: date,
    region_end: date,
) -> list[tuple[date, date]] | None:
    """If equal-slice segments do not straddle ETF_DATE, find the segment
    closest to it and shift all segments by a uniform delta so that segment
    contains ETF_DATE. Preserves segment lengths, no-overlap, and bounds
    within [region_start, region_end]. Returns None if shift impossible."""
    # Pick segment whose midpoint is nearest ETF_DATE.
    best_idx = min(
        range(len(segments)),
        key=lambda i: abs(
            ((segments[i][0] + (segments[i][1] - segments[i][0]) / 2) - ETF_DATE).days
        ),
    )
    seg_start, seg_end = segments[best_idx]
    if seg_start <= ETF_DATE <= seg_end:
        return segments  # already straddles
    # Compute required shift: move chosen segment so it contains ETF_DATE.
    if ETF_DATE < seg_start:
        delta_days = (ETF_DATE - seg_start).days  # negative
    else:
        delta_days = (ETF_DATE - seg_end).days  # positive
    shifted = [
        (s + timedelta(days=delta_days), e + timedelta(days=delta_days))
        for s, e in segments
    ]
    first_start = shifted[0][0]
    last_end = shifted[-1][1]
    if first_start < region_start or last_end > region_end:
        return None
    return shifted


def generate_folds(
    start: date,
    end: date,
    n_folds: int,
    mode: str,
    post_etf_required: bool,
) -> list[Fold]:
    if end <= start:
        raise ValueError(f"--end {end} must be after --start {start}")
    if n_folds < 1:
        raise ValueError(f"--n-folds must be >= 1, got {n_folds}")

    total_span = (end - start).days + 1
    # Reserve initial training window: max of (1/3 of total range, 365 days)
    # bounded so test region still fits N folds * MIN_TEST_DAYS.
    min_test_region = n_folds * MIN_TEST_DAYS
    max_initial_train = total_span - min_test_region - 1
    if max_initial_train < 1:
        raise ValueError(
            f"date range {start}..{end} = {total_span} days too short for "
            f"{n_folds} folds at >={MIN_TEST_DAYS} days each "
            f"(need >= {min_test_region + 2} days total)"
        )
    desired_initial_train = max(365, total_span // 3)
    initial_train_days = min(desired_initial_train, max_initial_train)
    test_region_start = start + timedelta(days=initial_train_days)
    test_region_end = end

    segments = _build_test_segments(test_region_start, test_region_end, n_folds)

    if post_etf_required:
        if end < ETF_DATE:
            raise ValueError(
                f"--post-etf-required but --end {end} is before 2024-01-11 "
                f"(Spot BTC ETF approval). Cannot include post-ETF regime in any "
                f"fold. Extend --end past 2024-01-11 or drop --post-etf-required."
            )
        if test_region_start > ETF_DATE:
            raise ValueError(
                f"--post-etf-required but the test region starts {test_region_start} "
                f"(after the {ETF_DATE} ETF approval). The reserved training window "
                f"swallows the ETF date. Provide an earlier --start or shorter --end."
            )
        if not _segments_have_etf_straddle(segments):
            shifted = _shift_segments_to_straddle_etf(
                segments, test_region_start, test_region_end
            )
            if shifted is None:
                raise ValueError(
                    f"--post-etf-required but cannot align any of the {n_folds} "
                    f"equal-length test segments to straddle 2024-01-11 within "
                    f"region {test_region_start}..{test_region_end}. Widen the range."
                )
            segments = shifted
            # After shift, region_start may differ; rebase test_region_start.
            test_region_start = segments[0][0]

    folds: list[Fold] = []
    if mode == "anchored":
        train_start = start
        for i, (ts, te) in enumerate(segments, start=1):
            train_end = ts - timedelta(days=1)
            folds.append(
                Fold(
                    fold_index=i,
                    train_start=train_start,
                    train_end=train_end,
                    test_start=ts,
                    test_end=te,
                )
            )
    elif mode == "rolling":
        rolling_train_days = initial_train_days
        for i, (ts, te) in enumerate(segments, start=1):
            train_end = ts - timedelta(days=1)
            train_start = train_end - timedelta(days=rolling_train_days - 1)
            if train_start < start:
                # Earliest fold may rely on shorter window; pin to --start to avoid
                # synthesizing pre-data dates.
                train_start = start
            folds.append(
                Fold(
                    fold_index=i,
                    train_start=train_start,
                    train_end=train_end,
                    test_start=ts,
                    test_end=te,
                )
            )
    else:
        raise ValueError(f"--mode must be 'anchored' or 'rolling', got {mode!r}")

    return folds


def _validate_folds(folds: list[Fold]) -> dict:
    # post-ETF presence
    post_etf_idx: int | None = None
    for f in folds:
        if f.test_start <= ETF_DATE <= f.test_end:
            post_etf_idx = f.fold_index
            break
    # 180-day rule
    all_min_180 = all(
        ((f.test_end - f.test_start).days + 1) >= MIN_TEST_DAYS for f in folds
    )
    # No overlap
    no_overlap = True
    for i, a in enumerate(folds):
        for b in folds[i + 1 :]:
            if not (a.test_end < b.test_start or b.test_end < a.test_start):
                no_overlap = False
                break
        if not no_overlap:
            break
    return {
        "post_etf_fold_present": post_etf_idx is not None,
        "post_etf_fold_index": post_etf_idx,
        "all_folds_have_min_180_days_test": all_min_180,
        "no_overlap_between_folds": no_overlap,
    }


def build_payload(
    start: date,
    end: date,
    n_folds: int,
    mode: str,
    post_etf_required: bool,
) -> dict:
    folds = generate_folds(start, end, n_folds, mode, post_etf_required)
    return {
        "input": {
            "start": start.isoformat(),
            "end": end.isoformat(),
            "n_folds": n_folds,
            "mode": mode,
            "post_etf_required": post_etf_required,
        },
        "structural_breaks": [
            {"date": d, "event": e} for d, e in STRUCTURAL_BREAKS
        ],
        "folds": [f.to_dict() for f in folds],
        "validation": _validate_folds(folds),
    }


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "Regime-aware walk-forward fold orchestrator. Generates N OOS folds "
            "and (when --post-etf-required) asserts at least one fold straddles "
            "2024-01-11 (Spot BTC ETF approval, regime-taxonomy.md Topic 7)."
        )
    )
    p.add_argument("--start", required=True, help="ISO date (UTC), inclusive")
    p.add_argument("--end", required=True, help="ISO date (UTC), inclusive")
    p.add_argument("--n-folds", type=int, default=5)
    p.add_argument(
        "--mode",
        choices=("anchored", "rolling"),
        default="anchored",
        help="anchored: train_start fixed at --start. rolling: fixed-length sliding train.",
    )
    p.add_argument(
        "--post-etf-required",
        action="store_true",
        default=False,
        help=(
            "Assert at least one fold's test window straddles 2024-01-11. "
            "Exits non-zero if the date range cannot accommodate this."
        ),
    )
    p.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Path to JSON output. Default stdout.",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        start = _parse(args.start)
        end = _parse(args.end)
    except ValueError as exc:
        print(f"error: invalid ISO date: {exc}", file=sys.stderr)
        return 1
    try:
        payload = build_payload(
            start=start,
            end=end,
            n_folds=args.n_folds,
            mode=args.mode,
            post_etf_required=args.post_etf_required,
        )
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    serialized = json.dumps(payload, indent=2, sort_keys=True)
    if args.output is not None:
        args.output.write_text(serialized + "\n", encoding="utf-8")
    else:
        sys.stdout.write(serialized + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
