"""GET /dashboard/chart/ohlcv — OHLCV time-series for the live chart view.
GET /dashboard/chart/pairs — pair whitelist from crypto-bot config.
"""
from __future__ import annotations

import functools
import json
from datetime import datetime
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request
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
    """Read pair_whitelist from crypto-bot config. Hard-fails on any error (Iron Law 3).

    Note: ``functools.lru_cache`` does NOT cache exceptions, so every failed
    request re-reads the file. This means a config repair (operator edits
    config.json without service restart) IS picked up on the next request —
    but a SUCCESSFUL load is cached until restart. Documented behavior, not a
    bug: the operator workflow is "edit config → restart service".
    """
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

    Returns HTTP 503 with a diagnostic detail if the config is missing,
    unparseable, or has no pair_whitelist (Iron Law 3 — no silent fallback to
    a default list). The config is operator-only; a successful load is cached
    until service restart.
    """
    try:
        return _load_pair_whitelist()
    except (FileNotFoundError, json.JSONDecodeError, KeyError, RuntimeError) as exc:
        raise HTTPException(
            status_code=503,
            detail=f"pair_whitelist unavailable: {exc}",
        ) from exc


class OhlcvPoint(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    ts: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float


# Maps API tf param to the source object. The 1m source is the raw
# hypertable (filtered on tf='1m'); higher timeframes are TimescaleDB
# continuous aggregates built in migration 007. Names are NOT user
# input — strict whitelist guards against SQL injection at endpoint.
_TF_SOURCES: dict[str, tuple[str, bool]] = {
    "1m":  ("brain.ohlcv",     True),   # has tf column → filter
    "5m":  ("brain.ohlcv_5m",  False),
    "15m": ("brain.ohlcv_15m", False),
    "1h":  ("brain.ohlcv_1h",  False),
    "4h":  ("brain.ohlcv_4h",  False),
    "1d":  ("brain.ohlcv_1d",  False),
}


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

    `tf=1m` reads `brain.ohlcv` directly (raw hypertable). Higher timeframes
    read continuous aggregates `brain.ohlcv_<tf>` built in migration 007.
    Empty array if no rows match — never raises (Iron Law 3 anti-placeholder
    requires real Postgres query; empty result must come from a real 0-row
    query, never hardcoded).
    """
    if tf not in _TF_SOURCES:
        raise HTTPException(
            status_code=400,
            detail=f"unsupported tf={tf!r}; allowed: {sorted(_TF_SOURCES)}",
        )
    table, has_tf_col = _TF_SOURCES[tf]
    where_tf = "AND tf = '1m'" if has_tf_col else ""
    sql = f"""
        SELECT ts, open, high, low, close, volume
        FROM {table}
        WHERE pair = $1
          {where_tf}
          AND ($2::timestamptz IS NULL OR ts >= $2)
          AND ($3::timestamptz IS NULL OR ts <= $3)
        ORDER BY ts DESC
        LIMIT $4
    """
    pool = request.app.state.pg_pool
    async with pool.acquire() as conn:
        rows = await conn.fetch(sql, pair, from_ts, to_ts, limit)
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
