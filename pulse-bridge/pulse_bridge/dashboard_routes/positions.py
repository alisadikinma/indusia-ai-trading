"""GET /dashboard/positions — currently-open positions view.

Phase 1.5.B/C scope: source signals where Claude approved (or resized) but no
outcome has been recorded yet. These represent pending/working positions until
Phase 3 wires the public.trades table (Freqtrade-owned). When that lands, this
same query will LEFT JOIN public.trades to attach fill price / unrealized PnL —
see comment below.
"""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Request
from pydantic import BaseModel

router = APIRouter()


class Position(BaseModel):
    signal_id: int
    pair: str
    side: str  # 'long' | 'short'
    decided_at: datetime
    intended_size_mult: float | None
    price_at_signal: float


# Phase 3 enhancement: LEFT JOIN public.trades t ON t.signal_id = s.id and surface
#   t.amount, t.open_rate, t.current_profit, t.is_open  — until then, signals-only.
_SQL = """
    SELECT id AS signal_id,
           pair,
           CASE WHEN signal_type IN ('enter_long', 'exit_short') THEN 'long'
                WHEN signal_type IN ('enter_short', 'exit_long') THEN 'short'
                ELSE 'unknown' END AS side,
           COALESCE(claude_decided_at, ts) AS decided_at,
           claude_size_mult AS intended_size_mult,
           price_at_signal
    FROM brain.signals
    WHERE claude_decision IN ('approve', 'resize')
      AND signal_type IN ('enter_long', 'enter_short')
      AND trade_id IS NULL  -- not yet linked to a closed trade outcome
    ORDER BY decided_at DESC
    LIMIT 100
"""


@router.get("", response_model=list[Position])
async def list_positions(request: Request) -> list[Position]:
    pool = request.app.state.pg_pool
    async with pool.acquire() as conn:
        rows = await conn.fetch(_SQL)
    return [
        Position(
            signal_id=r["signal_id"],
            pair=r["pair"],
            side=r["side"],
            decided_at=r["decided_at"],
            intended_size_mult=float(r["intended_size_mult"]) if r["intended_size_mult"] is not None else None,
            price_at_signal=float(r["price_at_signal"]),
        )
        for r in rows
    ]
