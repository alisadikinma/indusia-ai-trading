"""GET /dashboard/journal — paginated, filterable Brain Journal view.

Plus /dashboard/journal/export.csv — RFC 4180 CSV export of the same
filtered set, used by the Phase 1.5.F UI Export button.

brain.brain_journal is append-only (Iron Law 5). Both routes are read-only.
"""
from __future__ import annotations

import csv
import io
from datetime import datetime, timezone
from typing import Annotated, Any

from fastapi import APIRouter, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

router = APIRouter()


class JournalEntry(BaseModel):
    id: int
    ts: datetime
    signal_id: int | None
    regime: str
    decision: str
    reasoning: str
    confidence: int | None
    expected_outcome: str | None
    actual_outcome: str | None
    actual_pnl_pct: float | None
    outcome_recorded_at: datetime | None


class JournalPage(BaseModel):
    items: list[JournalEntry]
    total: int
    page: int
    size: int


def _split_multi(value: str | None) -> list[str]:
    """Comma-separated multi-value filter parsing.

    "trending_up,ranging" -> ["trending_up", "ranging"]
    "" or None -> []
    Trims whitespace, drops empties.
    """
    if value is None:
        return []
    parts = [p.strip() for p in value.split(",")]
    return [p for p in parts if p]


def _build_where(
    *,
    regime: str | None,
    decision: str | None,
    outcome: str | None,
    from_ts: datetime | None,
    to_ts: datetime | None,
    q: str | None,
) -> tuple[str, list[Any]]:
    """Build a parameterized WHERE clause for journal filters.

    Returns (sql_fragment_with_leading_space, params).
    sql_fragment is "" or " WHERE ...".

    `outcome` accepted values:
      - 'win', 'loss', 'open' (single)
      - 'win,loss' multi-value
      - 'open' maps to actual_outcome IS NULL
      - any other literal maps to actual_outcome = $n
    """
    where: list[str] = []
    params: list[Any] = []

    regimes = _split_multi(regime)
    if regimes:
        params.extend(regimes)
        # Build $n,$n+1,...
        placeholders = ",".join(f"${i}" for i in range(len(params) - len(regimes) + 1, len(params) + 1))
        where.append(f"regime IN ({placeholders})")

    decisions = _split_multi(decision)
    if decisions:
        params.extend(decisions)
        placeholders = ",".join(
            f"${i}" for i in range(len(params) - len(decisions) + 1, len(params) + 1)
        )
        where.append(f"decision IN ({placeholders})")

    outcomes = _split_multi(outcome)
    if outcomes:
        wants_open = "open" in outcomes
        concrete = [o for o in outcomes if o != "open"]
        outcome_fragments: list[str] = []
        if wants_open:
            outcome_fragments.append("actual_outcome IS NULL")
        if concrete:
            params.extend(concrete)
            placeholders = ",".join(
                f"${i}" for i in range(len(params) - len(concrete) + 1, len(params) + 1)
            )
            outcome_fragments.append(f"actual_outcome IN ({placeholders})")
        where.append("(" + " OR ".join(outcome_fragments) + ")")

    if from_ts is not None:
        params.append(from_ts)
        where.append(f"ts >= {_next_back(params)}")
    if to_ts is not None:
        params.append(to_ts)
        where.append(f"ts <= {_next_back(params)}")
    if q is not None and q.strip():
        params.append(q.strip())
        where.append(f"reasoning_tsv @@ plainto_tsquery('english', {_next_back(params)})")

    where_clause = (" WHERE " + " AND ".join(where)) if where else ""
    return where_clause, params


def _next_back(params: list[Any]) -> str:
    """Placeholder for the most recently appended param (1-indexed)."""
    return f"${len(params)}"


@router.get("", response_model=JournalPage)
async def list_journal(
    request: Request,
    regime: Annotated[
        str | None,
        Query(description="Regime filter; comma-separated for multi-value (e.g. 'trending_up,ranging')."),
    ] = None,
    decision: Annotated[
        str | None,
        Query(description="Decision filter; comma-separated for multi-value (approve,veto,resize,halt,no_action)."),
    ] = None,
    outcome: Annotated[
        str | None,
        Query(description="actual_outcome filter; 'open' matches NULL. Comma-separated for multi-value."),
    ] = None,
    from_ts: Annotated[datetime | None, Query(alias="from")] = None,
    to_ts: Annotated[datetime | None, Query(alias="to")] = None,
    q: Annotated[str | None, Query(description="Full-text search over reasoning")] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    size: Annotated[int, Query(ge=1, le=200)] = 50,
) -> JournalPage:
    pool = request.app.state.pg_pool
    where_clause, params = _build_where(
        regime=regime,
        decision=decision,
        outcome=outcome,
        from_ts=from_ts,
        to_ts=to_ts,
        q=q,
    )

    count_sql = f"SELECT count(*) FROM brain.brain_journal{where_clause}"
    rows_sql = (
        "SELECT id, ts, signal_id, regime, decision, reasoning, confidence, "
        "expected_outcome, actual_outcome, actual_pnl_pct, outcome_recorded_at "
        f"FROM brain.brain_journal{where_clause} "
        f"ORDER BY ts DESC LIMIT ${len(params) + 1} OFFSET ${len(params) + 2}"
    )
    offset = (page - 1) * size

    async with pool.acquire() as conn:
        total = await conn.fetchval(count_sql, *params)
        rows = await conn.fetch(rows_sql, *params, size, offset)

    items = [
        JournalEntry(
            id=r["id"],
            ts=r["ts"],
            signal_id=r["signal_id"],
            regime=r["regime"],
            decision=r["decision"],
            reasoning=r["reasoning"],
            confidence=r["confidence"],
            expected_outcome=r["expected_outcome"],
            actual_outcome=r["actual_outcome"],
            actual_pnl_pct=float(r["actual_pnl_pct"]) if r["actual_pnl_pct"] is not None else None,
            outcome_recorded_at=r["outcome_recorded_at"],
        )
        for r in rows
    ]
    return JournalPage(items=items, total=int(total or 0), page=page, size=size)


# ---------------------------------------------------------------------------
# CSV export — same filter contract as GET /, no pagination (caps at 50_000).
# ---------------------------------------------------------------------------

# Hard cap: refuse to materialize more than this many rows in a single export
# to avoid runaway memory/streaming if an operator forgets a filter.
_CSV_HARD_CAP = 50_000

_CSV_COLUMNS = (
    "id",
    "ts",
    "signal_id",
    "regime",
    "decision",
    "confidence",
    "reasoning",
    "expected_outcome",
    "actual_outcome",
    "actual_pnl_pct",
    "outcome_recorded_at",
)


@router.get("/export.csv")
async def export_journal_csv(
    request: Request,
    regime: Annotated[str | None, Query()] = None,
    decision: Annotated[str | None, Query()] = None,
    outcome: Annotated[str | None, Query()] = None,
    from_ts: Annotated[datetime | None, Query(alias="from")] = None,
    to_ts: Annotated[datetime | None, Query(alias="to")] = None,
    q: Annotated[str | None, Query()] = None,
) -> StreamingResponse:
    pool = request.app.state.pg_pool
    where_clause, params = _build_where(
        regime=regime,
        decision=decision,
        outcome=outcome,
        from_ts=from_ts,
        to_ts=to_ts,
        q=q,
    )

    rows_sql = (
        "SELECT id, ts, signal_id, regime, decision, confidence, reasoning, "
        "expected_outcome, actual_outcome, actual_pnl_pct, outcome_recorded_at "
        f"FROM brain.brain_journal{where_clause} "
        f"ORDER BY ts DESC LIMIT {_CSV_HARD_CAP}"
    )

    async with pool.acquire() as conn:
        rows = await conn.fetch(rows_sql, *params)

    buf = io.StringIO()
    # csv.writer with default dialect = RFC 4180-compatible:
    # - delimiter ','
    # - quotechar '"' with internal " doubled
    # - lineterminator '\r\n'
    writer = csv.writer(buf, quoting=csv.QUOTE_MINIMAL, lineterminator="\r\n")
    writer.writerow(_CSV_COLUMNS)
    for r in rows:
        writer.writerow(
            [
                r["id"],
                r["ts"].isoformat() if r["ts"] is not None else "",
                r["signal_id"] if r["signal_id"] is not None else "",
                r["regime"] or "",
                r["decision"] or "",
                r["confidence"] if r["confidence"] is not None else "",
                r["reasoning"] or "",
                r["expected_outcome"] or "",
                r["actual_outcome"] or "",
                str(r["actual_pnl_pct"]) if r["actual_pnl_pct"] is not None else "",
                r["outcome_recorded_at"].isoformat() if r["outcome_recorded_at"] is not None else "",
            ]
        )

    payload = buf.getvalue().encode("utf-8")
    # Timestamp in filename so multiple filtered exports per session don't
    # collide on download (operator habit during post-mortem deep-dives).
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    content_disposition = f'attachment; filename="brain_journal_{ts}.csv"'
    return StreamingResponse(
        iter([payload]),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": content_disposition,
        },
    )
