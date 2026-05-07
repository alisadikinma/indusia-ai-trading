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

Phase 7 (this file): adds FreqAI feature engineering hooks + a target
generator (predicts whether close 16 bars ahead = 4h is >2% higher) +
gates ``populate_entry_trend`` on ``&-prediction > 0.65``. When the
``&-prediction`` column is absent (FreqAI disabled, e.g. during pure
Phase 3 backtests), the gate defaults to 1.0 so the strategy reverts
to Phase 3 rule-based behavior — backward compat preserved.
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
from freqtrade.strategy import DecimalParameter, IntParameter
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

    # Phase 7 — FreqAI gate. The actual ``enabled`` flag and feature
    # parameters live in config.json under the top-level "freqai" block;
    # this attribute is the strategy-side switch Freqtrade checks before
    # invoking feature_engineering_* hooks.
    freqai_info: dict = {"enabled": True}

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

    # ----- Phase 8 hyperoptable parameters --------------------------------
    # Wrapped so freqtrade hyperopt (or our custom run_hyperopt.py runner)
    # can search the space. Defaults match the Phase 3 rule-set (EMA 20/50,
    # ADX>25, ATR*2 trailing, prediction>0.65) so a plain backtest with
    # no params.json file replicates legacy behavior.
    #
    # See docs/decisions/2026-05-07-003-strategy-v1-hyperopt-params.md for
    # range justifications and the chosen-set decision.
    buy_ema_fast = IntParameter(
        low=10, high=25, default=20, space="buy", optimize=True, load=True
    )
    buy_ema_slow = IntParameter(
        low=40, high=80, default=50, space="buy", optimize=True, load=True
    )
    buy_adx_threshold = IntParameter(
        low=20, high=35, default=25, space="buy", optimize=True, load=True
    )
    buy_pred_threshold = DecimalParameter(
        low=0.55, high=0.75, default=0.65, decimals=2,
        space="buy", optimize=True, load=True,
    )
    sell_atr_mult = DecimalParameter(
        low=1.5, high=3.0, default=2.0, decimals=2,
        space="sell", optimize=True, load=True,
    )

    # ----- indicators ------------------------------------------------------
    def populate_indicators(self, dataframe: pd.DataFrame, metadata: dict) -> pd.DataFrame:
        # Use parameter-driven periods so hyperopt sweeps actually shift the
        # EMA crossover. ``.value`` returns the current point in the search
        # (or the loaded best from params file when running plain backtest).
        ema_fast_period = int(self.buy_ema_fast.value)
        ema_slow_period = int(self.buy_ema_slow.value)
        dataframe["ema20"] = ta.EMA(dataframe, timeperiod=ema_fast_period)
        dataframe["ema50"] = ta.EMA(dataframe, timeperiod=ema_slow_period)
        dataframe["adx14"] = ta.ADX(dataframe, timeperiod=14)
        dataframe["atr14"] = ta.ATR(dataframe, timeperiod=14)
        return dataframe

    # ----- FreqAI feature engineering (Phase 7) ----------------------------
    def feature_engineering_expand_all(
        self, dataframe: pd.DataFrame, period: int, metadata: dict, **kwargs
    ) -> pd.DataFrame:
        """Per-period base features. FreqAI expands these across the
        ``indicator_periods_candles`` configured in config.json.

        Naming convention: ``%-`` prefix marks a feature column. Freqtrade's
        feature pipeline scans dataframes for this prefix.
        """
        dataframe[f"%-rsi-period_{period}"] = ta.RSI(dataframe, timeperiod=period)
        dataframe[f"%-adx-period_{period}"] = ta.ADX(dataframe, timeperiod=period)
        ema_col = ta.EMA(dataframe, timeperiod=period)
        # Guard close==0 just in case (the divide is safe at runtime since
        # crypto close > 0, but tests feed synthetic frames).
        dataframe[f"%-ema_dist-period_{period}"] = (
            dataframe["close"] - ema_col
        ) / dataframe["close"].replace(0, pd.NA)
        return dataframe

    def feature_engineering_expand_basic(
        self, dataframe: pd.DataFrame, metadata: dict, **kwargs
    ) -> pd.DataFrame:
        """Features computed once (not expanded per period).

        Notes:
          * 24h window on 15m timeframe = 96 bars.
          * Multi-horizon returns + volatility capture trend persistence
            across the timescales the strategy actually trades on.
        """
        vol_window = 96  # 24h on 15m
        dataframe["%-volume_z_24h"] = (
            (dataframe["volume"] - dataframe["volume"].rolling(vol_window).mean())
            / dataframe["volume"].rolling(vol_window).std()
        )
        for h in [1, 4, 12, 24]:
            bars = h * 4  # 4 bars per hour at 15m
            dataframe[f"%-return_{h}h"] = dataframe["close"].pct_change(periods=bars)
            if h <= 12:
                dataframe[f"%-volatility_{h}h"] = (
                    dataframe["close"].pct_change().rolling(bars).std()
                )
        return dataframe

    def feature_engineering_standard(
        self, dataframe: pd.DataFrame, metadata: dict, **kwargs
    ) -> pd.DataFrame:
        """Standard features computed once, post-base.

        Currently a no-op — placeholder for downstream FreqAI versions
        that may add cross-asset correlation features here.
        """
        return dataframe

    def set_freqai_targets(
        self, dataframe: pd.DataFrame, metadata: dict, **kwargs
    ) -> pd.DataFrame:
        """Target: 1 if close 16 bars ahead is >2% higher than current close.

        16 bars on 15m = 4 hours forward. The 2% threshold is the strategy's
        de facto take-profit target (matches the ``minimal_roi`` ladder's
        first horizon). Last 16 rows have NaN futures → marked 0.
        """
        horizon = 16
        future_close = dataframe["close"].shift(-horizon)
        future_return = (future_close / dataframe["close"]) - 1
        dataframe["&-prediction"] = (future_return > 0.02).fillna(False).astype(int)
        return dataframe

    # ----- entry signal ----------------------------------------------------
    def populate_entry_trend(self, dataframe: pd.DataFrame, metadata: dict) -> pd.DataFrame:
        # Phase 7 FreqAI gate. Default 1.0 when column absent → behaves as
        # Phase 3 (backward compat with FreqAI-disabled backtests).
        if "&-prediction" in dataframe.columns:
            freqai_gate = dataframe["&-prediction"]
        else:
            freqai_gate = pd.Series(1.0, index=dataframe.index)

        adx_th = int(self.buy_adx_threshold.value)
        pred_th = float(self.buy_pred_threshold.value)
        cond = (
            (dataframe["ema20"] > dataframe["ema50"])
            & (dataframe["adx14"] > adx_th)
            & (dataframe["close"] > dataframe["ema20"])
            & (dataframe["volume"] > 0)
            & (freqai_gate > pred_th)
        )
        dataframe.loc[cond, "enter_long"] = 1
        # Use explicit tag so backtest analytics can distinguish Phase 3
        # rule-only entries from Phase 7 ML-gated entries by inspecting the
        # tag column.
        if "&-prediction" in dataframe.columns:
            dataframe.loc[cond, "enter_tag"] = "trend_ema_cross_adx_ml"
        else:
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
        atr_mult = float(self.sell_atr_mult.value)
        atr_pct = (atr_mult * float(latest_atr)) / float(current_rate)
        return -atr_pct

    # ----- entry confirmation (writes signal + reads Claude veto) ----------
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
        """Persist the entry signal then honor Claude's veto (Phase 4).

        Flow:
            1. Write the rule-based signal to brain.signals (Phase 3 behavior).
               Failure to write is a hard abort — paper-trade-only phase, we
               must not place trades that aren't auditable.
            2. Read brain.signals.claude_decision for the row we just wrote.
               - 'veto'    → return False (Claude vetoed; block entry).
               - 'resize'  → return True. Phase 4 limitation: Freqtrade has
                             already computed `amount` so size_mult is logged
                             but not applied here. Phase 7 will integrate
                             custom_stake_amount() to honor size_mult before
                             order placement.
               - 'approve' / NULL → proceed (advisory model — NULL means
                             Claude's 5-min routine has not yet decided, so
                             rule-based default fires).
        """
        signal_id = self._write_signal_to_brain(
            pair=pair,
            side=side,
            rate=rate,
            ts=current_time,
            entry_tag=entry_tag,
        )
        if signal_id is None:
            logger.error(
                "ClaudeOversightStrategy: failed to write signal to brain.signals; "
                "blocking trade entry until visibility is restored."
            )
            return False

        decision = self._read_claude_decision(signal_id)
        if decision == "veto":
            self._log_veto(pair=pair, signal_id=signal_id, current_time=current_time)
            return False
        if decision == "resize":
            logger.info(
                "ClaudeOversightStrategy: signal_id=%s resized by Claude; proceeding "
                "with original Freqtrade-computed amount (Phase 7 will integrate "
                "custom_stake_amount to honor size_mult).",
                signal_id,
            )
            return True
        # decision in (None, "approve") → proceed with rule-based default.
        return True

    # ----- internals -------------------------------------------------------
    def _write_signal_to_brain(
        self,
        pair: str,
        side: str,
        rate: float,
        ts: datetime,
        entry_tag: Optional[str],
    ) -> Optional[int]:
        """INSERT into brain.signals; return the new id (or the existing one
        if (pair, tf, ts, signal_type) already maps to a row). Returns None
        on Postgres failure so the caller can hard-abort the trade.

        The (pair, tf, ts, signal_type) UNIQUE constraint protects against
        duplicate inserts when Freqtrade retries an order on the same candle.
        """
        signal_type = "enter_long" if side == "long" else "enter_short"
        indicators_payload = '{"entry_tag": ' + (
            'null' if entry_tag is None else f'"{entry_tag}"'
        ) + "}"

        # ON CONFLICT ... DO UPDATE on a no-op column so we get RETURNING id
        # for both fresh inserts and existing rows (DO NOTHING wouldn't
        # return the id of the colliding row).
        sql = (
            "INSERT INTO brain.signals "
            "(ts, pair, tf, signal_type, price_at_signal, indicators) "
            "VALUES (%s, %s, %s, %s, %s, %s::jsonb) "
            "ON CONFLICT (pair, tf, ts, signal_type) "
            "DO UPDATE SET indicators = brain.signals.indicators "
            "RETURNING id"
        )

        try:
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
                row = cur.fetchone()
        except Exception:
            logger.exception(
                "ClaudeOversightStrategy: brain.signals INSERT raised; "
                "returning None so the strategy can abort."
            )
            return None
        if row is None:
            return None
        return int(row[0])

    def _read_claude_decision(self, signal_id: int) -> Optional[str]:
        """Read brain.signals.claude_decision. Returns None when NULL or row
        missing (treated as 'no decision yet' — proceed with rule-based)."""
        try:
            conn = _get_pg_connection()
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT claude_decision FROM brain.signals WHERE id = %s",
                    (signal_id,),
                )
                row = cur.fetchone()
        except Exception:
            logger.exception(
                "ClaudeOversightStrategy: failed reading claude_decision for "
                "signal_id=%s; defaulting to None (proceed).",
                signal_id,
            )
            return None
        if row is None:
            return None
        return row[0]

    def _log_veto(self, pair: str, signal_id: int, current_time: datetime) -> None:
        """Append a journal note that we refused entry due to Claude's veto.

        brain.brain_journal is append-only (Iron Law 5). This call INSERTs only.
        On any failure we log loudly but don't re-raise — the veto itself
        already short-circuits the trade; missing the audit row is bad but
        not as bad as silently slipping the trade through.
        """
        reasoning = (
            f"confirm_trade_entry refused: Claude vetoed signal_id={signal_id} "
            f"on {pair} at {current_time.isoformat()}. Strategy honored the veto."
        )
        try:
            conn = _get_pg_connection()
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO brain.brain_journal "
                    "(ts, signal_id, regime, decision, reasoning, confidence) "
                    "VALUES (now(), %s, %s, %s, %s, %s)",
                    (
                        signal_id,
                        # Strategy doesn't classify regime — that is Claude's job.
                        # Use 'no_action' bucket via decision field, regime stays
                        # 'unknown' so analytics know the entry was strategy-side.
                        "unknown",
                        "no_action",
                        reasoning,
                        None,
                    ),
                )
        except Exception:
            logger.exception(
                "ClaudeOversightStrategy: failed to log veto for signal_id=%s",
                signal_id,
            )
