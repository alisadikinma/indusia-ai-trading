"""GET /v1/context_bundle — cache-friendly bundle for the Claude routine.

Layout is intentionally split into a STABLE prefix (Iron Laws + skill list +
schema summary) and a DYNAMIC tail (recent OHLCV, pending signals, journal,
equity). Anthropic's prompt cache has a 5-minute TTL — keeping the stable
prefix invariant across most calls maximizes cache-hit rate when Claude's
oversight routine assembles its prompt.

The Iron Laws array is REAL content extracted from CLAUDE.md, not a stub.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Annotated, Any

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel

from .auth import hmac_dep

router = APIRouter()


# --- STABLE PREFIX ----------------------------------------------------------
# Iron Laws — exact summaries copied from CLAUDE.md so the routine sees the
# same wording every cycle. NOT a placeholder; this is the contract.
IRON_LAWS: list[str] = [
    "Iron Law 1: Claude cannot override risk rails. Max position 25% equity, "
    "max 3 concurrent, daily-loss circuit breaker -5%, per-trade 2xATR(14) "
    "trailing stop, max-drawdown kill switch -20% from peak. Claude may VETO "
    "or RESIZE within the cap; Claude may NOT disable, extend, or reset.",
    "Iron Law 2: No live trade without backtest + paper-trade sign-off. "
    "Walk-forward Sharpe>1.5, MaxDD<25%, PF>1.4 in all 5 OOS folds; then "
    "3-4 weeks paper trade with PnL drift <30% vs backtest; then live $100 "
    "for 4 weeks. No silent advance.",
    "Iron Law 3: No placeholder data in production code paths. Real Postgres, "
    "real CCXT, real env via os.environ[...]; mocks only inside tests/.",
    "Iron Law 4: Claude must not modify its own discipline files "
    "(<bot>/claude-routines/skills/trading-discipline.md, freqtrade config, "
    "migrations, CLAUDE.md, references/). Operator-only, with ADR.",
    "Iron Law 5: Memory grows append-only. <schema>.brain_journal trigger-rejects "
    "UPDATE/DELETE. <bot>/claude-routines/memory/*.md is append-only by convention.",
]

PLAYBOOK_SKILLS: list[str] = [
    "regime-detection",
    "signal-evaluation",
    "trading-discipline",
    "known-traps",
    "post-mortem-protocol",
]


def _coerce_json(val: Any) -> Any:
    if val is None:
        return None
    if isinstance(val, (dict, list)):
        return val
    if isinstance(val, (bytes, bytearray)):
        return json.loads(val.decode("utf-8"))
    if isinstance(val, str):
        return json.loads(val)
    return val


# --- DATA MODELS ------------------------------------------------------------
class StableBlock(BaseModel):
    iron_laws: list[str]
    schema_summary: dict[str, str]
    playbook_skills: list[str]


class OhlcvBar(BaseModel):
    ts: datetime
    o: float
    h: float
    l: float
    c: float
    v: float


class OpenPosition(BaseModel):
    signal_id: int
    pair: str
    side: str
    decided_at: datetime
    intended_size_mult: float | None
    price_at_signal: float


class PendingSignalSummary(BaseModel):
    id: int
    ts: datetime
    pair: str
    tf: str
    signal_type: str
    price_at_signal: float


class JournalEntrySummary(BaseModel):
    ts: datetime
    regime: str
    decision: str
    reasoning: str
    confidence: int | None
    actual_outcome: str | None


class DynamicBlock(BaseModel):
    now: datetime
    ohlcv_last_4h: list[OhlcvBar]
    open_positions: list[OpenPosition]
    pending_signals: list[PendingSignalSummary]
    recent_journal: list[JournalEntrySummary]
    current_equity_pct: float | None
    drawdown_pct: float | None


class ContextBundle(BaseModel):
    stable: StableBlock
    dynamic: DynamicBlock


# --- ROUTE ------------------------------------------------------------------
@router.get("/context_bundle", response_model=ContextBundle, dependencies=[hmac_dep])
async def get_context_bundle(
    request: Request,
    pair: Annotated[str, Query(min_length=3, max_length=20)],
    tf: Annotated[str, Query(min_length=2, max_length=5)] = "15m",
) -> ContextBundle:
    pool = request.app.state.pg_pool
    now = datetime.now(tz=timezone.utc)
    four_hours_ago = now - timedelta(hours=4)

    async with pool.acquire() as conn:
        ohlcv_rows = await conn.fetch(
            "SELECT ts, open AS o, high AS h, low AS l, close AS c, volume AS v "
            "FROM brain.ohlcv "
            "WHERE pair = $1 AND tf = $2 AND ts >= $3 "
            "ORDER BY ts ASC",
            pair, tf, four_hours_ago,
        )

        open_position_rows = await conn.fetch(
            "SELECT id AS signal_id, pair, "
            "       CASE WHEN signal_type IN ('enter_long', 'exit_short') THEN 'long' "
            "            WHEN signal_type IN ('enter_short', 'exit_long') THEN 'short' "
            "            ELSE 'unknown' END AS side, "
            "       COALESCE(claude_decided_at, ts) AS decided_at, "
            "       claude_size_mult AS intended_size_mult, "
            "       price_at_signal "
            "FROM brain.signals "
            "WHERE claude_decision IN ('approve', 'resize') "
            "  AND signal_type IN ('enter_long', 'enter_short') "
            "  AND trade_id IS NULL "
            "ORDER BY decided_at DESC "
            "LIMIT 50"
        )

        pending_rows = await conn.fetch(
            "SELECT id, ts, pair, tf, signal_type, price_at_signal "
            "FROM brain.signals "
            "WHERE claude_decision IS NULL AND ts >= $1 "
            "ORDER BY ts DESC "
            "LIMIT 20",
            now - timedelta(hours=1),
        )

        journal_rows = await conn.fetch(
            "SELECT ts, regime, decision, reasoning, confidence, actual_outcome "
            "FROM brain.brain_journal "
            "ORDER BY ts DESC "
            "LIMIT 10"
        )

        equity_row = await conn.fetchrow(
            "SELECT equity_usd, drawdown_pct "
            "FROM brain.equity_curve "
            "ORDER BY ts DESC LIMIT 1"
        )

    # current_equity_pct = equity_usd represented as a percentage relative to
    # the running max — but since we only store equity_usd here, expose the
    # raw figure (in USD) until Phase 7+ teaches the equity_curve writer to
    # store a normalized ratio. The dashboard already operates on the same
    # column, so we mirror its semantics.
    current_equity_pct: float | None = (
        float(equity_row["equity_usd"]) if equity_row is not None else None
    )
    drawdown_pct: float | None = (
        float(equity_row["drawdown_pct"]) if equity_row is not None else None
    )

    return ContextBundle(
        stable=StableBlock(
            iron_laws=IRON_LAWS,
            schema_summary={"pair": pair, "tf": tf},
            playbook_skills=PLAYBOOK_SKILLS,
        ),
        dynamic=DynamicBlock(
            now=now,
            ohlcv_last_4h=[
                OhlcvBar(
                    ts=r["ts"],
                    o=float(r["o"]),
                    h=float(r["h"]),
                    l=float(r["l"]),
                    c=float(r["c"]),
                    v=float(r["v"]),
                )
                for r in ohlcv_rows
            ],
            open_positions=[
                OpenPosition(
                    signal_id=r["signal_id"],
                    pair=r["pair"],
                    side=r["side"],
                    decided_at=r["decided_at"],
                    intended_size_mult=(
                        float(r["intended_size_mult"])
                        if r["intended_size_mult"] is not None
                        else None
                    ),
                    price_at_signal=float(r["price_at_signal"]),
                )
                for r in open_position_rows
            ],
            pending_signals=[
                PendingSignalSummary(
                    id=r["id"],
                    ts=r["ts"],
                    pair=r["pair"],
                    tf=r["tf"],
                    signal_type=r["signal_type"],
                    price_at_signal=float(r["price_at_signal"]),
                )
                for r in pending_rows
            ],
            recent_journal=[
                JournalEntrySummary(
                    ts=r["ts"],
                    regime=r["regime"],
                    decision=r["decision"],
                    reasoning=r["reasoning"],
                    confidence=r["confidence"],
                    actual_outcome=r["actual_outcome"],
                )
                for r in journal_rows
            ],
            current_equity_pct=current_equity_pct,
            drawdown_pct=drawdown_pct,
        ),
    )
