"""GET /dashboard/freqai/* — FreqAI model insights (Phase 1.5.G).

Schema (owned by migration 004_phase6_freqai_history.sql):
  brain.freqai_history(id, retrained_at, pair, tf, train_window_days,
                       train_rows, auc, feature_importance, model_path, notes)

Phase 6 creates the table empty; Phase 7's training cron populates it.

Endpoints:
  GET /calibration   — calibration buckets (predicted P bucket vs actual win rate)
                       computed by JOINing brain.signals with brain.brain_journal,
                       AUC trend (rolling 30d), latest feature importance.
  GET /history       — raw retrain rows (most recent first, capped at 200).
  GET /predictions   — last 24h Claude oversight decision histogram (size mult
                       buckets) — the closest available proxy for live model
                       prediction distribution until a dedicated prediction log
                       is added (Phase 7+).

Each endpoint returns empty results + a `note` when the underlying data isn't
populated yet, per Iron Law 3 (no synthetic placeholder data).

asyncpg jsonb behaviour:
  asyncpg returns jsonb columns as Python `str` by default (no json codec
  registered on the pool). Both feature_importance and any future jsonb
  payload need json.loads() before arithmetic / dict access. The previous
  freqai.py:64 bug (`dict(latest_fi_row["feature_importance"])`) is fixed
  here by parsing the str through json.loads().
"""
from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel

router = APIRouter()


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------
class AucPoint(BaseModel):
    retrained_at: str
    auc: float
    pair: str
    tf: str


class CalibrationBucket(BaseModel):
    """One predicted-probability bucket with the realised win rate.

    Joined from brain.signals.claude_size_mult (the brain's resize multiplier,
    used here as a soft proxy for prediction confidence in the 0.5..1.5 range)
    and brain.brain_journal.actual_outcome ('win' / 'loss' / NULL=open).
    """

    bucket_lo: float
    bucket_hi: float
    predicted_mid: float
    actual_win_rate: float
    n: int


class CalibrationResponse(BaseModel):
    calibration: list[CalibrationBucket]
    auc_history: list[AucPoint]
    feature_importance: dict[str, Any] | None
    note: str


class PredictionBin(BaseModel):
    lo: float
    hi: float
    count: int


class PredictionHistogramResponse(BaseModel):
    bins: list[PredictionBin]
    total: int
    hours: int
    note: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _parse_jsonb(raw: Any) -> Any:
    """Decode a jsonb column from asyncpg.

    asyncpg returns jsonb as `str` by default. If the codec was registered
    elsewhere it might already be a dict/list — pass that through. None stays
    None. Bad strings raise loudly so we never silently substitute placeholder
    data (Iron Law 3).
    """
    if raw is None:
        return None
    if isinstance(raw, (dict, list)):
        return raw
    if isinstance(raw, (bytes, bytearray)):
        raw = raw.decode("utf-8")
    return json.loads(raw)


# Calibration buckets across the 0.5..1.5 claude_size_mult range. Width = 0.1.
# 10 evenly spaced buckets covering the schema CHECK constraint.
_CALIBRATION_EDGES: list[tuple[float, float]] = [
    (round(0.5 + i * 0.1, 2), round(0.5 + (i + 1) * 0.1, 2)) for i in range(10)
]


# ---------------------------------------------------------------------------
# /calibration
# ---------------------------------------------------------------------------
_CALIBRATION_JOIN_SQL = """
    SELECT s.claude_size_mult AS p,
           bj.actual_outcome AS outcome
    FROM brain.signals s
    JOIN brain.brain_journal bj ON bj.signal_id = s.id
    WHERE s.claude_decision IN ('approve', 'resize')
      AND s.claude_size_mult IS NOT NULL
      AND bj.actual_outcome IS NOT NULL
"""


@router.get("/calibration", response_model=CalibrationResponse)
async def calibration(request: Request) -> CalibrationResponse:
    """Aggregated calibration + AUC trend + latest feature importance.

    Empty payload + explanatory note when no retrains have happened yet.
    Calibration buckets are computed from JOIN(signals, brain_journal) and
    will be empty until Phase 6+ post-mortem cron records `actual_outcome`.
    """
    pool = request.app.state.pg_pool
    async with pool.acquire() as conn:
        # Rolling 30-day AUC window per spec line 484. The 200-row cap is a
        # belt-and-braces upper bound for the (rare) case where the retrain
        # cron runs more than ~6×/day.
        history_rows = await conn.fetch(
            "SELECT retrained_at, auc, pair, tf FROM brain.freqai_history "
            "WHERE retrained_at >= now() - interval '30 days' "
            "ORDER BY retrained_at DESC LIMIT 200"
        )
        latest_fi_row = await conn.fetchrow(
            "SELECT feature_importance FROM brain.freqai_history "
            "WHERE feature_importance != '{}'::jsonb "
            "ORDER BY retrained_at DESC LIMIT 1"
        )
        calib_rows = await conn.fetch(_CALIBRATION_JOIN_SQL)

    auc_history = [
        AucPoint(
            retrained_at=r["retrained_at"].isoformat(),
            auc=float(r["auc"]),
            pair=r["pair"],
            tf=r["tf"],
        )
        for r in history_rows
    ]

    # Decode jsonb (asyncpg returns it as str by default — see _parse_jsonb).
    feature_importance: dict[str, Any] | None = None
    if latest_fi_row is not None:
        decoded = _parse_jsonb(latest_fi_row["feature_importance"])
        if isinstance(decoded, dict):
            # Coerce values to float for safe JSON serialization.
            feature_importance = {str(k): float(v) for k, v in decoded.items()}

    # Bucket the calibration rows. Each bucket gets {predicted_mid, win_rate, n}.
    buckets: list[CalibrationBucket] = []
    for lo, hi in _CALIBRATION_EDGES:
        in_bucket = [
            r for r in calib_rows if lo <= float(r["p"]) < hi or (hi == 1.5 and float(r["p"]) == hi)
        ]
        if not in_bucket:
            continue
        wins = sum(1 for r in in_bucket if r["outcome"] == "win")
        buckets.append(
            CalibrationBucket(
                bucket_lo=lo,
                bucket_hi=hi,
                predicted_mid=round((lo + hi) / 2, 3),
                actual_win_rate=wins / len(in_bucket),
                n=len(in_bucket),
            )
        )

    note = ""
    if not auc_history:
        note = (
            "No FreqAI retrains recorded yet — Phase 7 cron populates "
            "brain.freqai_history on each daily retrain."
        )
    elif not buckets:
        note = (
            "Calibration empty — populates once brain.brain_journal rows "
            "have actual_outcome attached (Phase 6 post-mortem cron)."
        )

    return CalibrationResponse(
        calibration=buckets,
        auc_history=auc_history,
        feature_importance=feature_importance,
        note=note,
    )


# ---------------------------------------------------------------------------
# /history
# ---------------------------------------------------------------------------
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


# ---------------------------------------------------------------------------
# /predictions  (last 24h Claude oversight histogram)
# ---------------------------------------------------------------------------
_PREDICTIONS_SQL = """
    SELECT claude_size_mult AS p
    FROM brain.signals
    WHERE claude_decision IN ('approve', 'resize')
      AND claude_size_mult IS NOT NULL
      AND COALESCE(claude_decided_at, ts) >= now() - ($1::int * interval '1 hour')
"""


@router.get("/predictions", response_model=PredictionHistogramResponse)
async def predictions(
    request: Request,
    hours: int = Query(24, ge=1, le=168),
) -> PredictionHistogramResponse:
    """Histogram of Claude's oversight decisions over the last `hours` hours.

    Source: brain.signals.claude_size_mult for approved/resized signals where
    claude_decided_at falls inside the window. This is the most direct signal
    the brain emits to the body — it's *not* the raw FreqAI prediction
    probability (which Freqtrade computes internally and the brain doesn't
    persist), but it is what the operator actually cares about: the
    distribution of decisions that turned into capital allocations.

    The schema CHECK constraint clamps `claude_size_mult` to [0.5, 1.5].
    Empty histogram returns `bins=[]` + an explanatory note.
    """
    pool = request.app.state.pg_pool
    async with pool.acquire() as conn:
        rows = await conn.fetch(_PREDICTIONS_SQL, hours)

    bins: list[PredictionBin] = []
    for lo, hi in _CALIBRATION_EDGES:
        count = sum(
            1
            for r in rows
            if lo <= float(r["p"]) < hi or (hi == 1.5 and float(r["p"]) == hi)
        )
        if count > 0:
            bins.append(PredictionBin(lo=lo, hi=hi, count=count))

    note = ""
    if not bins:
        note = (
            f"No Claude oversight decisions in the last {hours}h yet. "
            "The histogram populates once the Phase 6 oversight cron starts "
            "approving / resizing signals."
        )

    return PredictionHistogramResponse(
        bins=bins,
        total=len(rows),
        hours=hours,
        note=note,
    )
