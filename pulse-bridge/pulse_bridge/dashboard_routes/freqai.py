"""GET /dashboard/freqai/* — FreqAI model insights.

Schema (owned by migration 004_phase6_freqai_history.sql):
  brain.freqai_history(id, retrained_at, pair, tf, train_window_days,
                       train_rows, auc, feature_importance, model_path, notes)

Phase 6 creates the table empty; Phase 7's training cron populates it.
Until rows exist, calibration aggregations are not yet meaningful — we
return empty arrays + a "no runs yet" note. Calibration bucket computation
itself is Phase 7 work (it needs the actual prediction-vs-outcome pairs).
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel

router = APIRouter()


class AucPoint(BaseModel):
    retrained_at: str
    auc: float
    pair: str
    tf: str


class CalibrationResponse(BaseModel):
    calibration: list[dict[str, Any]]
    auc_history: list[AucPoint]
    feature_importance: dict[str, Any] | None
    note: str


@router.get("/calibration", response_model=CalibrationResponse)
async def calibration(request: Request) -> CalibrationResponse:
    """Aggregated calibration + AUC trend + feature importance.

    Empty payload + explanatory note when no retrains have happened yet.
    """
    pool = request.app.state.pg_pool
    async with pool.acquire() as conn:
        history_rows = await conn.fetch(
            "SELECT retrained_at, auc, pair, tf FROM brain.freqai_history "
            "ORDER BY retrained_at DESC LIMIT 200"
        )
        latest_fi_row = await conn.fetchrow(
            "SELECT feature_importance FROM brain.freqai_history "
            "WHERE feature_importance != '{}'::jsonb "
            "ORDER BY retrained_at DESC LIMIT 1"
        )

    auc_history = [
        AucPoint(
            retrained_at=r["retrained_at"].isoformat(),
            auc=float(r["auc"]),
            pair=r["pair"],
            tf=r["tf"],
        )
        for r in history_rows
    ]
    feature_importance = (
        dict(latest_fi_row["feature_importance"]) if latest_fi_row else None
    )

    note = (
        "No FreqAI retrains recorded yet — Phase 7 cron populates "
        "brain.freqai_history on each daily retrain."
        if not auc_history
        else ""
    )

    return CalibrationResponse(
        calibration=[],  # Phase 7 computes calibration buckets from prediction outcomes
        auc_history=auc_history,
        feature_importance=feature_importance,
        note=note,
    )


@router.get("/history", response_model=list[dict[str, Any]])
async def history(request: Request) -> list[dict[str, Any]]:
    """Raw retrain history rows (most recent first, capped at 200)."""
    pool = request.app.state.pg_pool
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, retrained_at, pair, tf, train_window_days, train_rows, "
            "       auc, model_path, notes "
            "FROM brain.freqai_history "
            "ORDER BY retrained_at DESC LIMIT 200"
        )
    return [
        {
            "id": r["id"],
            "retrained_at": r["retrained_at"].isoformat(),
            "pair": r["pair"],
            "tf": r["tf"],
            "train_window_days": r["train_window_days"],
            "train_rows": r["train_rows"],
            "auc": float(r["auc"]),
            "model_path": r["model_path"],
            "notes": r["notes"],
        }
        for r in rows
    ]
