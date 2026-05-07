"""Export brain.ohlcv rows to Freqtrade-format Feather files.

Phase 3 verification helper: Freqtrade's backtester reads OHLCV from
``freqtrade-config/data/<exchange>/<PAIR>-<tf>.feather``. Our canonical OHLCV store
is ``brain.ohlcv`` in Postgres. This script bridges the two so we can verify
``ClaudeOversightStrategy`` end-to-end on the real January 2024 BTC/USDT
data we loaded in Phase 2 — no live exchange call needed.

Two modes:

    --tf <freqtrade_tf>            export rows where brain.ohlcv.tf matches exactly
    --resample-from <source_tf>    pull source_tf rows and resample on the fly

Resampling is needed because Phase 2 currently loads only 1m data, and
ClaudeOversightStrategy runs on 15m. The resampler aggregates with the
canonical OHLCV rules (open=first, high=max, low=min, close=last,
volume=sum). Result columns and dtypes match what Freqtrade expects:

    date    datetime64[ns, UTC]   (Freqtrade calls history_load_data,
                                   converts to ms-precision UTC)
    open    float64
    high    float64
    low     float64
    close   float64
    volume  float64

Usage:
    python infra/scripts/export_freqtrade_data.py \
        --pair BTC/USDT \
        --tf 15m \
        --resample-from 1m \
        --start 2024-01-01 \
        --end 2024-02-01 \
        --exchange binance \
        --datadir freqtrade-config/data
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import psycopg


# Map a Freqtrade-style tf string to a pandas resample rule.
_RESAMPLE_RULE = {
    "1m": "1min",
    "3m": "3min",
    "5m": "5min",
    "15m": "15min",
    "30m": "30min",
    "1h": "1h",
    "4h": "4h",
    "1d": "1D",
}


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--pair", required=True, help="e.g. BTC/USDT")
    p.add_argument("--tf", required=True, help="Target timeframe to write (e.g. 15m)")
    p.add_argument(
        "--resample-from",
        default=None,
        help="If set, read this tf from brain.ohlcv and resample to --tf",
    )
    p.add_argument("--start", required=True, help="ISO date, inclusive (e.g. 2024-01-01)")
    p.add_argument("--end", required=True, help="ISO date, exclusive (e.g. 2024-02-01)")
    p.add_argument("--exchange", default="binance")
    p.add_argument(
        "--datadir",
        default="freqtrade-config/data",
        help="Freqtrade data dir (will create <datadir>/<exchange>/)",
    )
    return p.parse_args()


def _connect() -> psycopg.Connection:
    """Open a Postgres connection from POSTGRES_* env vars (hard-fail on missing)."""
    return psycopg.connect(
        host=os.environ["POSTGRES_HOST"],
        port=os.environ["POSTGRES_PORT"],
        dbname=os.environ["POSTGRES_DB"],
        user=os.environ["POSTGRES_USER"],
        password=os.environ["POSTGRES_PASSWORD"],
    )


def _fetch_ohlcv(
    conn: psycopg.Connection,
    pair: str,
    tf: str,
    start: datetime,
    end: datetime,
) -> pd.DataFrame:
    sql = (
        "SELECT ts, open, high, low, close, volume "
        "FROM brain.ohlcv "
        "WHERE pair = %s AND tf = %s AND ts >= %s AND ts < %s "
        "ORDER BY ts"
    )
    with conn.cursor() as cur:
        cur.execute(sql, (pair, tf, start, end))
        rows = cur.fetchall()
    if not rows:
        raise SystemExit(
            f"No rows in brain.ohlcv for pair={pair} tf={tf} "
            f"between {start.isoformat()} and {end.isoformat()}"
        )
    df = pd.DataFrame(rows, columns=["date", "open", "high", "low", "close", "volume"])
    # psycopg returns Decimal for NUMERIC; cast to float64 (Freqtrade expects float)
    for col in ("open", "high", "low", "close", "volume"):
        df[col] = df[col].astype(float)
    df["date"] = pd.to_datetime(df["date"], utc=True)
    return df


def _resample(df: pd.DataFrame, target_tf: str) -> pd.DataFrame:
    rule = _RESAMPLE_RULE.get(target_tf)
    if rule is None:
        raise SystemExit(f"Unsupported target timeframe: {target_tf}")
    df = df.set_index("date")
    out = df.resample(rule, label="left", closed="left").agg(
        {
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last",
            "volume": "sum",
        }
    ).dropna(subset=["open", "close"])
    out = out.reset_index()
    return out


def _write_feather(df: pd.DataFrame, datadir: Path, exchange: str, pair: str, tf: str) -> Path:
    out_dir = datadir / exchange
    out_dir.mkdir(parents=True, exist_ok=True)
    # Freqtrade filename convention: BTC_USDT-15m.feather
    fname = pair.replace("/", "_") + f"-{tf}.feather"
    out_path = out_dir / fname
    df.to_feather(out_path)
    return out_path


def main() -> int:
    args = _parse_args()
    start = datetime.fromisoformat(args.start).replace(tzinfo=timezone.utc)
    end = datetime.fromisoformat(args.end).replace(tzinfo=timezone.utc)
    source_tf = args.resample_from or args.tf

    with _connect() as conn:
        df = _fetch_ohlcv(conn, args.pair, source_tf, start, end)

    if args.resample_from is not None and args.resample_from != args.tf:
        df = _resample(df, args.tf)

    out_path = _write_feather(df, Path(args.datadir), args.exchange, args.pair, args.tf)
    print(
        f"wrote {len(df):,} {args.tf} candles to {out_path} "
        f"(range: {df['date'].min()} -> {df['date'].max()})"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
