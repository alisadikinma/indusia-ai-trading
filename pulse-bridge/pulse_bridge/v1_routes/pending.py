"""GET /v1/pending_signals — Claude polls the queue of un-decided signals."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Annotated, Any

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel

from .auth import hmac_dep


def _coerce_json(val: Any) -> Any:
    """asyncpg returns JSONB as str unless a codec is registered. Normalize."""
    if val is None:
        return {}
    if isinstance(val, (dict, list)):
        return val
    if isinstance(val, (bytes, bytearray)):
        return json.loads(val.decode("utf-8"))
    if isinstance(val, str):
        return json.loads(val)
    return val

router = APIRouter()


class PendingSignal(BaseModel):
    id: int
    ts: datetime
    pair: str
    tf: str
    signal_type: str
    price_at_signal: float
    indicators: dict[str, Any]


_SQL = (
    "SELECT id, ts, pair, tf, signal_type, price_at_signal, indicators "
    "FROM brain.signals "
    "WHERE claude_decision IS NULL AND ts >= $1 "
    "ORDER BY ts DESC "
    "LIMIT $2"
)


@router.get("/pending_signals", response_model=list[PendingSignal], dependencies=[hmac_dep])
async def get_pending_signals(
    request: Request,
    since: Annotated[datetime | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> list[PendingSignal]:
    pool = request.app.state.pg_pool
    if since is None:
        since = datetime.now(tz=timezone.utc) - timedelta(hours=1)
    async with pool.acquire() as conn:
        rows = await conn.fetch(_SQL, since, limit)
    return [
        PendingSignal(
            id=r["id"],
            ts=r["ts"],
            pair=r["pair"],
            tf=r["tf"],
            signal_type=r["signal_type"],
            price_at_signal=float(r["price_at_signal"]),
            indicators=_coerce_json(r["indicators"]),
        )
        for r in rows
    ]
