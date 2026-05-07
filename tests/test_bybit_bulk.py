"""Tests for the Bybit public archive bulk loader.

Bybit publishes pre-aggregated OHLCV (kline-for-MetaTrader-4) ZIPs at:

    https://public.bybit.com/kline_for_metatrader4/<SYMBOL>/<YEAR>/

Each file is gzipped CSV named:

    <SYMBOL>_<INTERVAL_MINUTES>_<YYYY-MM-DD>_<YYYY-MM-DD>.csv.gz

Coverage starts:
* inverse contracts (e.g. BTCUSD)  → ~November 2019
* linear contracts  (e.g. BTCUSDT) → ~May 2020

Per the project Phase 0 spec for the post-research backtest data extension.

The archive directory is browsable HTML (Apache autoindex), so the loader
discovers monthly files by scraping anchor tags rather than guessing
filenames.

These tests cover:
* parse_csv_gz_bytes() — header-less CSV parsing (RED→GREEN; no network).
* parse_csv_gz_bytes() — pair encoding (@bybit suffix, source='bybit').
* parse_csv_gz_bytes() — UTC-aware timestamps from Unix-second integers.
* a small REAL public.bybit.com integration test marked
  ``pytest.mark.integration``. If the network/SSL refuses connection
  (corporate proxy, captive portal, certificate issue) we ``pytest.skip``
  with a clear reason — Iron Law 3 forbids silently substituting fake data.

Pair encoding (project standard): rows are written to ``brain.ohlcv`` with
``pair`` of the form ``<PAIR>@bybit``. See loader docstring + TODO note about
future migration ``004_brain_ohlcv_source_in_pk.sql``.
"""
from __future__ import annotations

import gzip
import io
import os
from pathlib import Path

import pytest

# RED step: BybitBulkLoader does not yet exist.
from infra.data_loader.bybit_bulk import BybitBulkLoader  # noqa: E402


def _synthetic_bybit_csv_bytes() -> bytes:
    """Header-less CSV in Bybit's MT4-style OHLCV format.

    Bybit publishes 8-column rows: Date, Time, Open, High, Low, Close, Volume,
    Tickvol. The loader normalizes Date+Time into a single UTC ts.
    Per Bybit MT4-style archive convention, Date is YYYY.MM.DD and Time is
    HH:MM in UTC.
    """
    rows = [
        "2019.11.05,00:00,9200.0,9210.0,9195.0,9205.0,12.5,12",
        "2019.11.05,00:01,9205.0,9215.0,9200.0,9210.5,9.8,9",
        "2019.11.05,00:02,9210.5,9220.0,9208.0,9215.0,15.2,17",
    ]
    return ("\n".join(rows) + "\n").encode("utf-8")


def _synthetic_bybit_csv_gz_bytes() -> bytes:
    return gzip.compress(_synthetic_bybit_csv_bytes())


def test_parse_csv_gz_bytes_returns_canonical_dataframe() -> None:
    loader = BybitBulkLoader()
    df = loader.parse_csv_gz_bytes(
        _synthetic_bybit_csv_gz_bytes(), pair="BTC/USD", tf="1m"
    )
    expected = ["pair", "tf", "ts", "open", "high", "low", "close", "volume", "source"]
    assert list(df.columns) == expected, f"Got columns {df.columns!r}"
    assert df.height == 3


def test_parse_csv_gz_bytes_pair_has_bybit_suffix() -> None:
    loader = BybitBulkLoader()
    df = loader.parse_csv_gz_bytes(
        _synthetic_bybit_csv_gz_bytes(), pair="BTC/USD", tf="1m"
    )
    pairs = set(df["pair"].to_list())
    assert pairs == {"BTC/USD@bybit"}, f"Bad pair encoding: {pairs}"
    assert set(df["source"].to_list()) == {"bybit"}


def test_parse_csv_gz_bytes_timestamps_are_utc_aware() -> None:
    import datetime as _dt

    loader = BybitBulkLoader()
    df = loader.parse_csv_gz_bytes(
        _synthetic_bybit_csv_gz_bytes(), pair="BTC/USD", tf="1m"
    )
    assert getattr(df["ts"].dtype, "time_zone", None) == "UTC"
    first = df["ts"].to_list()[0]
    assert first == _dt.datetime(2019, 11, 5, 0, 0, 0, tzinfo=_dt.timezone.utc)


def test_parse_csv_gz_rejects_empty_input() -> None:
    loader = BybitBulkLoader()
    with pytest.raises((ValueError, Exception)):
        loader.parse_csv_gz_bytes(b"", pair="BTC/USD", tf="1m")


def test_parse_local_gz_file(tmp_path: Path) -> None:
    """parse_local_gz() reads a .csv.gz off disk (used by integration flow)."""
    p = tmp_path / "BTCUSD_1_2019-11-01_2019-11-30.csv.gz"
    p.write_bytes(_synthetic_bybit_csv_gz_bytes())
    loader = BybitBulkLoader()
    df = loader.parse_local_gz(p, pair="BTC/USD", tf="1m")
    assert df.height == 3
    assert set(df["pair"].to_list()) == {"BTC/USD@bybit"}


# ---------------------------------------------------------------------------
# Real-network integration test against public.bybit.com. Hits the live
# Apache-autoindex listing and downloads ONE month CSV.gz to validate the
# end-to-end pipeline. Skipped (with clear reason) when the development
# machine cannot reach Bybit (captive portal / corporate SSL inspection /
# Bybit-archive geofence) — per Iron Law 3 we never silently mock.
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_real_bybit_archive_smoke(tmp_path: Path) -> None:
    import httpx

    cache_dir = tmp_path / "bybit_cache"
    loader = BybitBulkLoader(cache_dir=cache_dir)
    # One inverse-contract month from coverage start (2019-11). Symbol
    # ``BTCUSD`` is Bybit-native.
    try:
        files = loader.list_monthly_files(symbol="BTCUSD", year=2019)
    except (httpx.HTTPError, OSError) as e:
        pytest.skip(
            f"Cannot reach public.bybit.com (network/SSL): {e}. "
            "Re-run on the production VPS where TLS to Bybit succeeds. "
            "NOT auto-mocked: Iron Law 3."
        )
    if not files:
        pytest.skip(
            "Bybit archive returned 0 files — directory schema may have "
            "changed. Re-validate URL pattern and update loader before "
            "rerunning. NOT auto-mocked: Iron Law 3."
        )
    # Download the first available file and parse.
    chosen = files[0]
    try:
        local = loader.download_file(chosen.url, cache_dir / chosen.filename)
    except (httpx.HTTPError, OSError) as e:
        pytest.skip(
            f"Cannot download Bybit archive file {chosen.filename!r}: {e}. "
            "Re-run on the production VPS. NOT auto-mocked: Iron Law 3."
        )
    df = loader.parse_local_gz(local, pair="BTC/USD", tf="1m")
    assert df.height > 0
    assert all(p.endswith("@bybit") for p in df["pair"].to_list())
    assert getattr(df["ts"].dtype, "time_zone", None) == "UTC"
