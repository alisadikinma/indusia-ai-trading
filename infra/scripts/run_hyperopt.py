"""Phase 8 — Windows-friendly hyperopt sweep runner.

The Freqtrade ``hyperopt`` CLI cannot run on this Windows dev box because
``ccxt.binance().load_markets()`` is geofenced. This runner sidesteps the
CLI entirely and computes a Sharpe-optimizing parameter sweep directly
against Postgres-backed OHLCV. Pattern is the same one ``freqai_train_smoke.py``
uses for Phase 7 verification.

What it does:

  1. Pulls 1m BTC/USDT OHLCV from ``brain.ohlcv`` for the requested timerange,
     resamples to 15m (the strategy's timeframe).
  2. For each random parameter sample (random search; Optuna's TPE would be
     better but adds complexity for negligible win at sub-1k epochs),
     applies the strategy's rule set:
         entry := EMA_fast > EMA_slow & ADX(14) > adx_th & close > EMA_fast
         exit  := EMA_fast < EMA_slow
         stop  := -atr_mult * ATR(14) / price (trailing on entry price)
     and computes simulated profit_abs per trade. Pure rule-based sim;
     FreqAI gate intentionally skipped here because that adds another
     order of magnitude in cost (FreqAI retrains every 16 candles). The
     gate's ``buy_pred_threshold`` is still part of the search space —
     when training data is not available we treat it as "any value
     between 0.55 and 0.75 has identical effect" but persist the sampled
     value so the result row is faithful.
  3. Computes Sharpe via :class:`SharpeHyperOptLoss.hyperopt_loss_function`
     (real Freqtrade code path — Iron Law 3 / no reimplementation).
  4. Persists every epoch to ``brain.hyperopt_results``.
  5. Prints the top-3 by loss at exit.

Usage::

    set -a; source .env; set +a
    python -m infra.scripts.run_hyperopt --pair BTC/USDT \\
        --timerange-start 2024-01-01 --timerange-end 2024-07-01 \\
        --epochs 50 --run-id smoke-001

Caveats baked in (and documented in ADR-003):

  * Random search, not TPE. Adequate for the 5-dim space at <100 epochs.
  * Pure rule-based; no FreqAI gate. The chosen-set must be re-validated
    on the VPS with the FreqAI gate enabled.
  * Single pair (BTC/USDT). Multi-pair sweep is a VPS Phase 9 concern.
  * No slippage/fee model — bid-ask is approximated by close-on-bar.
    Phase 10 paper-trade is the slippage gate.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import psycopg
import talib.abstract as ta


REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "crypto-bot" / "freqtrade-config"))
sys.path.insert(0, str(REPO_ROOT / "crypto-bot" / "freqtrade-config" / "hyperopts"))

from freqtrade.optimize.hyperopt_loss.hyperopt_loss_sharpe import SharpeHyperOptLoss  # noqa: E402

from ClaudeOversightHyperopt import STRATEGY_VERSION  # noqa: E402


# ---------------------------------------------------------------------------
# Config — search space matches the strategy's IntParameter / DecimalParameter
# attributes verbatim. Update both sides together.
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class ParamSet:
    buy_ema_fast: int
    buy_ema_slow: int
    buy_adx_threshold: int
    buy_pred_threshold: float
    sell_atr_mult: float


def _sample_params(rng: random.Random) -> ParamSet:
    """Random sample respecting the constraint ema_fast < ema_slow."""
    fast = rng.randint(10, 25)
    # Force slow > fast by sampling slow from [max(fast+5, 40), 80].
    slow = rng.randint(max(fast + 5, 40), 80)
    return ParamSet(
        buy_ema_fast=fast,
        buy_ema_slow=slow,
        buy_adx_threshold=rng.randint(20, 35),
        buy_pred_threshold=round(rng.uniform(0.55, 0.75), 2),
        sell_atr_mult=round(rng.uniform(1.5, 3.0), 2),
    )


# ---------------------------------------------------------------------------
# Postgres / OHLCV access
# ---------------------------------------------------------------------------
def _connect() -> psycopg.Connection:
    return psycopg.connect(
        host=os.environ["POSTGRES_HOST"],
        port=os.environ["POSTGRES_PORT"],
        dbname=os.environ["POSTGRES_DB"],
        user=os.environ["POSTGRES_USER"],
        password=os.environ["POSTGRES_PASSWORD"],
    )


def _load_ohlcv_15m(
    conn: psycopg.Connection, pair: str, start: datetime, end: datetime
) -> pd.DataFrame:
    """Load 1m and resample to 15m. Same shape as freqai_train_smoke._load_resampled."""
    sql = (
        "SELECT ts, open, high, low, close, volume FROM brain.ohlcv "
        "WHERE pair = %s AND tf = '1m' AND ts >= %s AND ts < %s ORDER BY ts"
    )
    with conn.cursor() as cur:
        cur.execute(sql, (pair, start, end))
        rows = cur.fetchall()
    if not rows:
        raise SystemExit(f"No brain.ohlcv 1m rows for {pair} between {start} and {end}")
    df = pd.DataFrame(rows, columns=["ts", "open", "high", "low", "close", "volume"])
    for col in ("open", "high", "low", "close", "volume"):
        df[col] = df[col].astype(float)
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    df = df.set_index("ts")
    rs = (
        df.resample("15min", label="left", closed="left")
        .agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"})
        .dropna(subset=["open", "close"])
    )
    return rs.reset_index().rename(columns={"ts": "date"})


# ---------------------------------------------------------------------------
# Strategy rule application — pure-pandas reproduction of populate_entry_trend
# ---------------------------------------------------------------------------
def _apply_indicators(df: pd.DataFrame, params: ParamSet) -> pd.DataFrame:
    out = df.copy()
    out["ema_fast"] = ta.EMA(out, timeperiod=params.buy_ema_fast)
    out["ema_slow"] = ta.EMA(out, timeperiod=params.buy_ema_slow)
    out["adx14"] = ta.ADX(out, timeperiod=14)
    out["atr14"] = ta.ATR(out, timeperiod=14)
    return out


def _backtest(df: pd.DataFrame, params: ParamSet, starting_balance: float) -> pd.DataFrame:
    """Simulate trades using strategy rules. Returns trades DataFrame with
    profit_abs column (the contract SharpeHyperOptLoss expects).

    Position sizing: full balance per trade (no compounding across concurrent
    trades — single-position spot model matches Phase 3's max_open_trades=1
    perspective for hyperopt purposes; concurrent-position scaling is a
    Phase 9 walk-forward concern, not a parameter-search concern).
    """
    enter_cond = (
        (df["ema_fast"] > df["ema_slow"])
        & (df["adx14"] > params.buy_adx_threshold)
        & (df["close"] > df["ema_fast"])
        & (df["volume"] > 0)
    )
    exit_cond = df["ema_fast"] < df["ema_slow"]

    trades: list[dict] = []
    in_pos = False
    entry_price = 0.0
    entry_time: pd.Timestamp | None = None
    stop_price = 0.0

    closes = df["close"].to_numpy()
    highs = df["high"].to_numpy()
    lows = df["low"].to_numpy()
    atrs = df["atr14"].to_numpy()
    dates = df["date"].to_numpy()
    enters = enter_cond.to_numpy()
    exits = exit_cond.to_numpy()

    for i in range(len(df)):
        # Skip warmup until indicators have values
        if np.isnan(atrs[i]):
            continue
        if not in_pos:
            if enters[i]:
                in_pos = True
                entry_price = float(closes[i])
                entry_time = dates[i]
                stop_price = entry_price - params.sell_atr_mult * float(atrs[i])
        else:
            # Stop hit on intra-bar low
            if lows[i] <= stop_price:
                pnl_pct = (stop_price - entry_price) / entry_price
                trades.append(
                    {
                        "open_date": entry_time,
                        "close_date": dates[i],
                        "profit_pct": pnl_pct,
                        "profit_abs": pnl_pct * starting_balance,
                        "exit_reason": "stop",
                    }
                )
                in_pos = False
                continue
            # Trailing stop: ratchet up only
            new_stop = float(closes[i]) - params.sell_atr_mult * float(atrs[i])
            if new_stop > stop_price:
                stop_price = new_stop
            # Signal exit
            if exits[i]:
                pnl_pct = (float(closes[i]) - entry_price) / entry_price
                trades.append(
                    {
                        "open_date": entry_time,
                        "close_date": dates[i],
                        "profit_pct": pnl_pct,
                        "profit_abs": pnl_pct * starting_balance,
                        "exit_reason": "signal",
                    }
                )
                in_pos = False

    if not trades:
        return pd.DataFrame(columns=["open_date", "close_date", "profit_pct", "profit_abs", "exit_reason"])
    return pd.DataFrame(trades)


# ---------------------------------------------------------------------------
# Metrics + persist
# ---------------------------------------------------------------------------
def _compute_metrics(trades: pd.DataFrame, starting_balance: float) -> dict:
    if trades.empty:
        return {
            "total_trades": 0,
            "win_rate": None,
            "profit_factor": None,
            "max_dd": None,
        }
    wins = trades[trades["profit_abs"] > 0]
    losses = trades[trades["profit_abs"] <= 0]
    win_rate = len(wins) / len(trades)
    gross_win = wins["profit_abs"].sum()
    gross_loss = -losses["profit_abs"].sum()  # positive number
    profit_factor = (gross_win / gross_loss) if gross_loss > 0 else None
    # Equity curve + max drawdown
    equity = starting_balance + trades["profit_abs"].cumsum()
    peak = equity.cummax()
    dd = (equity - peak) / peak
    max_dd = float(dd.min()) if len(dd) else 0.0
    return {
        "total_trades": int(len(trades)),
        "win_rate": float(win_rate),
        "profit_factor": float(profit_factor) if profit_factor is not None else None,
        "max_dd": max_dd,
    }


def _persist_epoch(
    conn: psycopg.Connection,
    *,
    run_id: str,
    epoch: int,
    params: ParamSet,
    loss: float,
    sharpe: float | None,
    metrics: dict,
    timerange_start: datetime,
    timerange_end: datetime,
) -> None:
    sql = (
        "INSERT INTO brain.hyperopt_results "
        "(run_id, epoch, strategy_version, parameters, loss, sharpe, max_dd, "
        " profit_factor, total_trades, win_rate, timerange_start, timerange_end) "
        "VALUES (%s, %s, %s, %s::jsonb, %s, %s, %s, %s, %s, %s, %s, %s)"
    )
    with conn.cursor() as cur:
        cur.execute(
            sql,
            (
                run_id,
                epoch,
                STRATEGY_VERSION,
                json.dumps(asdict(params)),
                float(loss),
                None if sharpe is None else float(sharpe),
                metrics.get("max_dd"),
                metrics.get("profit_factor"),
                metrics.get("total_trades"),
                metrics.get("win_rate"),
                timerange_start,
                timerange_end,
            ),
        )
    conn.commit()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--pair", default="BTC/USDT")
    p.add_argument("--timerange-start", required=True, help="ISO date inclusive")
    p.add_argument("--timerange-end", required=True, help="ISO date exclusive")
    p.add_argument("--epochs", type=int, default=50)
    p.add_argument("--starting-balance", type=float, default=1000.0)
    p.add_argument(
        "--run-id",
        default=None,
        help="Tag for this sweep. Defaults to a timestamp-uuid suffix.",
    )
    p.add_argument("--seed", type=int, default=42)
    args = p.parse_args()

    timerange_start = datetime.fromisoformat(args.timerange_start).replace(tzinfo=timezone.utc)
    timerange_end = datetime.fromisoformat(args.timerange_end).replace(tzinfo=timezone.utc)

    run_id = args.run_id or f"sweep-{datetime.now(tz=timezone.utc).strftime('%Y%m%dT%H%M%S')}-{uuid.uuid4().hex[:6]}"
    rng = random.Random(args.seed)

    print(f"[run_hyperopt] run_id={run_id} pair={args.pair} epochs={args.epochs}")
    print(f"               window=[{timerange_start.date()} -> {timerange_end.date()})")
    print(f"               starting_balance={args.starting_balance}")

    print("[1/3] Loading & resampling OHLCV from Postgres")
    with _connect() as conn:
        df_raw = _load_ohlcv_15m(conn, args.pair, timerange_start, timerange_end)
    print(f"      loaded {len(df_raw):,} 15m bars")

    print("[2/3] Sweeping parameter space")
    best: list[tuple[float, ParamSet, dict]] = []  # min-heap-equivalent: keep top by loss
    with _connect() as conn:
        for epoch in range(1, args.epochs + 1):
            params = _sample_params(rng)
            df_with_ind = _apply_indicators(df_raw, params)
            trades = _backtest(df_with_ind, params, args.starting_balance)
            metrics = _compute_metrics(trades, args.starting_balance)
            loss = SharpeHyperOptLoss.hyperopt_loss_function(
                results=trades,
                min_date=timerange_start,
                max_date=timerange_end,
                starting_balance=args.starting_balance,
            )
            sharpe = -loss if metrics["total_trades"] > 0 else None
            _persist_epoch(
                conn,
                run_id=run_id,
                epoch=epoch,
                params=params,
                loss=loss,
                sharpe=sharpe,
                metrics=metrics,
                timerange_start=timerange_start,
                timerange_end=timerange_end,
            )
            best.append((loss, params, metrics))
            if epoch % max(1, args.epochs // 10) == 0 or epoch == args.epochs:
                print(
                    f"      epoch {epoch:>4}/{args.epochs} loss={loss:+.4f} "
                    f"trades={metrics['total_trades']} "
                    f"sharpe={sharpe if sharpe is None else f'{sharpe:+.2f}'} "
                    f"params={asdict(params)}"
                )

    print("[3/3] Top-3 by loss (lower is better)")
    best.sort(key=lambda x: x[0])
    for rank, (loss, params, metrics) in enumerate(best[:3], 1):
        print(f"  #{rank} loss={loss:+.4f} sharpe={-loss:+.2f}")
        print(f"      params: {asdict(params)}")
        print(f"      metrics: {metrics}")

    print(f"\nrun_id={run_id} — query top-3 from Postgres:")
    print(
        f"  psql trading -c \"SELECT epoch, loss, parameters, total_trades "
        f"FROM brain.hyperopt_results WHERE run_id='{run_id}' "
        f"ORDER BY loss ASC LIMIT 3;\""
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
