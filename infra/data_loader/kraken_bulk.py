"""Kraken historical OHLCVT bulk loader.

Loads Kraken's downloadable historical OHLCVT (Open, High, Low, Close, Volume,
Trades) data into ``brain.ohlcv``. Kraken publishes a single quarterly ZIP per
pair group via a Google-Drive share linked from
https://support.kraken.com/articles/360047124832-downloadable-historical-ohlcvt-open-high-low-close-volume-trades-data .

CSV format inside each zip — files named ``<KRAKEN_PAIR>_<INTERVAL_MINUTES>.csv``
(e.g. ``XBTUSD_1.csv``, ``XBTUSD_60.csv``, ``XBTUSD_1440.csv``); intervals
are 1, 5, 15, 30, 60, 240, 720, 1440 minutes. Each CSV has 7 columns and NO
header line:

    timestamp_unix_seconds, open, high, low, close, volume, trades_count

Timestamps are integer seconds (UTC), not milliseconds.

Pair encoding (project standard) — schema collision callout
-----------------------------------------------------------
The current ``brain.ohlcv`` table has primary key ``(pair, tf, ts)`` (see
``infra/migrations/000_bootstrap_schemas.sql``). Same-named pairs from
DIFFERENT venues would therefore collide on insert: ``BTC/USD`` from Kraken
vs. ``BTC/USD`` from Coinbase, or ``BTC/USDT`` from Binance vs. Kraken.

Workaround for Phase 0 of the post-research backtest data extension: this
loader writes Kraken pairs with an ``@kraken`` suffix
(e.g. ``BTC/USD@kraken``) so PK uniqueness is preserved.

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
- ``KRAKEN_OHLCVT_CACHE_DIR`` is consulted when no explicit ``cache_dir`` is
  passed; falls back to ``infra/data_loader/.cache/kraken_ohlcvt`` under repo
  root.
- ``POSTGRES_{HOST,PORT,USER,PASSWORD,DB}`` are required for ``bulk_load()``.
  Missing values raise ``KeyError`` (Iron Law: no silent fallback).

CLI
---

    python -m infra.data_loader.kraken_bulk \
        --url 'https://drive.google.com/...zip' \
        --kraken-pair XBTUSD \
        --pair BTC/USD \
        --tf 1d
"""
from __future__ import annotations

import argparse
import io
import logging
import os
import sys
import zipfile
from pathlib import Path

import httpx
import polars as pl
import psycopg

logger = logging.getLogger(__name__)

HTTP_TIMEOUT_S = 120.0  # quarterly archives can be hundreds of MB

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_DEFAULT_CACHE_DIR = REPO_ROOT / "infra" / "data_loader" / ".cache" / "kraken_ohlcvt"

# Map our canonical timeframe strings to the integer-minute suffix Kraken uses
# in the per-interval CSV filenames inside each pair zip.
_TF_TO_KRAKEN_MINUTES: dict[str, int] = {
    "1m": 1,
    "5m": 5,
    "15m": 15,
    "30m": 30,
    "1h": 60,
    "4h": 240,
    "12h": 720,
    "1d": 1440,
}

# Inside each Kraken pair-zip, the CSV is unheaded with these columns in order.
_KRAKEN_OHLCVT_COLS = (
    "ts_seconds",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "trades",
)


def _resolve_cache_dir(cache_dir: Path | None) -> Path:
    if cache_dir is not None:
        return cache_dir
    env = os.environ.get("KRAKEN_OHLCVT_CACHE_DIR")
    if env:
        return Path(env)
    return _DEFAULT_CACHE_DIR


def _kraken_minutes(tf: str) -> int:
    try:
        return _TF_TO_KRAKEN_MINUTES[tf]
    except KeyError as e:
        raise ValueError(
            f"Unsupported timeframe {tf!r}. Kraken OHLCVT supports "
            f"{sorted(_TF_TO_KRAKEN_MINUTES)}."
        ) from e


class KrakenBulkLoader:
    """Bulk loader for Kraken OHLCVT historical archive ZIPs."""

    def __init__(self, cache_dir: Path | None = None) -> None:
        self.cache_dir = _resolve_cache_dir(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    # -------------------------------------------------------------- download

    def download(self, url: str, dest: Path) -> Path:
        """Download a Kraken-published archive zip from ``url`` to ``dest``.

        Real network call — caller is responsible for providing a valid URL
        (Kraken posts a fresh Drive link each quarter). If the file already
        exists at ``dest`` it is reused (size check only — Kraken does not
        publish a checksum file alongside).
        """
        if dest.exists() and dest.stat().st_size > 0:
            logger.info("kraken cache hit: %s", dest)
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

    def parse_csv_bytes(
        self,
        raw: bytes,
        *,
        pair: str,
        tf: str,
    ) -> pl.DataFrame:
        """Parse a single Kraken OHLCVT CSV (header-less, 7 cols) into the
        canonical brain.ohlcv-shaped DataFrame.

        ``pair`` is the canonical pair (e.g. ``BTC/USD``). The output rows
        carry ``pair = f"{pair}@kraken"`` (PK collision workaround).
        """
        if not raw or not raw.strip():
            raise ValueError("Empty Kraken OHLCVT CSV bytes")

        df = pl.read_csv(
            io.BytesIO(raw),
            has_header=False,
            new_columns=list(_KRAKEN_OHLCVT_COLS),
            schema_overrides={
                "ts_seconds": pl.Int64,
                "open": pl.Float64,
                "high": pl.Float64,
                "low": pl.Float64,
                "close": pl.Float64,
                "volume": pl.Float64,
                "trades": pl.Int64,
            },
        )

        suffixed_pair = f"{pair}@kraken"
        df = df.with_columns(
            pl.from_epoch(pl.col("ts_seconds"), time_unit="s")
            .dt.replace_time_zone("UTC")
            .alias("ts"),
            pl.lit(suffixed_pair).alias("pair"),
            pl.lit(tf).alias("tf"),
            pl.lit("kraken").alias("source"),
        )

        return df.select(
            ["pair", "tf", "ts", "open", "high", "low", "close", "volume", "source"]
        )

    def parse_zip(
        self,
        zip_path: Path,
        *,
        kraken_pair: str,
        pair: str,
        tf: str,
    ) -> pl.DataFrame:
        """Open a Kraken-published archive zip and return the OHLCV slice for
        the requested ``kraken_pair`` and ``tf``.

        ``kraken_pair`` is the Kraken-native ticker (e.g. ``XBTUSD``).
        ``pair`` is the canonical pair (e.g. ``BTC/USD``) used for the
        suffixed ``pair`` column in the output.
        """
        minutes = _kraken_minutes(tf)
        target_inner = f"{kraken_pair}_{minutes}.csv"

        with zipfile.ZipFile(zip_path) as zf:
            names = zf.namelist()
            # Allow the file to be at the zip root or under an arbitrary
            # subdirectory (Kraken sometimes ships with a top-level folder).
            matches = [n for n in names if n.endswith(target_inner)]
            if not matches:
                raise ValueError(
                    f"{zip_path}: no member matching {target_inner!r} "
                    f"(zip contents: {names[:10]}{'...' if len(names) > 10 else ''})"
                )
            with zf.open(matches[0]) as f:
                raw = f.read()

        return self.parse_csv_bytes(raw, pair=pair, tf=tf)

    # ---------------------------------------------------------- fetch+parse

    def fetch_and_parse(
        self,
        *,
        url: str,
        kraken_pair: str,
        pair: str,
        tf: str,
    ) -> pl.DataFrame:
        """Convenience: download the archive (cached) and return parsed slice."""
        local = self.cache_dir / f"{kraken_pair}_archive.zip"
        self.download(url, local)
        return self.parse_zip(local, kraken_pair=kraken_pair, pair=pair, tf=tf)

    # ----------------------------------------------------------- bulk_load

    def bulk_load(
        self,
        *,
        url: str,
        kraken_pair: str,
        pair: str,
        tf: str,
    ) -> int:
        """Download → parse → INSERT ... ON CONFLICT DO NOTHING into brain.ohlcv.

        Returns the number of net rows inserted. Idempotent on re-run thanks
        to the ON CONFLICT clause.
        """
        df = self.fetch_and_parse(
            url=url, kraken_pair=kraken_pair, pair=pair, tf=tf
        )
        if df.is_empty():
            logger.warning("Kraken parse produced 0 rows for %s %s", pair, tf)
            return 0

        dsn = (
            f"postgresql://{os.environ['POSTGRES_USER']}:"
            f"{os.environ['POSTGRES_PASSWORD']}@"
            f"{os.environ['POSTGRES_HOST']}:"
            f"{os.environ['POSTGRES_PORT']}/"
            f"{os.environ['POSTGRES_DB']}"
        )
        with psycopg.connect(dsn) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    CREATE TEMP TABLE _stage_kraken_ohlcv (
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
                with cur.copy(
                    "COPY _stage_kraken_ohlcv "
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
                    FROM _stage_kraken_ohlcv
                    ON CONFLICT (pair, tf, ts) DO NOTHING;
                    """
                )
                inserted = cur.rowcount
            conn.commit()
        logger.info(
            "kraken bulk_load: %s rows in df, %s net inserted (%s %s)",
            df.height, inserted, pair, tf,
        )
        return inserted


# ---------------------------------------------------------------------- CLI


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m infra.data_loader.kraken_bulk",
        description="Bulk-load Kraken OHLCVT historical archive into brain.ohlcv.",
    )
    p.add_argument("--url", required=True, help="Kraken-published archive zip URL")
    p.add_argument("--kraken-pair", required=True, help="e.g. XBTUSD")
    p.add_argument("--pair", required=True, help="canonical pair, e.g. BTC/USD")
    p.add_argument("--tf", required=True, help="1m,5m,15m,30m,1h,4h,12h,1d")
    p.add_argument("--cache-dir", default=None)
    return p


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s"
    )
    args = _build_parser().parse_args(argv)
    loader = KrakenBulkLoader(
        cache_dir=Path(args.cache_dir) if args.cache_dir else None
    )
    inserted = loader.bulk_load(
        url=args.url,
        kraken_pair=args.kraken_pair,
        pair=args.pair,
        tf=args.tf,
    )
    print(f"inserted_rows={inserted}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
