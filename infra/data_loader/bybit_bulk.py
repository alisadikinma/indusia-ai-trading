"""Bybit public archive bulk OHLCV loader.

Loads Bybit's public historical OHLCV (kline-for-MetaTrader-4 style) data
from `https://public.bybit.com/kline_for_metatrader4/<SYMBOL>/<YEAR>/`.
Files are gzipped CSV named:

    <SYMBOL>_<INTERVAL_MIN>_<YYYY-MM-DD>_<YYYY-MM-DD>.csv.gz

Each CSV is header-less and uses 8 columns:

    Date, Time, Open, High, Low, Close, Volume, Tickvol

Where ``Date`` is ``YYYY.MM.DD`` and ``Time`` is ``HH:MM`` UTC.

Coverage horizon (per project Phase 0 spec, cross-referenced from the
NotebookLM exchange-microstructure research):
* inverse contracts (e.g. ``BTCUSD``)  → from ~November 2019
* linear contracts  (e.g. ``BTCUSDT``) → from ~May 2020

Symbol → category disambiguation is left to the caller; the archive layout
flattens both inverse and linear under the same MT4-export tree.

Pair encoding (project standard) — schema collision callout
-----------------------------------------------------------
The current ``brain.ohlcv`` table has primary key ``(pair, tf, ts)`` (see
``infra/migrations/000_bootstrap_schemas.sql``). Same-named pairs from
DIFFERENT venues would therefore collide on insert.

Workaround for Phase 0 of the post-research backtest data extension: this
loader writes Bybit pairs with an ``@bybit`` suffix
(e.g. ``BTC/USDT@bybit``, ``BTC/USD@bybit``) so PK uniqueness is preserved.

Note: ``infra/data_loader/binance_vision.py`` (the older loader) intentionally
keeps writing pairs WITHOUT a venue suffix (``BTC/USDT``) for backwards
compatibility with already-loaded Binance Vision data. Mixing suffixed +
unsuffixed encodings within the same table is the asymmetry this comment
documents.

TODO(migration 004_brain_ohlcv_source_in_pk.sql): add ``source`` to the
primary key so ``(pair, tf, ts, source)`` becomes globally unique. At that
point all venue loaders should write the canonical pair (no suffix) and rely
on the ``source`` column for disambiguation. Migration is OUT OF SCOPE for
this loader and will be authored by a later phase.

Env contract
------------
- ``BYBIT_ARCHIVE_CACHE_DIR`` is consulted when no ``cache_dir`` is passed;
  falls back to ``infra/data_loader/.cache/bybit_archive``.
- ``POSTGRES_{HOST,PORT,USER,PASSWORD,DB}`` are required for ``bulk_load()``;
  missing values raise ``KeyError`` (Iron Law: no silent fallback).

CLI
---

    python -m infra.data_loader.bybit_bulk \
        --symbol BTCUSD --pair BTC/USD --tf 1m --year 2019
"""
from __future__ import annotations

import argparse
import gzip
import io
import logging
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path

import httpx
import polars as pl
import psycopg

logger = logging.getLogger(__name__)

BYBIT_ARCHIVE_BASE = "https://public.bybit.com/kline_for_metatrader4"
HTTP_TIMEOUT_S = 90.0

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_DEFAULT_CACHE_DIR = REPO_ROOT / "infra" / "data_loader" / ".cache" / "bybit_archive"

_TF_TO_BYBIT_MINUTES: dict[str, int] = {
    "1m": 1,
    "5m": 5,
    "15m": 15,
    "30m": 30,
    "1h": 60,
    "4h": 240,
    "1d": 1440,
}

_BYBIT_MT4_COLS = (
    "date_str",
    "time_str",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "tickvol",
)

# Apache-autoindex anchors look like:
#   <a href="BTCUSD_1_2019-11-01_2019-11-30.csv.gz">BTCUSD_1_...</a>
_HREF_RE = re.compile(r'href="([^"?][^"]*\.csv\.gz)"', re.IGNORECASE)
_FILENAME_RE = re.compile(
    r"^(?P<symbol>[A-Z0-9]+)_(?P<minutes>\d+)_"
    r"(?P<start>\d{4}-\d{2}-\d{2})_(?P<end>\d{4}-\d{2}-\d{2})\.csv\.gz$"
)


def _resolve_cache_dir(cache_dir: Path | None) -> Path:
    if cache_dir is not None:
        return cache_dir
    env = os.environ.get("BYBIT_ARCHIVE_CACHE_DIR")
    if env:
        return Path(env)
    return _DEFAULT_CACHE_DIR


def _bybit_minutes(tf: str) -> int:
    try:
        return _TF_TO_BYBIT_MINUTES[tf]
    except KeyError as e:
        raise ValueError(
            f"Unsupported timeframe {tf!r}. Bybit MT4 archive supports "
            f"{sorted(_TF_TO_BYBIT_MINUTES)}."
        ) from e


@dataclass(frozen=True)
class BybitArchiveFile:
    symbol: str
    minutes: int
    start_date: str  # YYYY-MM-DD
    end_date: str
    url: str

    @property
    def filename(self) -> str:
        return f"{self.symbol}_{self.minutes}_{self.start_date}_{self.end_date}.csv.gz"


class BybitBulkLoader:
    """Bulk loader for Bybit's public.bybit.com kline_for_metatrader4 archive."""

    def __init__(self, cache_dir: Path | None = None) -> None:
        self.cache_dir = _resolve_cache_dir(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    # -------------------------------------------------------- listing + dl

    def _archive_dir_url(self, symbol: str, year: int) -> str:
        return f"{BYBIT_ARCHIVE_BASE}/{symbol}/{year:04d}/"

    def list_monthly_files(
        self,
        *,
        symbol: str,
        year: int,
        tf: str | None = None,
    ) -> list[BybitArchiveFile]:
        """Scrape the Apache autoindex for ``<SYMBOL>/<YEAR>/`` and return the
        list of available monthly CSV.gz files. If ``tf`` is supplied, filter
        to the matching minute interval.
        """
        url = self._archive_dir_url(symbol, year)
        with httpx.Client(timeout=HTTP_TIMEOUT_S, follow_redirects=True) as client:
            r = client.get(url)
            r.raise_for_status()
            html = r.text

        out: list[BybitArchiveFile] = []
        wanted_minutes = _bybit_minutes(tf) if tf else None
        for href in _HREF_RE.findall(html):
            m = _FILENAME_RE.match(href)
            if not m:
                continue
            minutes = int(m.group("minutes"))
            if wanted_minutes is not None and minutes != wanted_minutes:
                continue
            out.append(
                BybitArchiveFile(
                    symbol=m.group("symbol"),
                    minutes=minutes,
                    start_date=m.group("start"),
                    end_date=m.group("end"),
                    url=url + href,
                )
            )
        out.sort(key=lambda f: (f.start_date, f.minutes))
        return out

    def download_file(self, url: str, dest: Path) -> Path:
        """Download a single .csv.gz with simple cache (size > 0 = hit)."""
        if dest.exists() and dest.stat().st_size > 0:
            logger.info("bybit cache hit: %s", dest)
            return dest
        dest.parent.mkdir(parents=True, exist_ok=True)
        logger.info("downloading %s -> %s", url, dest)
        with httpx.Client(timeout=HTTP_TIMEOUT_S, follow_redirects=True) as client:
            with client.stream("GET", url) as r:
                r.raise_for_status()
                tmp = dest.with_suffix(dest.suffix + ".part")
                with tmp.open("wb") as f:
                    for chunk in r.iter_bytes(chunk_size=1 << 20):
                        f.write(chunk)
                tmp.replace(dest)
        return dest

    # ------------------------------------------------------------------ parse

    def parse_csv_gz_bytes(
        self,
        raw_gz: bytes,
        *,
        pair: str,
        tf: str,
    ) -> pl.DataFrame:
        """Parse a gzipped Bybit MT4-style CSV (header-less, 8 cols) into the
        canonical brain.ohlcv-shaped DataFrame.

        Output rows carry ``pair = f"{pair}@bybit"`` (PK collision workaround).
        """
        if not raw_gz:
            raise ValueError("Empty Bybit archive bytes")

        try:
            csv_bytes = gzip.decompress(raw_gz)
        except OSError as e:
            raise ValueError(f"Not a valid gzip stream: {e}") from e
        if not csv_bytes.strip():
            raise ValueError("Decompressed Bybit CSV is empty")

        df = pl.read_csv(
            io.BytesIO(csv_bytes),
            has_header=False,
            new_columns=list(_BYBIT_MT4_COLS),
            schema_overrides={
                "date_str": pl.String,
                "time_str": pl.String,
                "open": pl.Float64,
                "high": pl.Float64,
                "low": pl.Float64,
                "close": pl.Float64,
                "volume": pl.Float64,
                "tickvol": pl.Float64,
            },
        )

        # Date is YYYY.MM.DD, Time is HH:MM. Combine -> tz-aware UTC datetime.
        suffixed_pair = f"{pair}@bybit"
        df = df.with_columns(
            (pl.col("date_str") + pl.lit(" ") + pl.col("time_str"))
            .str.strptime(pl.Datetime("us"), "%Y.%m.%d %H:%M", strict=True)
            .dt.replace_time_zone("UTC")
            .alias("ts"),
            pl.lit(suffixed_pair).alias("pair"),
            pl.lit(tf).alias("tf"),
            pl.lit("bybit").alias("source"),
        )

        return df.select(
            ["pair", "tf", "ts", "open", "high", "low", "close", "volume", "source"]
        )

    def parse_local_gz(
        self,
        path: Path,
        *,
        pair: str,
        tf: str,
    ) -> pl.DataFrame:
        """Read a local .csv.gz off disk and return parsed canonical rows."""
        return self.parse_csv_gz_bytes(path.read_bytes(), pair=pair, tf=tf)

    # ----------------------------------------------------------- bulk_load

    def bulk_load(
        self,
        *,
        symbol: str,
        pair: str,
        tf: str,
        year: int,
    ) -> int:
        """Discover → download → parse → INSERT all months of ``symbol`` for
        ``year`` at ``tf`` interval into ``brain.ohlcv``.

        Returns net rows inserted (after ON CONFLICT DO NOTHING). Idempotent.
        """
        files = self.list_monthly_files(symbol=symbol, year=year, tf=tf)
        if not files:
            logger.warning(
                "bybit archive: no files matched symbol=%s year=%s tf=%s",
                symbol, year, tf,
            )
            return 0

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
                    CREATE TEMP TABLE _stage_bybit_ohlcv (
                        pair   TEXT,
                        tf     TEXT,
                        ts     TIMESTAMPTZ,
                        open   NUMERIC,
                        high   NUMERIC,
                        low    NUMERIC,
                        close  NUMERIC,
                        volume NUMERIC,
                        source TEXT
                    ) ON COMMIT DROP;
                    """
                )
            for f in files:
                local = self.download_file(
                    f.url, self.cache_dir / symbol / str(year) / f.filename
                )
                df = self.parse_local_gz(local, pair=pair, tf=tf)
                if df.is_empty():
                    logger.warning("bybit: 0 rows in %s", f.filename)
                    continue
                with conn.cursor() as cur:
                    cur.execute("TRUNCATE _stage_bybit_ohlcv;")
                    with cur.copy(
                        "COPY _stage_bybit_ohlcv "
                        "(pair, tf, ts, open, high, low, close, volume, source) "
                        "FROM STDIN WITH (FORMAT CSV)"
                    ) as cp:
                        buf = io.BytesIO()
                        df.write_csv(buf, include_header=False)
                        cp.write(buf.getvalue())
                    cur.execute(
                        """
                        INSERT INTO brain.ohlcv
                            (pair, tf, ts, open, high, low, close, volume, source)
                        SELECT pair, tf, ts, open, high, low, close, volume, source
                        FROM _stage_bybit_ohlcv
                        ON CONFLICT (pair, tf, ts) DO NOTHING;
                        """
                    )
                    inserted = cur.rowcount
                    total_inserted += inserted
                    logger.info(
                        "bybit: %s rows in %s, %s net inserted",
                        df.height, f.filename, inserted,
                    )
            conn.commit()
        return total_inserted


# ---------------------------------------------------------------------- CLI


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m infra.data_loader.bybit_bulk",
        description="Bulk-load Bybit MT4 archive monthly klines into brain.ohlcv.",
    )
    p.add_argument("--symbol", required=True, help="e.g. BTCUSD (inverse) or BTCUSDT (linear)")
    p.add_argument("--pair", required=True, help="canonical pair, e.g. BTC/USD")
    p.add_argument("--tf", required=True, help=f"one of {sorted(_TF_TO_BYBIT_MINUTES)}")
    p.add_argument("--year", required=True, type=int)
    p.add_argument("--cache-dir", default=None)
    return p


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s"
    )
    args = _build_parser().parse_args(argv)
    loader = BybitBulkLoader(
        cache_dir=Path(args.cache_dir) if args.cache_dir else None
    )
    inserted = loader.bulk_load(
        symbol=args.symbol,
        pair=args.pair,
        tf=args.tf,
        year=args.year,
    )
    print(f"inserted_rows={inserted}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
