"""GET /dashboard/chart/ohlcv — OHLCV time-series for the live chart view."""
from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, ConfigDict

router = APIRouter()


class OhlcvPoint(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    ts: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float


@router.get("/ohlcv", response_model=list[OhlcvPoint])
async def get_ohlcv(
    request: Request,
    pair: Annotated[str, Query(min_length=1, max_length=32)] = "BTC/USDT",
    tf: Annotated[str, Query(min_length=1, max_length=8)] = "1m",
    from_ts: Annotated[datetime | None, Query(alias="from")] = None,
    to_ts: Annotated[datetime | None, Query(alias="to")] = None,
    limit: Annotated[int, Query(ge=1, le=5000)] = 1000,
) -> list[OhlcvPoint]:
    """Return up to `limit` OHLCV candles for `pair` / `tf` between `from`..`to`.

    Empty array if no rows match — never raises (Iron Law 3 anti-placeholder requires
    real Postgres query; empty result must come from a real 0-row query, never hardcoded).
    """
    pool = request.app.state.pg_pool
    sql = """
        SELECT ts, open, high, low, close, volume
        FROM brain.ohlcv
        WHERE pair = $1 AND tf = $2
          AND ($3::timestamptz IS NULL OR ts >= $3)
          AND ($4::timestamptz IS NULL OR ts <= $4)
        ORDER BY ts DESC
        LIMIT $5
    """
    async with pool.acquire() as conn:
        rows = await conn.fetch(sql, pair, tf, from_ts, to_ts, limit)
    # Reverse so the chart consumer gets ascending time order.
    return [
        OhlcvPoint(
            ts=r["ts"],
            open=float(r["open"]),
            high=float(r["high"]),
            low=float(r["low"]),
            close=float(r["close"]),
            volume=float(r["volume"]),
        )
        for r in reversed(rows)
    ]
