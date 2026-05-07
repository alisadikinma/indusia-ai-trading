"""GET /dashboard/chart/ohlcv — OHLCV time-series for the live chart view.
GET /dashboard/chart/pairs — pair whitelist from crypto-bot config.
"""
from __future__ import annotations

import functools
import json
from datetime import datetime
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, ConfigDict

router = APIRouter()

# ---------------------------------------------------------------------------
# /dashboard/chart/pairs — pair whitelist from crypto-bot/freqtrade-config/config.json.
# ---------------------------------------------------------------------------

# Path resolution: this file lives at:
#   <repo>/pulse-bridge/pulse_bridge/dashboard_routes/chart.py
# Three .parent() calls reach the repo root:
#   parents[0]=dashboard_routes, [1]=pulse_bridge, [2]=pulse-bridge, [3]=<repo>.
_REPO_ROOT = Path(__file__).resolve().parents[3]
_FREQTRADE_CONFIG = _REPO_ROOT / "crypto-bot" / "freqtrade-config" / "config.json"


@functools.lru_cache(maxsize=1)
def _load_pair_whitelist() -> list[str]:
    """Read pair_whitelist from crypto-bot config. Hard-fails on any error (Iron Law 3)."""
    raw = _FREQTRADE_CONFIG.read_text(encoding="utf-8")
    cfg = json.loads(raw)
    pairs = cfg["exchange"]["pair_whitelist"]
    if not isinstance(pairs, list) or len(pairs) == 0:
        raise RuntimeError(
            f"pair_whitelist in {_FREQTRADE_CONFIG} is empty or not a list"
        )
    return [str(p) for p in pairs]


@router.get("/pairs", response_model=list[str])
async def get_pairs() -> list[str]:
    """Return the operator-configured pair whitelist from crypto-bot config.

    Hard-fails with HTTP 500 if config is missing or unparseable (Iron Law 3 —
    no silent fallback to a default list). The config is operator-only; changes
    require a service restart which clears the lru_cache.
    """
    return _load_pair_whitelist()


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
