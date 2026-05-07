"""GET /dashboard/backtest/runs and /dashboard/backtest/runs/{id}.

List view returns metadata only (no equity_curve / trades JSONB — those can be huge).
Detail view returns the full row including the embedded JSON blobs.
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

router = APIRouter()


class BacktestRunMeta(BaseModel):
    id: int
    started_at: datetime
    completed_at: datetime | None
    strategy_version: str
    fold_index: int
    train_start: datetime
    train_end: datetime
    test_start: datetime
    test_end: datetime
    metrics: dict[str, Any]
    gate_passed: bool
    notes: str | None


class BacktestRunDetail(BacktestRunMeta):
    parameters: dict[str, Any]
    equity_curve: Any | None
    trades: Any | None


def _coerce_json(val: Any) -> Any:
    if val is None:
        return None
    if isinstance(val, (dict, list)):
        return val
    if isinstance(val, (bytes, bytearray)):
        return json.loads(val.decode("utf-8"))
    if isinstance(val, str):
        return json.loads(val)
    return val


@router.get("/runs", response_model=list[BacktestRunMeta])
async def list_runs(request: Request) -> list[BacktestRunMeta]:
    pool = request.app.state.pg_pool
    sql = """
        SELECT id, started_at, completed_at, strategy_version, fold_index,
               train_start, train_end, test_start, test_end,
               metrics, gate_passed, notes
        FROM brain.backtest_runs
        ORDER BY started_at DESC
        LIMIT 200
    """
    async with pool.acquire() as conn:
        rows = await conn.fetch(sql)
    return [
        BacktestRunMeta(
            id=r["id"],
            started_at=r["started_at"],
            completed_at=r["completed_at"],
            strategy_version=r["strategy_version"],
            fold_index=r["fold_index"],
            train_start=r["train_start"],
            train_end=r["train_end"],
            test_start=r["test_start"],
            test_end=r["test_end"],
            metrics=_coerce_json(r["metrics"]) or {},
            gate_passed=r["gate_passed"],
            notes=r["notes"],
        )
        for r in rows
    ]


@router.get("/runs/{run_id}", response_model=BacktestRunDetail)
async def get_run(run_id: int, request: Request) -> BacktestRunDetail:
    pool = request.app.state.pg_pool
    sql = """
        SELECT id, started_at, completed_at, strategy_version, fold_index,
               train_start, train_end, test_start, test_end,
               parameters, metrics, equity_curve, trades, gate_passed, notes
        FROM brain.backtest_runs
        WHERE id = $1
    """
    async with pool.acquire() as conn:
        row = await conn.fetchrow(sql, run_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"backtest_run id={run_id} not found")
    return BacktestRunDetail(
        id=row["id"],
        started_at=row["started_at"],
        completed_at=row["completed_at"],
        strategy_version=row["strategy_version"],
        fold_index=row["fold_index"],
        train_start=row["train_start"],
        train_end=row["train_end"],
        test_start=row["test_start"],
        test_end=row["test_end"],
        parameters=_coerce_json(row["parameters"]) or {},
        metrics=_coerce_json(row["metrics"]) or {},
        equity_curve=_coerce_json(row["equity_curve"]),
        trades=_coerce_json(row["trades"]),
        gate_passed=row["gate_passed"],
        notes=row["notes"],
    )
