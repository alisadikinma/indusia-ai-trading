"""Phase 6 — weekly post-mortem cron.

Triggered by systemd timer (Sunday 00:00 UTC). Reads recent losing trades
from brain.brain_journal, groups by failure signature, invokes Claude in
non-interactive mode to analyze (using pattern-detector.md skill), and
appends structured lessons to memory/* and (if pattern is structural)
skills/known-traps.md.

Iron Law 4 exception: this cron is the ONE automation layer permitted to
write to skills/known-traps.md. Runtime brain (oversight-loop) only reads.

Iron Law 3 (anti-placeholder):
  * Real psycopg connection (no SQLite stub).
  * Real subprocess invocation of the Claude CLI in production. The ONLY
    mock allowed is in tests/test_post_mortem_cron.py via @patch.
  * No silent env defaults — os.environ[...] raises KeyError on missing.

Usage:
  python -m infra.scripts.post_mortem_cron

Exit codes:
  0: success (including the empty-state "no recurring losses" path).
  1: any failure during the cycle.
"""
from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger("post_mortem_cron")


REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SKILLS_DIR = REPO_ROOT / "crypto-bot" / "claude-routines" / "skills"
MEMORY_DIR = REPO_ROOT / "crypto-bot" / "claude-routines" / "memory"
LESSONS_FILE = MEMORY_DIR / "lessons-learned.md"
PERF_FILE = MEMORY_DIR / "strategy-performance.md"
HISTORY_FILE = MEMORY_DIR / "recent-regime-history.md"
KNOWN_TRAPS_FILE = SKILLS_DIR / "known-traps.md"
PATTERN_DETECTOR_SKILL = SKILLS_DIR / "pattern-detector.md"
POST_MORTEM_SKILL = SKILLS_DIR / "post-mortem-protocol.md"

# Bucketing thresholds (per known-traps.md §How this file grows).
FUNDING_NEG_THRESHOLD = -0.0005   # -0.05%
FUNDING_POS_THRESHOLD = 0.0005    # +0.05%
VOL_LOW_PCT = 2.0                 # ATR(14) % below 2 = low
VOL_HIGH_PCT = 5.0                # ATR(14) % above 5 = high


@dataclass(frozen=True)
class FailureSignature:
    regime: str
    funding_bucket: str   # 'neg' | 'flat' | 'pos'
    vol_bucket: str       # 'low' | 'mid' | 'high'
    signal_type: str


@dataclass
class FailureGroup:
    signature: FailureSignature
    count: int
    journal_ids: list[int]
    avg_pnl_pct: float
    time_spread_days: float


@dataclass
class ClaudeResponse:
    is_structural: bool
    suggested_known_trap_entry: str | None
    lesson_summary: str


# ---------------------------------------------------------------------------
# Postgres connection
# ---------------------------------------------------------------------------
def _postgres_dsn() -> str:
    """Build DSN from required env. Hard-fail (KeyError) if any var missing."""
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
# Query: detect_recurring_losses
# ---------------------------------------------------------------------------
_DETECT_SQL = """
WITH losses AS (
    SELECT
        j.id              AS journal_id,
        j.regime,
        j.actual_pnl_pct,
        j.ts,
        s.signal_type,
        COALESCE((s.indicators->>'funding_rate')::numeric, 0)::numeric AS funding_rate,
        COALESCE((s.indicators->>'atr_pct')::numeric, 0)::numeric      AS atr_pct,
        CASE
            WHEN COALESCE((s.indicators->>'funding_rate')::numeric, 0) < %(fn)s THEN 'neg'
            WHEN COALESCE((s.indicators->>'funding_rate')::numeric, 0) > %(fp)s THEN 'pos'
            ELSE 'flat'
        END AS funding_bucket,
        CASE
            WHEN COALESCE((s.indicators->>'atr_pct')::numeric, 0) < %(vl)s THEN 'low'
            WHEN COALESCE((s.indicators->>'atr_pct')::numeric, 0) > %(vh)s THEN 'high'
            ELSE 'mid'
        END AS vol_bucket
    FROM brain.brain_journal j
    LEFT JOIN brain.signals s ON s.id = j.signal_id
    WHERE j.actual_pnl_pct IS NOT NULL
      AND j.actual_pnl_pct < -1.0
      AND j.ts >= now() - (%(days)s || ' days')::interval
      AND s.signal_type IS NOT NULL
)
SELECT
    regime,
    funding_bucket,
    vol_bucket,
    signal_type,
    COUNT(*)::int                      AS cnt,
    AVG(actual_pnl_pct)::float         AS avg_pnl,
    EXTRACT(EPOCH FROM (MAX(ts) - MIN(ts))) / 86400.0 AS spread_days,
    ARRAY_AGG(journal_id ORDER BY ts)  AS ids
FROM losses
GROUP BY regime, funding_bucket, vol_bucket, signal_type
HAVING COUNT(*) >= 3
ORDER BY cnt DESC;
"""


def detect_recurring_losses(conn: Any, since_days: int = 7) -> list[FailureGroup]:
    """Group recent losing trades by failure signature.

    Returns one FailureGroup per signature where >= 3 losses occurred in the
    window. Pure SQL — no Claude call. Empty journal returns []."""
    params = {
        "fn": FUNDING_NEG_THRESHOLD,
        "fp": FUNDING_POS_THRESHOLD,
        "vl": VOL_LOW_PCT,
        "vh": VOL_HIGH_PCT,
        "days": str(since_days),
    }
    with conn.cursor() as cur:
        cur.execute(_DETECT_SQL, params)
        rows = cur.fetchall()
    out: list[FailureGroup] = []
    for regime, fb, vb, st, cnt, avg_pnl, spread, ids in rows:
        out.append(
            FailureGroup(
                signature=FailureSignature(
                    regime=regime,
                    funding_bucket=fb,
                    vol_bucket=vb,
                    signal_type=st,
                ),
                count=int(cnt),
                journal_ids=[int(i) for i in ids],
                avg_pnl_pct=float(avg_pnl),
                time_spread_days=float(spread or 0.0),
            )
        )
    return out


# ---------------------------------------------------------------------------
# Claude CLI invocation
# ---------------------------------------------------------------------------
def invoke_claude_pattern_detector(group: FailureGroup) -> ClaudeResponse:
    """Shell out to the Claude CLI with pattern-detector + post-mortem-protocol skills.

    Hard-fails on subprocess error or malformed JSON response. ANTHROPIC_API_KEY
    must be set in env (Claude CLI reads it).
    """
    # Hard-fail on missing API key.
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise RuntimeError(
            "ANTHROPIC_API_KEY missing from env — Claude CLI cannot authenticate."
        )

    prompt = (
        "You are running the post-mortem pattern-detector skill. Given the "
        "FailureGroup JSON below, decide whether this is a structural pattern "
        "worth adding to known-traps.md per the Decision rules. Respond with "
        "ONE valid JSON object matching the schema in pattern-detector.md "
        "Output format. No prose outside the JSON.\n\n"
        f"FailureGroup: {json.dumps(asdict(group), default=str)}"
    )

    cmd = [
        "claude",
        "-p",
        "--append-system-prompt-file", str(PATTERN_DETECTOR_SKILL),
        "--append-system-prompt-file", str(POST_MORTEM_SKILL),
        prompt,
    ]
    try:
        completed = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
    except FileNotFoundError as exc:
        raise RuntimeError(
            "Claude CLI binary 'claude' not on PATH — install per "
            "https://docs.anthropic.com/en/docs/claude-code/cli-reference"
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("Claude CLI timed out after 120s") from exc

    if completed.returncode != 0:
        raise RuntimeError(
            f"Claude CLI returned non-zero exit {completed.returncode}: "
            f"stderr={completed.stderr.strip()[:500]}"
        )

    raw = completed.stdout.strip()
    # Tolerate the model wrapping JSON in code fences.
    if raw.startswith("```"):
        raw = re.sub(r"^```[a-zA-Z0-9]*\n?", "", raw)
        raw = re.sub(r"\n?```$", "", raw)

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"Claude CLI returned malformed JSON: {raw[:300]!r}"
        ) from exc

    try:
        return ClaudeResponse(
            is_structural=bool(parsed["is_structural"]),
            suggested_known_trap_entry=parsed.get("suggested_known_trap_entry"),
            lesson_summary=str(parsed["lesson_summary"]),
        )
    except KeyError as exc:
        raise RuntimeError(
            f"Claude CLI JSON missing required field: {exc}"
        ) from exc


# ---------------------------------------------------------------------------
# File writers
# ---------------------------------------------------------------------------
def append_to_lessons(
    lessons_file: Path,
    group: FailureGroup,
    response: ClaudeResponse,
) -> None:
    """Append one structured entry to lessons-learned.md (always)."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    sig = group.signature
    cause_tag = (
        sig.regime
        + "/"
        + sig.signal_type
    )
    entry = (
        f"\n### {today} — {sig.regime} — {cause_tag}\n"
        f"Trades: brain_journal ids {group.journal_ids}\n"
        f"Signature: regime={sig.regime}, funding_bucket={sig.funding_bucket}, "
        f"vol_bucket={sig.vol_bucket}, signal_type={sig.signal_type}\n"
        f"Sample count: {group.count} (avg pnl {group.avg_pnl_pct:.2f}%, "
        f"spread {group.time_spread_days:.1f}d)\n"
        f"Lesson: {response.lesson_summary}\n"
    )
    with lessons_file.open("a", encoding="utf-8") as fh:
        fh.write(entry)


def append_to_known_traps(
    traps_file: Path,
    group: FailureGroup,
    response: ClaudeResponse,
) -> None:
    """Append a TRAP-NNN entry IFF claude_response.is_structural is True."""
    if not response.is_structural:
        logger.info(
            "pattern not structural — skipping known-traps append for %s",
            group.signature,
        )
        return

    body = traps_file.read_text(encoding="utf-8")
    # Find next TRAP-NNN by scanning existing entries.
    existing = re.findall(r"TRAP-(\d+)", body)
    next_n = max((int(x) for x in existing), default=0) + 1

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    sig = group.signature
    veto_rule = response.suggested_known_trap_entry or (
        f"VETO entries when regime={sig.regime} and funding_bucket={sig.funding_bucket} "
        f"and vol_bucket={sig.vol_bucket} and signal_type={sig.signal_type}"
    )
    entry = (
        f"\n### TRAP-{next_n:03d} (added {today})\n"
        f"- signature: regime={sig.regime}, funding_bucket={sig.funding_bucket}, "
        f"vol_bucket={sig.vol_bucket}, signal_type={sig.signal_type}\n"
        f"- sample_count: {group.count}\n"
        f"- mean_loss_pct: {group.avg_pnl_pct:.2f}\n"
        f"- veto_rule: {veto_rule}\n"
        f"- first_seen_journal_id: {group.journal_ids[0]}\n"
    )
    with traps_file.open("a", encoding="utf-8") as fh:
        fh.write(entry)


# ---------------------------------------------------------------------------
# Strategy performance table
# ---------------------------------------------------------------------------
_PERF_BEGIN = "<!-- BEGIN perf-table -->"
_PERF_END = "<!-- END perf-table -->"


def write_strategy_performance_table(perf_file: Path, rows: list[dict[str, Any]]) -> None:
    """Replace the per-regime metrics table inside the BEGIN/END markers.

    Rows: [{regime, count, win_rate, avg_pnl_pct, profit_factor, sharpe}, ...]
    Also updates the '## Last refresh' section ISO timestamp. Idempotent.
    """
    body = perf_file.read_text(encoding="utf-8")

    table_lines = [
        "| regime | count | win_rate | avg_pnl_pct | profit_factor | sharpe |",
        "|---|---|---|---|---|---|",
    ]
    if not rows:
        table_lines.append("| (no data) | 0 | - | - | - | - |")
    for r in rows:
        table_lines.append(
            f"| {r['regime']} | {r['count']} | {r['win_rate']:.2%} | "
            f"{r['avg_pnl_pct']:+.2f}% | {r['profit_factor']:.2f} | {r['sharpe']:.2f} |"
        )
    new_block = (
        f"{_PERF_BEGIN}\n" + "\n".join(table_lines) + f"\n{_PERF_END}"
    )

    pattern = re.compile(
        re.escape(_PERF_BEGIN) + r".*?" + re.escape(_PERF_END),
        re.DOTALL,
    )
    if pattern.search(body):
        body = pattern.sub(new_block, body)
    else:
        # File missing markers — append them under the header.
        body = body.rstrip() + "\n\n" + new_block + "\n"

    # Update Last refresh timestamp.
    iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    refresh_pattern = re.compile(r"(## Last refresh\s*\n+)([^\n]*)", re.MULTILINE)
    if refresh_pattern.search(body):
        body = refresh_pattern.sub(rf"\g<1>{iso}", body)
    else:
        body = body.rstrip() + f"\n\n## Last refresh\n\n{iso}\n"

    perf_file.write_text(body, encoding="utf-8")


def refresh_strategy_performance(conn: Any) -> list[dict[str, Any]]:
    """Recompute per-regime stats from brain.brain_journal + write to file."""
    sql = """
        SELECT
            regime,
            COUNT(*)::int                                                AS cnt,
            AVG(CASE WHEN actual_pnl_pct > 0 THEN 1.0 ELSE 0.0 END)::float AS win_rate,
            AVG(actual_pnl_pct)::float                                   AS avg_pnl,
            CASE
                WHEN SUM(CASE WHEN actual_pnl_pct < 0 THEN -actual_pnl_pct ELSE 0 END) = 0
                THEN 0.0
                ELSE (
                    SUM(CASE WHEN actual_pnl_pct > 0 THEN actual_pnl_pct ELSE 0 END)::float
                    / SUM(CASE WHEN actual_pnl_pct < 0 THEN -actual_pnl_pct ELSE 0 END)::float
                )
            END                                                          AS pf,
            CASE
                WHEN STDDEV_SAMP(actual_pnl_pct) IS NULL OR STDDEV_SAMP(actual_pnl_pct) = 0
                THEN 0.0
                ELSE (AVG(actual_pnl_pct) / STDDEV_SAMP(actual_pnl_pct))::float
            END                                                          AS sharpe
        FROM brain.brain_journal
        WHERE actual_pnl_pct IS NOT NULL
          AND ts >= now() - interval '90 days'
        GROUP BY regime
        ORDER BY cnt DESC;
    """
    rows: list[dict[str, Any]] = []
    with conn.cursor() as cur:
        cur.execute(sql)
        for regime, cnt, win_rate, avg_pnl, pf, sharpe in cur.fetchall():
            rows.append(
                {
                    "regime": regime,
                    "count": int(cnt),
                    "win_rate": float(win_rate or 0.0),
                    "avg_pnl_pct": float(avg_pnl or 0.0),
                    "profit_factor": float(pf or 0.0),
                    "sharpe": float(sharpe or 0.0),
                }
            )
    write_strategy_performance_table(PERF_FILE, rows)
    return rows


# ---------------------------------------------------------------------------
# Regime history compaction
# ---------------------------------------------------------------------------
_DATE_RE = re.compile(r"^\s*-\s*(\d{4}-\d{2}-\d{2})")


def compact_regime_history(history_file: Path = HISTORY_FILE, max_age_days: int = 30) -> int:
    """Drop list-item entries dated older than max_age_days. Returns count dropped.

    Reads each line; if it matches '- YYYY-MM-DD ...' and date < cutoff, drops it.
    All other lines (headings, prose) preserved. Idempotent.
    """
    if not history_file.exists():
        return 0
    body = history_file.read_text(encoding="utf-8")
    cutoff = datetime.now(timezone.utc).date()
    cutoff_ord = cutoff.toordinal() - max_age_days

    kept: list[str] = []
    dropped = 0
    for line in body.splitlines():
        m = _DATE_RE.match(line)
        if m:
            try:
                d = datetime.strptime(m.group(1), "%Y-%m-%d").date()
                if d.toordinal() < cutoff_ord:
                    dropped += 1
                    continue
            except ValueError:
                pass
        kept.append(line)
    if dropped:
        history_file.write_text("\n".join(kept) + "\n", encoding="utf-8")
    return dropped


# ---------------------------------------------------------------------------
# iteration_runs logging
# ---------------------------------------------------------------------------
def log_run(conn: Any, run_type: str, summary: dict[str, Any]) -> int:
    """Insert one row into brain.iteration_runs. Returns the new id."""
    sql = """
        INSERT INTO brain.iteration_runs (started_at, completed_at, run_type, summary, outcome)
        VALUES (now(), now(), %s, %s, 'PASS')
        RETURNING id
    """
    summary_text = json.dumps(summary, default=str)
    with conn.cursor() as cur:
        cur.execute(sql, (run_type, summary_text))
        new_id = int(cur.fetchone()[0])
    conn.commit()
    return new_id


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    # Sanity: required env loaded eagerly so we fail fast.
    _postgres_dsn()  # raises on missing
    if not os.environ.get("ANTHROPIC_API_KEY"):
        # Allow empty-state success path: only required when we'd actually call Claude.
        logger.warning("ANTHROPIC_API_KEY not set — will hard-fail if a pattern is detected.")

    summary: dict[str, Any] = {
        "groups_detected": 0,
        "lessons_appended": 0,
        "traps_appended": 0,
        "regime_rows_dropped": 0,
        "perf_rows": 0,
    }
    try:
        with _connect() as conn:
            groups = detect_recurring_losses(conn, since_days=7)
            summary["groups_detected"] = len(groups)
            if not groups:
                logger.info("no recurring losses detected in the last 7 days")

            for group in groups:
                logger.info(
                    "analysing group regime=%s sig=%s count=%d",
                    group.signature.regime, group.signature, group.count,
                )
                response = invoke_claude_pattern_detector(group)
                append_to_lessons(LESSONS_FILE, group, response)
                summary["lessons_appended"] += 1
                if response.is_structural:
                    append_to_known_traps(KNOWN_TRAPS_FILE, group, response)
                    summary["traps_appended"] += 1

            perf_rows = refresh_strategy_performance(conn)
            summary["perf_rows"] = len(perf_rows)

            dropped = compact_regime_history()
            summary["regime_rows_dropped"] = dropped

            log_run(conn, run_type="post_mortem", summary=summary)
    except Exception as exc:
        logger.exception("post_mortem_cron failed: %s", exc)
        return 1

    logger.info("post_mortem_cron complete: %s", summary)
    return 0


if __name__ == "__main__":
    sys.exit(main())
