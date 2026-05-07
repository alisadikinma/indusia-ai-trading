"""GET /dashboard/journal — paginated, filterable Brain Journal view.

brain.brain_journal is append-only (Iron Law 5). This route is read-only.
"""
from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Query, Request
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


@router.get("", response_model=JournalPage)
async def list_journal(
    request: Request,
    regime: Annotated[str | None, Query()] = None,
    decision: Annotated[str | None, Query()] = None,
    from_ts: Annotated[datetime | None, Query(alias="from")] = None,
    to_ts: Annotated[datetime | None, Query(alias="to")] = None,
    q: Annotated[str | None, Query(description="Full-text search over reasoning")] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    size: Annotated[int, Query(ge=1, le=200)] = 50,
) -> JournalPage:
    pool = request.app.state.pg_pool
    where: list[str] = []
    params: list[Any] = []

    def _add(sql: str, value: Any) -> None:
        params.append(value)
        where.append(sql.replace("$?", f"${len(params)}"))

    if regime is not None:
        _add("regime = $?", regime)
    if decision is not None:
        _add("decision = $?", decision)
    if from_ts is not None:
        _add("ts >= $?", from_ts)
    if to_ts is not None:
        _add("ts <= $?", to_ts)
    if q is not None and q.strip():
        _add("reasoning_tsv @@ plainto_tsquery('english', $?)", q.strip())

    where_clause = (" WHERE " + " AND ".join(where)) if where else ""

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
