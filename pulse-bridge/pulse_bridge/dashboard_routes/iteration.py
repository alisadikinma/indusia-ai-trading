"""GET /dashboard/iteration-runs — strategic iteration loop tracking (Phase 6/9.5)."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

router = APIRouter()


class IterationRun(BaseModel):
    id: int
    started_at: datetime
    completed_at: datetime | None
    run_type: str
    cycle_n: int | None
    failure_mode: str | None
    hypothesis: str | None
    adr_ref: str | None
    metrics_before: dict[str, Any] | None
    metrics_after: dict[str, Any] | None
    outcome: str | None
    summary: str | None


def _j(v: Any) -> Any:
    if v is None or isinstance(v, (dict, list)):
        return v
    if isinstance(v, (bytes, bytearray)):
        return json.loads(v.decode("utf-8"))
    if isinstance(v, str):
        return json.loads(v)
    return v


def _parse_ts(value: str, param_name: str) -> datetime:
    """Parse *value* as an ISO-8601 timestamp into a tz-aware ``datetime``.

    Raises HTTP 400 (not a silent skip) if malformed — Iron Law 3.

    The frontend's ``<input type="datetime-local">`` emits tz-naive strings
    like ``"2026-05-07T08:00"``. asyncpg passes a tz-naive ``datetime`` to a
    ``TIMESTAMPTZ`` column where Postgres interprets it via the session's
    ``TimeZone`` setting — which is operator-controlled and not guaranteed.
    To eliminate that latent timezone bug we normalise tz-naive input to UTC.
    """
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid ISO-8601 timestamp for '{param_name}': {value!r}",
        )
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


@router.get("", response_model=list[IterationRun])
async def list_iteration_runs(
    request: Request,
    from_: str | None = Query(None, alias="from"),
    to: str | None = None,
    outcome: str | None = None,        # CSV → IN list
    failure_mode: str | None = None,   # CSV → IN list
    run_type: str | None = None,       # CSV → IN list
) -> list[IterationRun]:
    pool = request.app.state.pg_pool

    # Parse + validate timestamps once. _parse_ts raises 400 on malformed input
    # (Iron Law 3) and normalises tz-naive datetime-local input to UTC.
    from_dt = _parse_ts(from_, "from") if from_ else None
    to_dt = _parse_ts(to, "to") if to else None

    sql_parts = [
        """
        SELECT id, started_at, completed_at, run_type, cycle_n, failure_mode,
               hypothesis, adr_ref, metrics_before, metrics_after, outcome, summary
        FROM brain.iteration_runs
        WHERE 1=1
        """
    ]
    args: list[Any] = []

    if from_dt is not None:
        sql_parts.append(f"AND started_at >= ${len(args) + 1}")
        args.append(from_dt)
    if to_dt is not None:
        sql_parts.append(f"AND started_at <= ${len(args) + 1}")
        args.append(to_dt)
    if outcome:
        values = [v.strip() for v in outcome.split(",") if v.strip()]
        if values:
            placeholders = ",".join(f"${len(args) + i + 1}" for i in range(len(values)))
            sql_parts.append(f"AND outcome IN ({placeholders})")
            args.extend(values)
    if failure_mode:
        values = [v.strip() for v in failure_mode.split(",") if v.strip()]
        if values:
            placeholders = ",".join(f"${len(args) + i + 1}" for i in range(len(values)))
            sql_parts.append(f"AND failure_mode IN ({placeholders})")
            args.extend(values)
    if run_type:
        values = [v.strip() for v in run_type.split(",") if v.strip()]
        if values:
            placeholders = ",".join(f"${len(args) + i + 1}" for i in range(len(values)))
            sql_parts.append(f"AND run_type IN ({placeholders})")
            args.extend(values)

    sql_parts.append("ORDER BY started_at DESC LIMIT 200")
    sql = " ".join(sql_parts)

    async with pool.acquire() as conn:
        rows = await conn.fetch(sql, *args)
    return [
        IterationRun(
            id=r["id"],
            started_at=r["started_at"],
            completed_at=r["completed_at"],
            run_type=r["run_type"],
            cycle_n=r["cycle_n"],
            failure_mode=r["failure_mode"],
            hypothesis=r["hypothesis"],
            adr_ref=r["adr_ref"],
            metrics_before=_j(r["metrics_before"]),
            metrics_after=_j(r["metrics_after"]),
            outcome=r["outcome"],
            summary=r["summary"],
        )
        for r in rows
    ]
