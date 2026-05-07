"""Tests for the Kraken historical OHLCVT bulk loader.

Kraken publishes downloadable historical OHLCVT zips on a Google-Drive-hosted
share linked from
https://support.kraken.com/articles/360047124832-downloadable-historical-ohlcvt-open-high-low-close-volume-trades-data
Each zip contains ``<PAIR>_<INTERVAL_MIN>.csv`` files with 7 unheaded columns:

    timestamp, open, high, low, close, volume, trades

Timestamps are integer Unix seconds (no header line in the CSV).

These tests cover:
* parse_csv_bytes() — the pure-CSV-bytes parser (RED→GREEN; no network).
* a small REAL Kraken-archive integration test marked
  ``pytest.mark.integration``. Because the Kraken Drive share URL pattern
  changes (Kraken posts a fresh link each quarter), if no
  ``KRAKEN_OHLCVT_ZIP_URL`` env var is set we skip this test rather than
  silently mock it (Iron Law 3 — no placeholder data).

Pair encoding (project standard): rows are written to ``brain.ohlcv`` with
``pair`` of the form ``<PAIR>@kraken`` to avoid PK collision with same-named
Binance pairs (existing PK = (pair, tf, ts)). See loader docstring +
TODO note about future migration ``004_brain_ohlcv_source_in_pk.sql``.
"""
from __future__ import annotations

import io
import os
import zipfile
from pathlib import Path

import pytest

# RED step: KrakenBulkLoader does not yet exist.
from infra.data_loader.kraken_bulk import KrakenBulkLoader  # noqa: E402


def _synthetic_kraken_csv_bytes() -> bytes:
    """Build a tiny in-memory OHLCVT CSV in Kraken's published format.

    Columns (no header): timestamp, open, high, low, close, volume, trades.
    Timestamp is integer Unix seconds.
    """
    # 2014-01-08 12:00:00 UTC = 1389182400 (one of the earliest BTC/USD bars)
    rows = [
        "1389182400,830.0,832.0,829.5,831.0,12.5,42",
        "1389182460,831.0,833.0,830.5,832.5,9.8,30",
        "1389182520,832.5,834.0,832.0,833.5,15.2,55",
    ]
    return ("\n".join(rows) + "\n").encode("utf-8")


def _synthetic_kraken_zip_bytes(inner_filename: str = "XBTUSD_1.csv") -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(inner_filename, _synthetic_kraken_csv_bytes())
    return buf.getvalue()


def test_parse_csv_bytes_returns_canonical_dataframe() -> None:
    """parse_csv_bytes() must yield columns matching brain.ohlcv shape."""
    loader = KrakenBulkLoader()
    df = loader.parse_csv_bytes(
        _synthetic_kraken_csv_bytes(), pair="BTC/USD", tf="1m"
    )
    expected = ["pair", "tf", "ts", "open", "high", "low", "close", "volume", "source"]
    assert list(df.columns) == expected, f"Got columns {df.columns!r}"
    assert df.height == 3


def test_parse_csv_bytes_pair_has_kraken_suffix() -> None:
    """Kraken rows MUST be tagged with @kraken pair suffix to avoid PK
    collision against other venues' rows in brain.ohlcv (PK=(pair,tf,ts)).
    Documented in loader docstring + TODO migration ref.
    """
    loader = KrakenBulkLoader()
    df = loader.parse_csv_bytes(
        _synthetic_kraken_csv_bytes(), pair="BTC/USD", tf="1m"
    )
    # Every row's pair column ends with "@kraken"
    pair_vals = set(df["pair"].to_list())
    assert pair_vals == {"BTC/USD@kraken"}, f"Bad pair encoding: {pair_vals}"
    assert set(df["source"].to_list()) == {"kraken"}


def test_parse_csv_bytes_timestamps_are_utc_aware() -> None:
    """Kraken timestamps are Unix seconds; loader converts to tz-aware UTC."""
    import datetime as _dt

    loader = KrakenBulkLoader()
    df = loader.parse_csv_bytes(
        _synthetic_kraken_csv_bytes(), pair="BTC/USD", tf="1m"
    )
    assert getattr(df["ts"].dtype, "time_zone", None) == "UTC"
    first = df["ts"].to_list()[0]
    assert first == _dt.datetime(2014, 1, 8, 12, 0, 0, tzinfo=_dt.timezone.utc)


def test_parse_zip_picks_correct_interval(tmp_path: Path) -> None:
    """A Kraken pair zip contains XBTUSD_1.csv, XBTUSD_5.csv, XBTUSD_60.csv...
    Loader must pick the file matching the requested timeframe.
    """
    zp = tmp_path / "XBTUSD_OHLCVT.zip"
    with zipfile.ZipFile(zp, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("XBTUSD_1.csv", _synthetic_kraken_csv_bytes())
        # 60-minute file — different content so we can confirm we picked right
        zf.writestr("XBTUSD_60.csv", b"1389182400,1.0,1.0,1.0,1.0,1.0,1\n")

    loader = KrakenBulkLoader()
    df_1m = loader.parse_zip(zp, kraken_pair="XBTUSD", pair="BTC/USD", tf="1m")
    df_1h = loader.parse_zip(zp, kraken_pair="XBTUSD", pair="BTC/USD", tf="1h")
    assert df_1m.height == 3
    assert df_1h.height == 1


def test_parse_csv_bytes_rejects_malformed_input() -> None:
    """Empty or wrong-shaped data must raise — never silently produce stub rows."""
    loader = KrakenBulkLoader()
    with pytest.raises((ValueError, Exception)):
        loader.parse_csv_bytes(b"", pair="BTC/USD", tf="1m")


# ---------------------------------------------------------------------------
# Real-network integration test — marked ``integration`` so default ``pytest``
# runs skip it. Hits the *real* Kraken-published zip URL when the operator
# sets KRAKEN_OHLCVT_ZIP_URL (the Drive share link Kraken posts each quarter).
# Per Iron Law 3 we do NOT silently swap in mocked data; we skip with a clear
# reason if no URL is configured.
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_real_kraken_archive_smoke(tmp_path: Path) -> None:
    url = os.environ.get("KRAKEN_OHLCVT_ZIP_URL")
    if not url:
        pytest.skip(
            "KRAKEN_OHLCVT_ZIP_URL not set. Kraken publishes its OHLCVT "
            "Drive link each quarter (see "
            "https://support.kraken.com/articles/360047124832); export the "
            "current URL and rerun. NOT auto-mocked: Iron Law 3."
        )
    pair = os.environ.get("KRAKEN_OHLCVT_TEST_PAIR", "XBTUSD")
    target_pair = os.environ.get("KRAKEN_OHLCVT_TEST_TARGET_PAIR", "BTC/USD")
    tf = os.environ.get("KRAKEN_OHLCVT_TEST_TF", "1d")
    cache_dir = tmp_path / "kraken_cache"
    loader = KrakenBulkLoader(cache_dir=cache_dir)
    df = loader.fetch_and_parse(
        url=url,
        kraken_pair=pair,
        pair=target_pair,
        tf=tf,
    )
    assert df.height > 0
    assert all(p.endswith("@kraken") for p in df["pair"].to_list())
    assert getattr(df["ts"].dtype, "time_zone", None) == "UTC"
