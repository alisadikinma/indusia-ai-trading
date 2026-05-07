"""Binance Vision monthly OHLCV bulk loader.

Downloads monthly kline zips from data.binance.vision, verifies the published
SHA256 CHECKSUM, parses the 12-column CSV into a polars DataFrame with the
canonical [ts, open, high, low, close, volume] schema, and bulk-inserts into
the brain.ohlcv hypertable using the staging-table + ON CONFLICT DO NOTHING
pattern (true COPY does not support upsert directly).

Symbol naming: Binance Vision uses concatenated symbols (e.g. BTCUSDT). The
canonical pair name in our database is slash-separated (BTC/USDT). The
translation happens at insert time inside bulk_load(); the public methods
download_month and parse_zip operate on the Binance Vision native form.

Dual ms / microsecond timestamp handling
----------------------------------------
On 2025-01-01 Binance Vision migrated all Spot kline data from millisecond
(13-digit) to microsecond (16-digit) integer timestamps in the first column.
A naive parser hard-coded to ms will silently produce year ~50,000 AD
timestamps when fed post-2025 files, and a parser hard-coded to μs will
produce year 1970 timestamps when fed pre-2025 files. ``parse_zip()``
auto-detects per-row by integer magnitude (μs values are ≥ 10^15 for any
post-1970 date — comfortably above the maximum plausible ms epoch of ~4.7×10^12
for years up to ~21000 AD) and dispatches to the correct ``time_unit``. Both
canonicalize to a tz-aware UTC ``Datetime[ns]`` polars column with no
sub-second drift artefacts when stitching across the boundary.
Source: NotebookLM citation 17 — github.com/binance/binance-public-data
(also references/crypto/exchange-microstructure.md Topic 5).

Env contract:
- BINANCE_VISION_CACHE_DIR is consulted when no explicit cache_dir is passed
  to BinanceVisionLoader. If unset and no cache_dir is given, falls back to
  ``infra/data_loader/.cache/binance_vision`` under the repo root.
- POSTGRES_{HOST,PORT,USER,PASSWORD,DB} are required for bulk_load(). Missing
  env vars surface as KeyError (Iron Law: no silent fallback).

CLI:
    python -m infra.data_loader.binance_vision \
        --symbol BTCUSDT --tf 1m --start 2024-01-01 --end 2024-01-31
"""
from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import hashlib
import io
import logging
import os
import sys
import zipfile
from dataclasses import dataclass
from pathlib import Path

import httpx
import polars as pl
import psycopg

logger = logging.getLogger(__name__)

BINANCE_VISION_BASE = "https://data.binance.vision/data/spot/monthly/klines"
DEFAULT_MAX_CONCURRENT_DOWNLOADS = 4
HTTP_TIMEOUT_S = 60.0

# Binance Vision kline CSV is headerless; column order is documented at
# https://github.com/binance/binance-public-data/#klines
_BINANCE_KLINE_COLS = [
    "open_time_ms",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "close_time_ms",
    "quote_volume",
    "n_trades",
    "taker_buy_base",
    "taker_buy_quote",
    "ignore",
]

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_DEFAULT_CACHE_DIR = REPO_ROOT / "infra" / "data_loader" / ".cache" / "binance_vision"

# Dual ms/μs detection threshold (see module docstring "Dual ms / microsecond
# timestamp handling"). Any value ≥ this is interpreted as microseconds; below
# is milliseconds. 10^14 ms ≈ year 5138 (impossible for spot kline data); 10^14
# μs ≈ year 1973 (impossible for Binance, founded 2017). Wide safety margin.
_MS_VS_US_THRESHOLD = 10**14


@dataclass(frozen=True)
class _MonthRef:
    symbol: str
    tf: str
    year: int
    month: int

    @property
    def filename(self) -> str:
        return f"{self.symbol}-{self.tf}-{self.year:04d}-{self.month:02d}.zip"

    @property
    def url(self) -> str:
        return f"{BINANCE_VISION_BASE}/{self.symbol}/{self.tf}/{self.filename}"

    @property
    def checksum_url(self) -> str:
        return self.url + ".CHECKSUM"


def _symbol_to_pair(symbol: str) -> str:
    """Translate BTCUSDT -> BTC/USDT.

    Binance Vision spot symbols are always {BASE}{QUOTE} where QUOTE is one of
    a small known set. We split on the longest matching quote suffix.
    """
    known_quotes = (
        "USDT", "BUSD", "USDC", "FDUSD", "TUSD", "USD", "BTC", "ETH", "BNB", "EUR", "TRY"
    )
    s = symbol.upper()
    for q in known_quotes:
        if s.endswith(q) and len(s) > len(q):
            return f"{s[:-len(q)]}/{q}"
    raise ValueError(f"Cannot infer base/quote split for symbol {symbol!r}")


def _resolve_cache_dir(cache_dir: Path | None) -> Path:
    if cache_dir is not None:
        return cache_dir
    env = os.environ.get("BINANCE_VISION_CACHE_DIR")
    if env:
        return Path(env)
    return _DEFAULT_CACHE_DIR


def _iter_months(start: dt.date, end: dt.date):
    """Yield (year, month) pairs covering [start, end] inclusive."""
    if end < start:
        raise ValueError(f"end {end} is before start {start}")
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        yield y, m
        if m == 12:
            y, m = y + 1, 1
        else:
            m += 1


class BinanceVisionLoader:
    """Bulk loader for Binance Vision monthly klines."""

    def __init__(
        self,
        cache_dir: Path | None = None,
        max_concurrent: int = DEFAULT_MAX_CONCURRENT_DOWNLOADS,
    ) -> None:
        self.cache_dir = _resolve_cache_dir(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._max_concurrent = max_concurrent

    # ------------------------------------------------------------------ paths

    def _local_path(self, ref: _MonthRef) -> Path:
        d = self.cache_dir / ref.symbol / ref.tf
        d.mkdir(parents=True, exist_ok=True)
        return d / ref.filename

    # -------------------------------------------------------------- checksum

    @staticmethod
    def _parse_checksum(text: str) -> str:
        # Format: "<hex sha256>  filename"
        token = text.strip().split()
        if not token:
            raise ValueError(f"Empty CHECKSUM body: {text!r}")
        return token[0].lower()

    @staticmethod
    def _sha256_file(path: Path) -> str:
        h = hashlib.sha256()
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest().lower()

    # ------------------------------------------------------------- download

    def download_month(
        self, symbol: str, tf: str, year: int, month: int
    ) -> Path:
        """Download one monthly zip + CHECKSUM, verify SHA256, return local path.

        Idempotent: if the file is already cached and matches the published
        checksum, returns immediately without re-downloading.
        """
        ref = _MonthRef(symbol=symbol.upper(), tf=tf, year=year, month=month)
        local = self._local_path(ref)

        # 1. Always fetch the checksum (small, ~80 bytes) so we can verify cache.
        with httpx.Client(timeout=HTTP_TIMEOUT_S, follow_redirects=True) as client:
            r_cs = client.get(ref.checksum_url)
            r_cs.raise_for_status()
            expected = self._parse_checksum(r_cs.text)

            # 2. Cache hit?
            if local.exists() and self._sha256_file(local) == expected:
                logger.debug("cache hit: %s", local)
                return local

            # 3. Download zip (real bytes, no stub).
            logger.info("downloading %s", ref.url)
            with client.stream("GET", ref.url) as r:
                r.raise_for_status()
                tmp = local.with_suffix(local.suffix + ".part")
                with tmp.open("wb") as f:
                    for chunk in r.iter_bytes(chunk_size=1 << 20):
                        f.write(chunk)
                actual = self._sha256_file(tmp)
                if actual != expected:
                    tmp.unlink(missing_ok=True)
                    raise RuntimeError(
                        f"checksum mismatch for {ref.filename}: "
                        f"expected {expected}, got {actual}"
                    )
                tmp.replace(local)
        return local

    async def download_month_async(
        self,
        client: httpx.AsyncClient,
        sem: asyncio.Semaphore,
        ref: _MonthRef,
    ) -> Path:
        async with sem:
            local = self._local_path(ref)
            r_cs = await client.get(ref.checksum_url)
            r_cs.raise_for_status()
            expected = self._parse_checksum(r_cs.text)

            if local.exists() and self._sha256_file(local) == expected:
                return local

            logger.info("downloading %s", ref.url)
            async with client.stream("GET", ref.url) as r:
                r.raise_for_status()
                tmp = local.with_suffix(local.suffix + ".part")
                with tmp.open("wb") as f:
                    async for chunk in r.aiter_bytes(chunk_size=1 << 20):
                        f.write(chunk)
            actual = self._sha256_file(tmp)
            if actual != expected:
                tmp.unlink(missing_ok=True)
                raise RuntimeError(
                    f"checksum mismatch for {ref.filename}: "
                    f"expected {expected}, got {actual}"
                )
            tmp.replace(local)
            return local

    # ------------------------------------------------------------------ parse

    def parse_zip(self, zip_path: Path) -> pl.DataFrame:
        """Open a Binance Vision monthly zip and return canonical OHLCV."""
        with zipfile.ZipFile(zip_path) as zf:
            csv_names = [n for n in zf.namelist() if n.endswith(".csv")]
            if not csv_names:
                raise ValueError(f"{zip_path}: no CSV inside zip")
            with zf.open(csv_names[0]) as f:
                raw = f.read()

        df = pl.read_csv(
            io.BytesIO(raw),
            has_header=False,
            new_columns=_BINANCE_KLINE_COLS,
            schema_overrides={
                "open_time_ms": pl.Int64,
                "open": pl.Float64,
                "high": pl.Float64,
                "low": pl.Float64,
                "close": pl.Float64,
                "volume": pl.Float64,
                "close_time_ms": pl.Int64,
                "quote_volume": pl.Float64,
                "n_trades": pl.Int64,
                "taker_buy_base": pl.Float64,
                "taker_buy_quote": pl.Float64,
                "ignore": pl.Float64,
            },
        )
        # Dual ms / μs timestamp handling (see module docstring). Per-row
        # detection by magnitude: values ≥ _MS_VS_US_THRESHOLD are μs, else ms.
        # Robust to a single zip whose rows are all-ms (pre-2025), all-μs
        # (post-2025), and the theoretical mixed case (Binance switched
        # exactly on 2025-01-01 so a same-month file should not actually mix,
        # but the logic remains correct if it ever does).
        threshold = _MS_VS_US_THRESHOLD
        df = df.with_columns(
            pl.when(pl.col("open_time_ms") >= threshold)
            .then(
                pl.from_epoch(pl.col("open_time_ms"), time_unit="us")
            )
            .otherwise(
                pl.from_epoch(pl.col("open_time_ms"), time_unit="ms")
            )
            .dt.replace_time_zone("UTC")
            .alias("ts")
        )
        return df.select(["ts", "open", "high", "low", "close", "volume"])

    # -------------------------------------------------------------- bulk_load

    def bulk_load(
        self,
        symbol: str,
        tf: str,
        start: dt.date,
        end: dt.date,
    ) -> int:
        """Download (cached) -> parse -> insert all months in [start, end].

        Returns net number of rows inserted across all months (after
        ON CONFLICT DO NOTHING). Re-runs are idempotent.

        DB params come from the standard POSTGRES_* env vars; missing values
        raise KeyError (no silent fallback).
        """
        symbol = symbol.upper()
        pair = _symbol_to_pair(symbol)
        refs = [
            _MonthRef(symbol=symbol, tf=tf, year=y, month=m)
            for y, m in _iter_months(start, end)
        ]
        if not refs:
            return 0

        # 1. Download (concurrently) — cached after first run.
        async def _download_all() -> list[Path]:
            sem = asyncio.Semaphore(self._max_concurrent)
            async with httpx.AsyncClient(
                timeout=HTTP_TIMEOUT_S, follow_redirects=True, http2=True
            ) as client:
                tasks = [self.download_month_async(client, sem, r) for r in refs]
                return await asyncio.gather(*tasks)

        local_paths = asyncio.run(_download_all())

        # 2. Connect to Postgres, COPY into staging temp, INSERT ... ON CONFLICT.
        dsn = (
            f"postgresql://{os.environ['POSTGRES_USER']}:"
            f"{os.environ['POSTGRES_PASSWORD']}@"
            f"{os.environ['POSTGRES_HOST']}:"
            f"{os.environ['POSTGRES_PORT']}/"
            f"{os.environ['POSTGRES_DB']}"
        )
        total_inserted = 0
        with psycopg.connect(dsn) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    CREATE TEMP TABLE _stage_ohlcv (
                        ts TIMESTAMPTZ,
                        open NUMERIC,
                        high NUMERIC,
                        low NUMERIC,
                        close NUMERIC,
                        volume NUMERIC
                    ) ON COMMIT DROP;
                    """
                )
            for ref, path in zip(refs, local_paths, strict=True):
                df = self.parse_zip(path)
                inserted = self._copy_and_upsert(conn, df, pair, tf)
                total_inserted += inserted
                logger.info(
                    "loaded %s rows for %s %s %04d-%02d (net inserted=%d)",
                    df.height, pair, tf, ref.year, ref.month, inserted,
                )
            conn.commit()
        return total_inserted

    @staticmethod
    def _copy_and_upsert(
        conn: psycopg.Connection,
        df: pl.DataFrame,
        pair: str,
        tf: str,
    ) -> int:
        """COPY a DataFrame into a temp staging table, then upsert into brain.ohlcv.

        Returns rows inserted (i.e. rows in df minus rows skipped via ON CONFLICT).
        """
        with conn.cursor() as cur:
            # Truncate staging from any prior month.
            cur.execute("TRUNCATE _stage_ohlcv;")
            with cur.copy(
                "COPY _stage_ohlcv (ts, open, high, low, close, volume) "
                "FROM STDIN WITH (FORMAT CSV)"
            ) as cp:
                # Stream df rows as CSV bytes — avoids materialising a giant string.
                # polars write_csv with no header is the fastest path.
                buf = io.BytesIO()
                df.write_csv(buf, include_header=False)
                cp.write(buf.getvalue())
            cur.execute(
                """
                INSERT INTO brain.ohlcv (pair, tf, ts, open, high, low, close, volume, source)
                SELECT %s, %s, ts, open, high, low, close, volume, 'binance_vision'
                FROM _stage_ohlcv
                ON CONFLICT (pair, tf, ts) DO NOTHING;
                """,
                (pair, tf),
            )
            return cur.rowcount


# ---------------------------------------------------------------------- CLI


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m infra.data_loader.binance_vision",
        description="Bulk-load Binance Vision monthly klines into brain.ohlcv.",
    )
    p.add_argument("--symbol", required=True, help="e.g. BTCUSDT")
    p.add_argument("--tf", required=True, help="e.g. 1m, 5m, 1h")
    p.add_argument("--start", required=True, help="YYYY-MM-DD (inclusive)")
    p.add_argument("--end", required=True, help="YYYY-MM-DD (inclusive)")
    p.add_argument("--cache-dir", default=None)
    return p


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s"
    )
    args = _build_parser().parse_args(argv)
    loader = BinanceVisionLoader(
        cache_dir=Path(args.cache_dir) if args.cache_dir else None
    )
    inserted = loader.bulk_load(
        symbol=args.symbol,
        tf=args.tf,
        start=dt.date.fromisoformat(args.start),
        end=dt.date.fromisoformat(args.end),
    )
    print(f"inserted_rows={inserted}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
