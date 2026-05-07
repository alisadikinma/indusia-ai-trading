"""GET /dashboard/risk/state — current risk-rail state.

circuit_breaker_state mapping:
  green  — drawdown < 10% (or no equity rows yet)
  amber  — 10% <= drawdown < 18%
  red    — drawdown >= 18% (approaching the 20% MaxDD kill-switch in Iron Law 1)

Phase 11 adds an authoritative protection-state file written by the Freqtrade
process; when that lands, this endpoint should read that file and override the
heuristic above. For now, derive purely from brain.equity_curve.
"""
from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel

router = APIRouter()


class RiskState(BaseModel):
    drawdown_pct: float | None
    daily_pnl: float | None
    open_positions: int
    circuit_breaker_state: str  # 'green' | 'amber' | 'red'
    note: str | None = None


def _classify(drawdown_pct: float) -> str:
    if drawdown_pct >= 0.18:
        return "red"
    if drawdown_pct >= 0.10:
        return "amber"
    return "green"


@router.get("/state", response_model=RiskState)
async def get_state(request: Request) -> RiskState:
    pool = request.app.state.pg_pool
    sql_latest = """
        SELECT ts, equity_usd, realized_pnl, unrealized_pnl, open_positions, drawdown_pct
        FROM brain.equity_curve
        ORDER BY ts DESC
        LIMIT 1
    """
    async with pool.acquire() as conn:
        row = await conn.fetchrow(sql_latest)
        if row is None:
            return RiskState(
                drawdown_pct=None,
                daily_pnl=None,
                open_positions=0,
                circuit_breaker_state="green",
                note="no equity_curve rows yet",
            )
        # Daily PnL = realized + unrealized of the most recent row minus the
        # latest row from >= 24h ago (or current row's own delta if older isn't there).
        sql_24h = """
            SELECT realized_pnl + unrealized_pnl AS pnl_total
            FROM brain.equity_curve
            WHERE ts <= ($1::timestamptz - interval '24 hours')
            ORDER BY ts DESC
            LIMIT 1
        """
        prev = await conn.fetchval(sql_24h, row["ts"])

    current_total = float(row["realized_pnl"]) + float(row["unrealized_pnl"])
    daily_pnl = current_total - float(prev) if prev is not None else current_total
    drawdown = float(row["drawdown_pct"])
    return RiskState(
        drawdown_pct=drawdown,
        daily_pnl=daily_pnl,
        open_positions=int(row["open_positions"]),
        circuit_breaker_state=_classify(drawdown),
    )
