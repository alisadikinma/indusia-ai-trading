"""Phase 7 verification harness — train ClaudeOversightModel on real Postgres data.

Sidesteps Freqtrade's CLI (which wants Binance loadMarkets — geofenced from
this dev box). Builds the data_dictionary FreqAI's pipeline would build,
calls model.fit() directly, and verifies brain.freqai_history is populated
with a real AUC value.

Usage:
    set -a; source .env; set +a
    python -m infra.scripts.freqai_train_smoke --pair BTC/USDT --tf 15m \\
        --train-start 2023-01-01 --train-end 2024-09-30 \\
        --test-start 2024-10-01 --test-end 2024-12-31

This proves Phase 7 works end-to-end on real data: real Postgres data
in, real XGBoost training, real AUC out, real telemetry row written.
"""
from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import psycopg
import talib.abstract as ta


# Add freqtrade-config to sys.path so we can import the model.
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "crypto-bot" / "freqtrade-config"))


@dataclass
class MinimalDataKitchen:
    """Minimal FreqaiDataKitchen-like stub — only fields our model touches."""
    pair: str
    full_path: Path = Path("/tmp/freqai-smoke")


def _connect() -> psycopg.Connection:
    return psycopg.connect(
        host=os.environ["POSTGRES_HOST"],
        port=os.environ["POSTGRES_PORT"],
        dbname=os.environ["POSTGRES_DB"],
        user=os.environ["POSTGRES_USER"],
        password=os.environ["POSTGRES_PASSWORD"],
    )


def _load_resampled(
    conn: psycopg.Connection,
    pair: str,
    target_tf: str,
    start: datetime,
    end: datetime,
) -> pd.DataFrame:
    """Load 1m from Postgres and resample to target_tf."""
    sql = (
        "SELECT ts, open, high, low, close, volume FROM brain.ohlcv "
        "WHERE pair = %s AND tf = '1m' AND ts >= %s AND ts < %s ORDER BY ts"
    )
    with conn.cursor() as cur:
        cur.execute(sql, (pair, start, end))
        rows = cur.fetchall()
    if not rows:
        raise SystemExit(
            f"No brain.ohlcv 1m rows for {pair} between {start} and {end}"
        )
    df = pd.DataFrame(rows, columns=["ts", "open", "high", "low", "close", "volume"])
    for col in ("open", "high", "low", "close", "volume"):
        df[col] = df[col].astype(float)
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    df = df.set_index("ts")

    rule_map = {"1m": "1min", "5m": "5min", "15m": "15min", "1h": "1h", "4h": "4h", "1d": "1D"}
    rule = rule_map[target_tf]
    rs = df.resample(rule, label="left", closed="left").agg({
        "open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum",
    }).dropna(subset=["open", "close"])
    return rs.reset_index().rename(columns={"ts": "date"})


def _build_features(df: pd.DataFrame) -> pd.DataFrame:
    """Compute the same features ClaudeOversightStrategy's feature_engineering hooks would."""
    out = df.copy()
    # Indicators
    for period in (10, 14, 20, 50):
        out[f"%-rsi_{period}"] = ta.RSI(out, timeperiod=period)
        out[f"%-adx_{period}"] = ta.ADX(out, timeperiod=period)
        ema = ta.EMA(out, timeperiod=period)
        out[f"%-ema_dist_{period}"] = (out["close"] - ema) / out["close"]
    # Volume z-score over 96 bars (~24h on 15m)
    vol_mean = out["volume"].rolling(96).mean()
    vol_std = out["volume"].rolling(96).std()
    out["%-volume_z_24h"] = (out["volume"] - vol_mean) / vol_std
    # Multi-horizon returns + volatility (15m bars per hour = 4)
    for h in (1, 4, 12, 24):
        bars = h * 4
        out[f"%-return_{h}h"] = out["close"].pct_change(periods=bars)
        if h <= 12:
            out[f"%-volatility_{h}h"] = out["close"].pct_change().rolling(bars).std()
    return out


def _set_target(df: pd.DataFrame, horizon_bars: int = 16, threshold: float = 0.02) -> pd.DataFrame:
    """P(close[t+horizon] > close[t] * (1 + threshold)) binary target."""
    out = df.copy()
    future = out["close"].shift(-horizon_bars) / out["close"] - 1
    out["&-prediction"] = (future > threshold).astype(int)
    return out


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--pair", default="BTC/USDT")
    p.add_argument("--tf", default="15m")
    p.add_argument("--train-start", required=True, help="ISO date inclusive")
    p.add_argument("--train-end", required=True, help="ISO date exclusive")
    p.add_argument("--test-start", required=True, help="ISO date inclusive")
    p.add_argument("--test-end", required=True, help="ISO date exclusive")
    args = p.parse_args()

    train_start = datetime.fromisoformat(args.train_start).replace(tzinfo=timezone.utc)
    train_end = datetime.fromisoformat(args.train_end).replace(tzinfo=timezone.utc)
    test_start = datetime.fromisoformat(args.test_start).replace(tzinfo=timezone.utc)
    test_end = datetime.fromisoformat(args.test_end).replace(tzinfo=timezone.utc)

    print(f"[1/5] Loading 1m → {args.tf} for train window {train_start.date()} → {train_end.date()}")
    with _connect() as conn:
        train_df = _load_resampled(conn, args.pair, args.tf, train_start, train_end)
        print(f"      train_df rows after resample: {len(train_df):,}")

        print(f"[2/5] Loading 1m → {args.tf} for test window {test_start.date()} → {test_end.date()}")
        test_df = _load_resampled(conn, args.pair, args.tf, test_start, test_end)
        print(f"      test_df rows after resample: {len(test_df):,}")

    print("[3/5] Building features + target")
    train_full = _set_target(_build_features(train_df))
    test_full = _set_target(_build_features(test_df))

    feat_cols = [c for c in train_full.columns if c.startswith("%-")]
    target_col = "&-prediction"

    # Drop warmup rows (first ~100 bars have NaN indicators) and trailing rows
    # without future target
    train_clean = train_full.dropna(subset=feat_cols + [target_col]).copy()
    test_clean = test_full.dropna(subset=feat_cols + [target_col]).copy()

    print(f"      train_clean rows after dropna: {len(train_clean):,}")
    print(f"      test_clean  rows after dropna: {len(test_clean):,}")
    print(f"      features: {len(feat_cols)} cols")
    print(f"      class balance train: pos={(train_clean[target_col]==1).sum():,} "
          f"neg={(train_clean[target_col]==0).sum():,}")

    if len(train_clean) < 500:
        raise SystemExit(
            f"Insufficient training rows ({len(train_clean)}). Load more data first."
        )

    print("[4/5] Constructing FreqAI data_dictionary + dk; calling model.fit()")
    data_dictionary = {
        "train_features": train_clean[feat_cols],
        "train_labels": train_clean[[target_col]],
        "test_features": test_clean[feat_cols],
        "test_labels": test_clean[[target_col]],
    }
    dk = MinimalDataKitchen(pair=args.pair)

    # Import the model AFTER sys.path setup
    from freqaimodels.ClaudeOversightModel import ClaudeOversightModel

    user_data_dir = REPO_ROOT / "user_data"
    user_data_dir.mkdir(exist_ok=True)
    cfg = {
        "user_data_dir": user_data_dir,
        "timeframe": args.tf,
        "exchange": {
            "name": "binance",
            "pair_whitelist": [args.pair],
        },
        "runmode": "backtest",
        "freqai": {
            "enabled": True,
            "identifier": "claude-oversight-smoke",
            "train_period_days": (train_end - train_start).days,
            "backtest_period_days": (test_end - test_start).days,
            "live_retrain_hours": 24,
            "feature_parameters": {
                "include_corr_pairlist": [],
                "label_period_candles": 16,
                "include_shifted_candles": 2,
                "DI_threshold": 0.9,
                "weight_factor": 0.9,
                "principal_component_analysis": False,
                "use_SVM_to_remove_outliers": False,
                "stratify_training_data": 0,
                "indicator_periods_candles": [10, 20],
            },
            "data_split_parameters": {
                "test_size": 0.25,
                "shuffle": False,
                "random_state": 42,
            },
            "model_training_parameters": {
                "n_estimators": 200,
                "max_depth": 6,
                "learning_rate": 0.05,
                "verbosity": 0,
                "n_jobs": -1,
            },
        },
    }
    model_obj = ClaudeOversightModel(config=cfg)
    trained = model_obj.fit(data_dictionary, dk)
    print(f"      trained model: {type(trained).__name__}")

    print("[5/5] Verifying brain.freqai_history population")
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT id, retrained_at, pair, tf, train_window_days, train_rows, auc, "
            "       jsonb_pretty(feature_importance), model_path "
            "FROM brain.freqai_history ORDER BY retrained_at DESC LIMIT 1"
        )
        row = cur.fetchone()
    if row is None:
        print("      WARNING: no row written. Check Iron-Law-3-exception logs above.")
        return 1
    print(f"      id={row[0]} retrained_at={row[1]} pair={row[2]} tf={row[3]}")
    print(f"      train_window_days={row[4]} train_rows={row[5]:,} auc={row[6]}")
    print(f"      top features by importance:")
    print(row[7][:500])

    return 0


if __name__ == "__main__":
    sys.exit(main())
