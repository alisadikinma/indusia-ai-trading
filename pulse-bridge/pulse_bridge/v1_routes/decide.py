"""POST /v1/decide — Claude posts approve / veto / resize for one signal.

Atomic Postgres transaction:
    1. UPDATE brain.signals SET claude_decision, claude_size_mult, claude_decided_at
       WHERE id = $1 AND claude_decision IS NULL  (idempotency guard)
    2. INSERT INTO brain.brain_journal (...)  — append-only (Iron Law 5).

The journal INSERT triggers pg_notify('dashboard_journal', ...) so the
dashboard WebSocket fan-out picks it up automatically (002_pg_notify_triggers).
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field, model_validator

from .auth import hmac_dep

router = APIRouter()


class DecideRequest(BaseModel):
    signal_id: int = Field(ge=1)
    regime: Literal["trending_up", "trending_down", "ranging", "volatile"]
    decision: Literal["approve", "veto", "resize"]
    size_mult: float | None = Field(default=None, ge=0.5, le=1.5)
    reasoning: str = Field(min_length=10, max_length=4000)
    confidence: int = Field(ge=1, le=10)
    expected_outcome: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def _size_mult_only_for_resize(self) -> DecideRequest:
        if self.decision == "resize" and self.size_mult is None:
            raise ValueError("size_mult is required when decision='resize'")
        if self.decision != "resize" and self.size_mult is not None:
            raise ValueError("size_mult is only valid when decision='resize'")
        return self


class DecideResponse(BaseModel):
    signal_id: int
    decision_recorded_at: datetime
    journal_id: int


@router.post("/decide", response_model=DecideResponse, dependencies=[hmac_dep])
async def post_decide(payload: DecideRequest, request: Request) -> DecideResponse:
    pool = request.app.state.pg_pool
    async with pool.acquire() as conn, conn.transaction():
        # 1. Verify the signal exists at all (so we can distinguish 404 vs 409).
        existing = await conn.fetchrow(
            "SELECT id, claude_decision FROM brain.signals WHERE id = $1 FOR UPDATE",
            payload.signal_id,
        )
        if existing is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"signal_id {payload.signal_id} not found in brain.signals.",
            )
        if existing["claude_decision"] is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"signal_id {payload.signal_id} already has claude_decision="
                    f"'{existing['claude_decision']}'. Decisions are idempotent."
                ),
            )

        # 2. Atomic UPDATE on brain.signals.
        decided_row = await conn.fetchrow(
            "UPDATE brain.signals "
            "SET claude_decision = $1, claude_size_mult = $2, claude_decided_at = now() "
            "WHERE id = $3 "
            "RETURNING claude_decided_at",
            payload.decision,
            payload.size_mult,
            payload.signal_id,
        )
        decided_at: datetime = decided_row["claude_decided_at"]

        # 3. Append-only INSERT into brain.brain_journal (Iron Law 5).
        journal_row = await conn.fetchrow(
            "INSERT INTO brain.brain_journal "
            "(ts, signal_id, regime, decision, reasoning, confidence, expected_outcome) "
            "VALUES (now(), $1, $2, $3, $4, $5, $6) "
            "RETURNING id",
            payload.signal_id,
            payload.regime,
            payload.decision,
            payload.reasoning,
            payload.confidence,
            payload.expected_outcome,
        )
        journal_id = int(journal_row["id"])

    return DecideResponse(
        signal_id=payload.signal_id,
        decision_recorded_at=decided_at,
        journal_id=journal_id,
    )
