"""GET /dashboard/freqai/* — FreqAI model insights.

The freqai_history table is owned by Phase 7 (FreqAI integration). Until that
phase lands, calibration/history endpoints return empty payloads with an
explicit "Phase 7" note instead of throwing or hardcoding fake data — the
backing table simply does not exist yet, so no real query can succeed.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel

router = APIRouter()


class CalibrationResponse(BaseModel):
    calibration: list[dict[str, Any]]
    auc_history: list[dict[str, Any]]
    feature_importance: dict[str, Any] | None
    note: str


async def _freqai_table_exists(request: Request) -> bool:
    """Return True iff a Phase-7 freqai_history table is present in the brain schema."""
    pool = request.app.state.pg_pool
    sql = (
        "SELECT EXISTS ("
        "  SELECT 1 FROM information_schema.tables "
        "  WHERE table_schema='brain' AND table_name='freqai_history'"
        ")"
    )
    async with pool.acquire() as conn:
        return bool(await conn.fetchval(sql))


@router.get("/calibration", response_model=CalibrationResponse)
async def calibration(request: Request) -> CalibrationResponse:
    if not await _freqai_table_exists(request):
        return CalibrationResponse(
            calibration=[],
            auc_history=[],
            feature_importance=None,
            note="FreqAI model not yet trained — Phase 7 will populate brain.freqai_history.",
        )
    # Phase 7 will replace this branch with a real query against brain.freqai_history.
    pool = request.app.state.pg_pool
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT bucket, predicted_pct, actual_pct FROM brain.freqai_history "
            "ORDER BY bucket"
        )
    return CalibrationResponse(
        calibration=[dict(r) for r in rows],
        auc_history=[],
        feature_importance=None,
        note="",
    )


@router.get("/history", response_model=list[dict[str, Any]])
async def history(request: Request) -> list[dict[str, Any]]:
    if not await _freqai_table_exists(request):
        return []
    pool = request.app.state.pg_pool
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM brain.freqai_history ORDER BY trained_at DESC LIMIT 200"
        )
    return [dict(r) for r in rows]
