"""GET /dashboard/equity — equity-curve time-series."""
from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel

router = APIRouter()


class EquityPoint(BaseModel):
    ts: datetime
    equity_usd: float
    realized_pnl: float
    unrealized_pnl: float
    open_positions: int
    drawdown_pct: float


@router.get("", response_model=list[EquityPoint])
async def get_equity(
    request: Request,
    from_ts: Annotated[datetime | None, Query(alias="from")] = None,
    to_ts: Annotated[datetime | None, Query(alias="to")] = None,
    limit: Annotated[int, Query(ge=1, le=10000)] = 5000,
) -> list[EquityPoint]:
    pool = request.app.state.pg_pool
    sql = """
        SELECT ts, equity_usd, realized_pnl, unrealized_pnl, open_positions, drawdown_pct
        FROM brain.equity_curve
        WHERE ($1::timestamptz IS NULL OR ts >= $1)
          AND ($2::timestamptz IS NULL OR ts <= $2)
        ORDER BY ts ASC
        LIMIT $3
    """
    async with pool.acquire() as conn:
        rows = await conn.fetch(sql, from_ts, to_ts, limit)
    return [
        EquityPoint(
            ts=r["ts"],
            equity_usd=float(r["equity_usd"]),
            realized_pnl=float(r["realized_pnl"]),
            unrealized_pnl=float(r["unrealized_pnl"]),
            open_positions=int(r["open_positions"]),
            drawdown_pct=float(r["drawdown_pct"]),
        )
        for r in rows
    ]
