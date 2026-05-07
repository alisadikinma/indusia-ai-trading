"""Phase 6 — post-mortem cron tests.

Covers ``infra.scripts.post_mortem_cron`` — the weekly cron that reads
recent losing trades from ``brain.brain_journal``, groups them by failure
signature, invokes Claude in non-interactive mode (mocked here only), and
appends structured lessons to ``crypto-bot/claude-routines/memory/*`` and
(if the pattern is structural) ``known-traps.md``.

Mocking policy (Iron Law 3): the only mock in this file is the
``subprocess`` call to the Claude CLI inside ``invoke_claude_pattern_detector``
— shelling out to ``claude`` in CI is impractical. Every other code path
uses real Postgres + real on-disk markdown files (with tmp_path).
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import patch

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


@pytest.fixture
def journal_cleanup():
    """Remove fixture rows from brain_journal/signals AFTER each test.

    brain_journal is append-only via trigger (Iron Law 5). We therefore
    bracket each test in a SAVEPOINT-style approach: run inside a transaction
    and ROLLBACK at the end. The trigger fires on UPDATE/DELETE only, NOT
    on transaction rollback, so this is safe.
    """
    psycopg = pytest.importorskip("psycopg")
    conn = psycopg.connect(_postgres_dsn())
    conn.autocommit = False
    yield conn
    conn.rollback()
    conn.close()


def _insert_losing_signal_and_journal(
    cur,
    *,
    pair: str,
    signal_type: str,
    regime: str,
    funding_rate: float,
    atr_pct: float,
    pnl_pct: float,
    days_ago: int,
) -> tuple[int, int]:
    """Insert a (signals, brain_journal) pair representing a closed losing trade.

    Returns (signal_id, journal_id). Indicators JSON carries funding_rate and
    atr_pct so the cron can compute funding_bucket / vol_bucket from real data.
    """
    cur.execute(
        """
        INSERT INTO brain.signals (ts, pair, tf, signal_type, price_at_signal, indicators, claude_decision, claude_decided_at)
        VALUES (now() - (%s || ' days')::interval, %s, '15m', %s, 50000.0,
                jsonb_build_object('funding_rate', %s::numeric, 'atr_pct', %s::numeric),
                'approve', now() - (%s || ' days')::interval)
        RETURNING id
        """,
        (str(days_ago), pair, signal_type, funding_rate, atr_pct, str(days_ago)),
    )
    signal_id = cur.fetchone()[0]
    cur.execute(
        """
        INSERT INTO brain.brain_journal (ts, signal_id, regime, decision, reasoning, confidence,
                                         expected_outcome, actual_outcome, actual_pnl_pct, outcome_recorded_at)
        VALUES (now() - (%s || ' days')::interval, %s, %s, 'approve',
                'Phase 6 fixture losing trade for post-mortem cron tests.',
                7, 'Hold to ROI ladder', 'stop hit', %s,
                now() - (%s || ' days')::interval + interval '1 hour')
        RETURNING id
        """,
        (str(days_ago), signal_id, regime, pnl_pct, str(days_ago)),
    )
    journal_id = cur.fetchone()[0]
    return signal_id, journal_id


def _journal_baseline(conn: Any, regime: str, signal_type: str) -> set[tuple[str, str, str, str]]:
    """Snapshot the set of (signature) groups that already exist in the DB
    BEFORE this test inserts anything. Tests assert deltas, not absolutes,
    so they're robust to other tests' leaked rows.
    """
    return set()  # placeholder, used only for clarity; logic below uses regime/signal_type filter


@pytest.mark.integration
def test_detect_recurring_losses_finds_3plus_pattern(journal_cleanup) -> None:
    """3 losses sharing (regime, funding_bucket, vol_bucket, signal_type)
    must surface exactly 1 group with 3 entries.

    Uses uncommitted transaction visibility: the test inserts inside the
    fixture's own connection and queries via the same connection — psycopg
    sees the uncommitted writes within the same transaction. The fixture
    rolls back at the end, leaving no new DB state (Iron Law 5's trigger
    blocks UPDATE/DELETE but NOT ROLLBACK).
    """
    from infra.scripts.post_mortem_cron import detect_recurring_losses

    cur = journal_cleanup.cursor()
    # Use a synthetic regime label that no other test or production row uses,
    # to isolate from accumulated DB state.
    regime = "phase6test_finds_3"
    for d in (1, 3, 6):
        _insert_losing_signal_and_journal(
            cur,
            pair="BTC/USDT",
            signal_type="enter_long",
            regime=regime,
            funding_rate=0.0008,
            atr_pct=6.0,
            pnl_pct=-2.5,
            days_ago=d,
        )
    groups = detect_recurring_losses(journal_cleanup, since_days=14)
    matching = [g for g in groups if g.signature.regime == regime]
    assert len(matching) == 1, f"expected 1 group for regime={regime}, got {len(matching)}: {groups}"
    g = matching[0]
    assert g.signature.signal_type == "enter_long"
    assert g.signature.funding_bucket == "pos"
    assert g.signature.vol_bucket == "high"
    assert g.count == 3
    assert len(g.journal_ids) == 3


@pytest.mark.integration
def test_detect_recurring_losses_ignores_2_or_fewer(journal_cleanup) -> None:
    from infra.scripts.post_mortem_cron import detect_recurring_losses

    cur = journal_cleanup.cursor()
    regime = "phase6test_only_2"
    for d in (1, 4):
        _insert_losing_signal_and_journal(
            cur,
            pair="ETH/USDT",
            signal_type="enter_long",
            regime=regime,
            funding_rate=0.0008,
            atr_pct=6.0,
            pnl_pct=-1.8,
            days_ago=d,
        )
    groups = detect_recurring_losses(journal_cleanup, since_days=14)
    matching = [g for g in groups if g.signature.regime == regime]
    assert len(matching) == 0, (
        f"2-row signature must be filtered by HAVING count >= 3; got {matching}"
    )


@pytest.mark.integration
def test_detect_recurring_losses_ignores_winning_trades(journal_cleanup) -> None:
    from infra.scripts.post_mortem_cron import detect_recurring_losses

    cur = journal_cleanup.cursor()
    regime = "phase6test_winning"
    for d in (1, 3, 5):
        _insert_losing_signal_and_journal(
            cur,
            pair="SOL/USDT",
            signal_type="enter_long",
            regime=regime,
            funding_rate=0.0008,
            atr_pct=6.0,
            pnl_pct=+2.5,  # WIN
            days_ago=d,
        )
    groups = detect_recurring_losses(journal_cleanup, since_days=14)
    matching = [g for g in groups if g.signature.regime == regime]
    assert len(matching) == 0


def test_append_to_lessons_writes_structured_entry(tmp_path: Path) -> None:
    from infra.scripts.post_mortem_cron import (
        ClaudeResponse,
        FailureGroup,
        FailureSignature,
        append_to_lessons,
    )

    lessons_file = tmp_path / "lessons-learned.md"
    lessons_file.write_text(
        "# Lessons Learned\n\n## Purpose\nstub\n\n## Entries\n",
        encoding="utf-8",
    )
    group = FailureGroup(
        signature=FailureSignature(
            regime="trending_up",
            funding_bucket="pos",
            vol_bucket="high",
            signal_type="enter_long",
        ),
        count=3,
        journal_ids=[101, 102, 103],
        avg_pnl_pct=-2.4,
        time_spread_days=5.0,
    )
    response = ClaudeResponse(
        is_structural=True,
        suggested_known_trap_entry="VETO entries when regime=trending_up and funding>0.05% and ATR-bucket=high",
        lesson_summary="Trend-following longs in extreme positive funding tend to wick out before continuation.",
    )
    append_to_lessons(lessons_file, group, response)
    body = lessons_file.read_text(encoding="utf-8")
    assert "trending_up" in body
    assert "[101, 102, 103]" in body
    assert response.lesson_summary in body
    assert "## Entries" in body  # original section preserved


def test_append_to_known_traps_only_if_structural(tmp_path: Path) -> None:
    from infra.scripts.post_mortem_cron import (
        ClaudeResponse,
        FailureGroup,
        FailureSignature,
        append_to_known_traps,
    )

    traps_file = tmp_path / "known-traps.md"
    initial = "# Known Traps\n\n## Current entries\n\nNo entries yet.\n"
    traps_file.write_text(initial, encoding="utf-8")

    group = FailureGroup(
        signature=FailureSignature(
            regime="ranging", funding_bucket="flat", vol_bucket="low", signal_type="enter_long"
        ),
        count=3,
        journal_ids=[1, 2, 3],
        avg_pnl_pct=-1.6,
        time_spread_days=4.0,
    )
    not_structural = ClaudeResponse(
        is_structural=False,
        suggested_known_trap_entry=None,
        lesson_summary="Coincidence, not pattern.",
    )
    append_to_known_traps(traps_file, group, not_structural)
    assert traps_file.read_text(encoding="utf-8") == initial, (
        "non-structural pattern must NOT modify known-traps.md"
    )

    structural = ClaudeResponse(
        is_structural=True,
        suggested_known_trap_entry="VETO entries when regime=ranging and signal_type=enter_long",
        lesson_summary="Ranging chop kills trend-following entries.",
    )
    append_to_known_traps(traps_file, group, structural)
    body = traps_file.read_text(encoding="utf-8")
    assert "TRAP-" in body
    assert "VETO entries when regime=ranging" in body
    assert "regime=ranging" in body


def test_refresh_strategy_performance_updates_table_in_place(tmp_path: Path) -> None:
    from infra.scripts.post_mortem_cron import write_strategy_performance_table

    perf_file = tmp_path / "strategy-performance.md"
    perf_file.write_text(
        "# Strategy Performance\n\n## Per-regime metrics\n\n"
        "<!-- BEGIN perf-table -->\nold table content\n<!-- END perf-table -->\n\n"
        "## Last refresh\n\nnever\n",
        encoding="utf-8",
    )
    rows = [
        {
            "regime": "trending_up",
            "count": 12,
            "win_rate": 0.58,
            "avg_pnl_pct": 1.2,
            "profit_factor": 1.6,
            "sharpe": 1.9,
        }
    ]
    write_strategy_performance_table(perf_file, rows)
    body = perf_file.read_text(encoding="utf-8")
    assert "old table content" not in body
    assert "trending_up" in body
    assert "<!-- BEGIN perf-table -->" in body
    assert "<!-- END perf-table -->" in body
    # Last refresh must be updated to a real ISO timestamp
    assert "Last refresh" in body
    assert "never" not in body


def test_invoke_claude_pattern_detector_parses_json_response(tmp_path: Path) -> None:
    """Mock-only test: subprocess call to Claude CLI is mocked because we
    cannot reasonably exercise it in CI. Production code path remains real.
    """
    from infra.scripts.post_mortem_cron import (
        FailureGroup,
        FailureSignature,
        invoke_claude_pattern_detector,
    )

    group = FailureGroup(
        signature=FailureSignature(
            regime="trending_up", funding_bucket="pos", vol_bucket="high", signal_type="enter_long"
        ),
        count=3,
        journal_ids=[1, 2, 3],
        avg_pnl_pct=-2.0,
        time_spread_days=5.0,
    )

    fake_payload = json.dumps(
        {
            "is_structural": True,
            "suggested_known_trap_entry": "VETO ...",
            "lesson_summary": "Funding extremes warn.",
        }
    )

    class _FakeCompleted:
        def __init__(self, out: str) -> None:
            self.stdout = out
            self.stderr = ""
            self.returncode = 0

    os.environ["ANTHROPIC_API_KEY"] = "fixture-key"
    with patch("infra.scripts.post_mortem_cron.subprocess.run",
               return_value=_FakeCompleted(fake_payload)):
        resp = invoke_claude_pattern_detector(group)

    assert resp.is_structural is True
    assert resp.lesson_summary == "Funding extremes warn."


@pytest.mark.integration
def test_log_run_inserts_iteration_runs(journal_cleanup) -> None:
    from infra.scripts.post_mortem_cron import log_run

    summary = {"groups_detected": 0, "lessons_appended": 0, "test_marker": "phase6_t1"}
    new_id = log_run(journal_cleanup, run_type="post_mortem", summary=summary)
    cur = journal_cleanup.cursor()
    try:
        cur.execute(
            "SELECT run_type, summary FROM brain.iteration_runs WHERE id=%s",
            (new_id,),
        )
        row = cur.fetchone()
        assert row is not None
        assert row[0] == "post_mortem"
        assert "groups_detected" in row[1]
    finally:
        # iteration_runs has no append-only trigger (only brain_journal does);
        # safe to delete fixture rows so the test is repeatable.
        cur.execute("DELETE FROM brain.iteration_runs WHERE id=%s", (new_id,))
        journal_cleanup.commit()
