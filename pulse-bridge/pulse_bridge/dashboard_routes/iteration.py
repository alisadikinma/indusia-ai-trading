"""GET /dashboard/iteration-runs — strategic iteration loop tracking (Phase 6/9.5)."""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Request
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


@router.get("", response_model=list[IterationRun])
async def list_iteration_runs(request: Request) -> list[IterationRun]:
    pool = request.app.state.pg_pool
    sql = """
        SELECT id, started_at, completed_at, run_type, cycle_n, failure_mode,
               hypothesis, adr_ref, metrics_before, metrics_after, outcome, summary
        FROM brain.iteration_runs
        ORDER BY started_at DESC
        LIMIT 200
    """
    async with pool.acquire() as conn:
        rows = await conn.fetch(sql)
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
