"""ClaudeOversightStrategy — Phase 3 v1 trend-following strategy.

Rule set:
    Entry  : EMA20 > EMA50  AND  ADX(14) > 25  AND  close > EMA20  AND  volume > 0
    Exit   : EMA20 < EMA50  AND  volume > 0
    Stop   : 2 * ATR(14) trailing (custom_stoploss)
    ROI    : time-decaying ladder

Phase 3 scope: rule-based signal generation + write each generated entry signal
to brain.signals (Postgres) so the dashboard WS sees it in real time. The
INSERT triggers pg_notify('dashboard_signals', ...) — see
infra/migrations/002_pg_notify_triggers.sql.

Phase 4 will REPLACE the body of confirm_trade_entry to additionally call the
PULSE bridge for Claude's approve/veto/resize verdict before allowing the
trade to fire. For now claude_decision stays NULL on the row, meaning
"no oversight applied yet".

Phase 7 will add a FreqAI prediction column gating entries.
"""
from __future__ import annotations

import logging
import os
import threading
from datetime import datetime
from typing import Optional

import pandas as pd
import psycopg
import talib.abstract as ta

from freqtrade.persistence import Trade
from freqtrade.strategy.interface import IStrategy


logger = logging.getLogger(__name__)


# Module-level connection cache. Lazy: opened on first signal write, reused
# across calls. Thread-safe via _CONN_LOCK because Freqtrade may invoke
# strategy callbacks from worker threads.
_CONN_LOCK = threading.Lock()
_CONN: psycopg.Connection | None = None


def _get_pg_connection() -> psycopg.Connection:
    """Lazy-open a psycopg connection from POSTGRES_* env vars.

    Hard-fails (KeyError) on missing env (Iron Law 3 — no silent default).
    """
    global _CONN
    with _CONN_LOCK:
        if _CONN is None or _CONN.closed:
            _CONN = psycopg.connect(
                host=os.environ["POSTGRES_HOST"],
                port=os.environ["POSTGRES_PORT"],
                dbname=os.environ["POSTGRES_DB"],
                user=os.environ["POSTGRES_USER"],
                password=os.environ["POSTGRES_PASSWORD"],
                autocommit=True,
            )
        return _CONN


class ClaudeOversightStrategy(IStrategy):
    """Phase 3 v1 strategy. See module docstring for the rule set."""

    INTERFACE_VERSION = 3
    timeframe = "15m"
    can_short = False  # Phase 3: spot-long only; futures shorts come later

    # Hard floor stop. Real per-trade stop comes from custom_stoploss below.
    stoploss = -0.10
    trailing_stop = False
    use_custom_stoploss = True

    # ROI: time-decaying take-profit ladder (replaceable by hyperopt later).
    minimal_roi = {"0": 0.10, "60": 0.05, "240": 0.02, "720": 0.0}

    process_only_new_candles = True
    use_exit_signal = True
    exit_profit_only = False
    exit_profit_offset = 0.0
    ignore_roi_if_entry_signal = False

    # Need EMA50 + ADX14 warmup; round up generously.
    startup_candle_count: int = 100

    # ----- indicators ------------------------------------------------------
    def populate_indicators(self, dataframe: pd.DataFrame, metadata: dict) -> pd.DataFrame:
        dataframe["ema20"] = ta.EMA(dataframe, timeperiod=20)
        dataframe["ema50"] = ta.EMA(dataframe, timeperiod=50)
        dataframe["adx14"] = ta.ADX(dataframe, timeperiod=14)
        dataframe["atr14"] = ta.ATR(dataframe, timeperiod=14)
        return dataframe

    # ----- entry signal ----------------------------------------------------
    def populate_entry_trend(self, dataframe: pd.DataFrame, metadata: dict) -> pd.DataFrame:
        cond = (
            (dataframe["ema20"] > dataframe["ema50"])
            & (dataframe["adx14"] > 25)
            & (dataframe["close"] > dataframe["ema20"])
            & (dataframe["volume"] > 0)
        )
        dataframe.loc[cond, "enter_long"] = 1
        dataframe.loc[cond, "enter_tag"] = "trend_ema_cross_adx"
        return dataframe

    # ----- exit signal -----------------------------------------------------
    def populate_exit_trend(self, dataframe: pd.DataFrame, metadata: dict) -> pd.DataFrame:
        cond = (dataframe["ema20"] < dataframe["ema50"]) & (dataframe["volume"] > 0)
        dataframe.loc[cond, "exit_long"] = 1
        dataframe.loc[cond, "exit_tag"] = "trend_reversal"
        return dataframe

    # ----- ATR trailing stop ----------------------------------------------
    def custom_stoploss(
        self,
        pair: str,
        trade: "Trade",
        current_time: datetime,
        current_rate: float,
        current_profit: float,
        **kwargs,
    ) -> Optional[float]:
        """Return a stoploss expressed as a fraction below current_rate.

        Uses the latest ATR(14) value from the analyzed dataframe. Returns
        ``None`` when the dataframe / ATR is not yet available — Freqtrade
        falls back to ``self.stoploss`` (the hard floor) in that case.
        """
        df, _ = self.dp.get_analyzed_dataframe(pair=pair, timeframe=self.timeframe)
        if df is None or df.empty:
            return None
        latest_atr = df["atr14"].iloc[-1]
        if pd.isna(latest_atr) or latest_atr <= 0 or current_rate <= 0:
            return None
        atr_pct = (2.0 * float(latest_atr)) / float(current_rate)
        return -atr_pct

    # ----- entry confirmation (writes signal to brain.signals) -------------
    def confirm_trade_entry(
        self,
        pair: str,
        order_type: str,
        amount: float,
        rate: float,
        time_in_force: str,
        current_time: datetime,
        entry_tag: Optional[str],
        side: str,
        **kwargs,
    ) -> bool:
        """Persist the entry signal to brain.signals.

        Phase 3 behaviour: every rule-based signal is "approved" by default
        (claude_decision stays NULL on the row). Phase 4 will replace this
        body to call PULSE bridge for Claude's verdict before allowing entry.

        Failure policy: HARD-FAIL (return False, blocking the trade) when the
        Postgres write fails. We are paper-trade-only at this phase (Iron
        Law 2) and visibility into the journal is more valuable than slipping
        an unrecorded trade through. A live-mode operator would revisit this
        when paper-trading is signed off.
        """
        try:
            self._write_signal_to_brain(
                pair=pair,
                side=side,
                rate=rate,
                ts=current_time,
                entry_tag=entry_tag,
            )
        except Exception:
            logger.exception(
                "ClaudeOversightStrategy: failed to write signal to brain.signals; "
                "blocking trade entry until visibility is restored."
            )
            return False
        return True

    # ----- internals -------------------------------------------------------
    def _write_signal_to_brain(
        self,
        pair: str,
        side: str,
        rate: float,
        ts: datetime,
        entry_tag: Optional[str],
    ) -> None:
        """INSERT into brain.signals.

        ON CONFLICT DO NOTHING — the (pair, tf, ts, signal_type) UNIQUE
        constraint protects against duplicate inserts when Freqtrade retries
        an order on the same candle.
        """
        signal_type = "enter_long" if side == "long" else "enter_short"
        indicators_payload = '{"entry_tag": ' + (
            'null' if entry_tag is None else f'"{entry_tag}"'
        ) + "}"

        sql = (
            "INSERT INTO brain.signals "
            "(ts, pair, tf, signal_type, price_at_signal, indicators) "
            "VALUES (%s, %s, %s, %s, %s, %s::jsonb) "
            "ON CONFLICT (pair, tf, ts, signal_type) DO NOTHING"
        )

        conn = _get_pg_connection()
        with conn.cursor() as cur:
            cur.execute(
                sql,
                (
                    ts,
                    pair,
                    self.timeframe,
                    signal_type,
                    rate,
                    indicators_payload,
                ),
            )
