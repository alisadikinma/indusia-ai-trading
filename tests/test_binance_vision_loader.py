"""Phase 2: tests for the Binance Vision bulk loader.

Step 1 in the TDD ladder is the parse_zip() shape test below — it imports
BinanceVisionLoader, which does not yet exist (RED). After implementation
(GREEN) all assertions hold against a real Binance Vision monthly zip
fixture committed under tests/fixtures/binance_vision/.

Integration tests run against the local Postgres on 127.0.0.1:5544 with
the brain.ohlcv hypertable from migration 001.
"""
from __future__ import annotations

import os
import zipfile
from datetime import date
from pathlib import Path

import pytest

# RED step: this import is the failing-test trigger. The error message expected
# during the first run of pytest on this file is:
#   ImportError: cannot import name 'BinanceVisionLoader' from
#   'infra.data_loader.binance_vision'
from infra.data_loader.binance_vision import BinanceVisionLoader  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURE_DIR = REPO_ROOT / "tests" / "fixtures" / "binance_vision"
FIXTURE_ZIP = FIXTURE_DIR / "BTCUSDT-1m-2024-01.zip"


def _postgres_dsn() -> str:
    return (
        f"postgresql://{os.environ['POSTGRES_USER']}:"
        f"{os.environ['POSTGRES_PASSWORD']}@"
        f"{os.environ['POSTGRES_HOST']}:"
        f"{os.environ['POSTGRES_PORT']}/"
        f"{os.environ['POSTGRES_DB']}"
    )


@pytest.fixture(scope="module")
def fixture_zip() -> Path:
    if not FIXTURE_ZIP.exists():
        pytest.skip(
            f"Real Binance Vision fixture not present: {FIXTURE_ZIP}. "
            "Run scripts/fetch_binance_fixture.py or download manually from "
            "https://data.binance.vision/data/spot/monthly/klines/BTCUSDT/1m/"
        )
    # sanity: real zip with at least one CSV inside
    with zipfile.ZipFile(FIXTURE_ZIP) as zf:
        names = zf.namelist()
    assert names, "Fixture zip is empty"
    assert any(n.endswith(".csv") for n in names), "Fixture zip missing CSV"
    return FIXTURE_ZIP


def test_parse_zip_returns_correct_columns(fixture_zip: Path) -> None:
    """parse_zip must return polars DataFrame with the canonical OHLCV column set."""
    loader = BinanceVisionLoader()
    df = loader.parse_zip(fixture_zip)
    expected = ["ts", "open", "high", "low", "close", "volume"]
    assert list(df.columns) == expected, f"Got columns {df.columns!r}"


def test_parse_zip_row_count_reasonable(fixture_zip: Path) -> None:
    """A 30/31-day month at 1m resolution has ~43,200 / ~44,640 rows."""
    loader = BinanceVisionLoader()
    df = loader.parse_zip(fixture_zip)
    n = df.height
    # Allow some slack: Binance occasionally has gaps. 2024-01 is 31 days = 44,640 minutes.
    # Accept anything plausible for a full month at 1m.
    assert 30_000 <= n <= 50_000, f"Suspicious row count {n} for a 1m month"


def test_parse_zip_timestamps_are_utc_aware(fixture_zip: Path) -> None:
    """Timestamps must be timezone-aware UTC and monotonically increasing."""
    loader = BinanceVisionLoader()
    df = loader.parse_zip(fixture_zip)
    ts = df["ts"]
    # Polars Datetime with tz="UTC" -> dtype.time_zone == 'UTC'
    assert getattr(ts.dtype, "time_zone", None) == "UTC", f"Not UTC-aware: {ts.dtype}"
    # Monotonic non-decreasing
    diffs = ts.diff().drop_nulls()
    # All 1-minute spacing typically; allow >0 (strictly increasing)
    assert (diffs.dt.total_seconds() > 0).all(), "Timestamps not strictly increasing"


@pytest.mark.integration
@pytest.mark.slow
def test_download_verifies_checksum_real_url(tmp_path: Path) -> None:
    """Downloads a real (small) historical Binance Vision month and verifies SHA256.

    Uses 2017-08 (the earliest BTCUSDT spot month) to keep the download small.
    Hard-fails if Binance Vision is unreachable — surfaces network/rate-limit issues.
    """
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    loader = BinanceVisionLoader(cache_dir=cache_dir)
    p = loader.download_month("BTCUSDT", "1m", 2017, 8)
    assert p.exists()
    assert p.stat().st_size > 1000, "Downloaded zip suspiciously small"
    # Idempotent re-download should be a cache hit (mtime unchanged).
    mtime1 = p.stat().st_mtime
    p2 = loader.download_month("BTCUSDT", "1m", 2017, 8)
    assert p2 == p
    assert p2.stat().st_mtime == mtime1, "Cached file was rewritten on second call"


@pytest.mark.integration
def test_bulk_load_inserts_rows(fixture_zip: Path, tmp_path: Path) -> None:
    """End-to-end pipeline against local Postgres using the fixture zip.

    Strategy: copy the fixture into a temp cache that matches the loader's
    expected on-disk layout, then call bulk_load() — which finds the cached
    file and skips network. Inserts into brain.ohlcv via staging+ON CONFLICT.
    """
    psycopg = pytest.importorskip("psycopg")

    cache_dir = tmp_path / "cache"
    target_dir = cache_dir / "BTCUSDT" / "1m"
    target_dir.mkdir(parents=True)
    # Mirror the cache layout produced by download_month()
    (target_dir / "BTCUSDT-1m-2024-01.zip").write_bytes(fixture_zip.read_bytes())

    # Pre-clean any prior 2024-01 BTC/USDT rows so the test is hermetic
    with psycopg.connect(_postgres_dsn()) as conn, conn.cursor() as cur:
        cur.execute(
            "DELETE FROM brain.ohlcv "
            "WHERE pair=%s AND tf=%s AND ts >= %s AND ts < %s",
            ("BTC/USDT", "1m", "2024-01-01", "2024-02-01"),
        )
        conn.commit()

    loader = BinanceVisionLoader(cache_dir=cache_dir)
    inserted = loader.bulk_load(
        symbol="BTCUSDT",
        tf="1m",
        start=date(2024, 1, 1),
        end=date(2024, 1, 31),
    )
    assert inserted >= 30_000, f"Inserted only {inserted} rows"

    with psycopg.connect(_postgres_dsn()) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM brain.ohlcv "
            "WHERE pair=%s AND tf=%s AND ts >= %s AND ts < %s",
            ("BTC/USDT", "1m", "2024-01-01", "2024-02-01"),
        )
        row = cur.fetchone()
        assert row is not None
        assert row[0] >= 30_000

    # Idempotency: re-running bulk_load should insert 0 net new rows
    inserted2 = loader.bulk_load(
        symbol="BTCUSDT",
        tf="1m",
        start=date(2024, 1, 1),
        end=date(2024, 1, 31),
    )
    assert inserted2 == 0, f"Re-run inserted {inserted2} rows; expected 0 (ON CONFLICT)"


# ---------------------------------------------------------------------------
# Dual ms / microsecond timestamp handling — Binance Vision shifted Spot data
# from millisecond to microsecond precision on 2025-01-01. Pre-2025 zips ship
# ms; post-2025 zips ship μs. Our loader must detect & convert both correctly
# without sub-second drift artefacts when stitching across the boundary.
# Source: NotebookLM citation 17 — github.com/binance/binance-public-data
# (also cross-referenced in references/crypto/exchange-microstructure.md
# Topic 5).
# ---------------------------------------------------------------------------


def _make_synthetic_zip(
    out_zip: Path,
    inner_csv_name: str,
    rows: list[tuple],
) -> None:
    """Write a Binance-Vision-shaped 12-col CSV inside a zip.

    Each ``rows`` tuple is the full 12-col Binance kline row, opening with the
    timestamp in WHATEVER precision the caller wants to test (caller decides
    ms vs μs). All other columns can be plausible floats.
    """
    import csv as _csv
    import io as _io

    buf = _io.StringIO()
    w = _csv.writer(buf, lineterminator="\n")
    for r in rows:
        w.writerow(r)
    csv_bytes = buf.getvalue().encode("utf-8")
    with zipfile.ZipFile(out_zip, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(inner_csv_name, csv_bytes)


def test_parse_zip_handles_pre_2025_millisecond_timestamps(tmp_path: Path) -> None:
    """Pre-2025-01-01 Binance Vision files use millisecond-precision timestamps.

    A zip dated 2024-12 must parse to UTC-aware ts at millisecond precision
    with no spurious μs digits.
    """
    import datetime as _dt

    from infra.data_loader.binance_vision import BinanceVisionLoader

    zp = tmp_path / "BTCUSDT-1m-2024-12.zip"
    # 2024-12-31 23:58:00 UTC, 23:59:00 UTC — 60_000ms apart.
    base_ms = int(
        _dt.datetime(2024, 12, 31, 23, 58, 0, tzinfo=_dt.timezone.utc).timestamp()
        * 1000
    )
    rows = [
        (
            base_ms, "100.0", "101.0", "99.0", "100.5", "12.34",
            base_ms + 60_000 - 1, "1234.5", 7, "5.0", "500.0", "0",
        ),
        (
            base_ms + 60_000, "100.5", "101.5", "99.5", "101.0", "11.0",
            base_ms + 120_000 - 1, "1100.0", 5, "4.0", "404.0", "0",
        ),
    ]
    _make_synthetic_zip(zp, "BTCUSDT-1m-2024-12.csv", rows)

    df = BinanceVisionLoader().parse_zip(zp)
    assert df.height == 2
    ts0 = df["ts"].to_list()[0]
    ts1 = df["ts"].to_list()[1]
    # Aware UTC, exactly the inputs (no μs drift).
    assert ts0 == _dt.datetime(2024, 12, 31, 23, 58, 0, tzinfo=_dt.timezone.utc)
    assert ts1 == _dt.datetime(2024, 12, 31, 23, 59, 0, tzinfo=_dt.timezone.utc)


def test_parse_zip_handles_post_2025_microsecond_timestamps(tmp_path: Path) -> None:
    """Post-2025-01-01 Binance Vision files use microsecond-precision timestamps.

    The integer-typed first column is now μs-since-epoch — a 13-digit ms value
    becomes a 16-digit μs value. The loader must detect this and avoid
    treating it as ms (which would produce a year ~50000+ AD timestamp).
    """
    import datetime as _dt

    from infra.data_loader.binance_vision import BinanceVisionLoader

    zp = tmp_path / "BTCUSDT-1m-2025-01.zip"
    # 2025-01-02 00:00:00 UTC, 00:01:00 UTC — 60_000_000μs apart.
    base_us = int(
        _dt.datetime(2025, 1, 2, 0, 0, 0, tzinfo=_dt.timezone.utc).timestamp()
        * 1_000_000
    )
    rows = [
        (
            base_us, "200.0", "201.0", "199.0", "200.5", "10.0",
            base_us + 60_000_000 - 1, "2000.0", 7, "5.0", "1000.0", "0",
        ),
        (
            base_us + 60_000_000, "200.5", "201.5", "199.5", "201.0", "9.0",
            base_us + 120_000_000 - 1, "1800.0", 4, "4.0", "800.0", "0",
        ),
    ]
    _make_synthetic_zip(zp, "BTCUSDT-1m-2025-01.csv", rows)

    df = BinanceVisionLoader().parse_zip(zp)
    assert df.height == 2
    ts_list = df["ts"].to_list()
    assert ts_list[0] == _dt.datetime(2025, 1, 2, 0, 0, 0, tzinfo=_dt.timezone.utc)
    assert ts_list[1] == _dt.datetime(2025, 1, 2, 0, 1, 0, tzinfo=_dt.timezone.utc)
    # Year sanity — if we mistakenly treated μs as ms we'd be in year ~3939.
    for t in ts_list:
        assert 2025 <= t.year <= 2026, f"Wrong-precision parse: got {t}"


def test_parse_zip_boundary_crossing_no_subsecond_drift(tmp_path: Path) -> None:
    """Two zips spanning the 2024-12 / 2025-01 boundary parse with consistent
    minute-aligned ts. Concatenating gives strictly-increasing ts with no
    sub-second-drift artefacts when stitching ms and μs files together.
    """
    import datetime as _dt

    import polars as pl

    from infra.data_loader.binance_vision import BinanceVisionLoader

    pre_zip = tmp_path / "BTCUSDT-1m-2024-12.zip"
    post_zip = tmp_path / "BTCUSDT-1m-2025-01.zip"

    # Last 3 minutes of 2024-12 in ms.
    base_pre_ms = int(
        _dt.datetime(2024, 12, 31, 23, 57, 0, tzinfo=_dt.timezone.utc).timestamp()
        * 1000
    )
    pre_rows = [
        (
            base_pre_ms + i * 60_000, "100.0", "101.0", "99.0", "100.5",
            "10.0", base_pre_ms + (i + 1) * 60_000 - 1, "1000.0",
            5, "4.0", "400.0", "0",
        )
        for i in range(3)
    ]
    _make_synthetic_zip(pre_zip, "BTCUSDT-1m-2024-12.csv", pre_rows)

    # First 3 minutes of 2025-01 in μs.
    base_post_us = int(
        _dt.datetime(2025, 1, 1, 0, 0, 0, tzinfo=_dt.timezone.utc).timestamp()
        * 1_000_000
    )
    post_rows = [
        (
            base_post_us + i * 60_000_000, "100.0", "101.0", "99.0", "100.5",
            "10.0", base_post_us + (i + 1) * 60_000_000 - 1, "1000.0",
            5, "4.0", "400.0", "0",
        )
        for i in range(3)
    ]
    _make_synthetic_zip(post_zip, "BTCUSDT-1m-2025-01.csv", post_rows)

    loader = BinanceVisionLoader()
    df_pre = loader.parse_zip(pre_zip)
    df_post = loader.parse_zip(post_zip)

    # Same dtype — both must be tz-aware UTC datetime.
    assert getattr(df_pre["ts"].dtype, "time_zone", None) == "UTC"
    assert getattr(df_post["ts"].dtype, "time_zone", None) == "UTC"

    combined = pl.concat([df_pre, df_post]).sort("ts")
    diffs = combined["ts"].diff().drop_nulls().dt.total_seconds().to_list()
    # All neighbouring rows must be 60 seconds apart — no sub-second drift,
    # no spurious zero / negative diffs from precision-mixing.
    assert all(d == 60.0 for d in diffs), f"sub-second drift detected: {diffs}"

    # Exact boundary check: last pre row + 60s == first post row.
    last_pre = df_pre["ts"].to_list()[-1]
    first_post = df_post["ts"].to_list()[0]
    assert (first_post - last_pre).total_seconds() == 60.0
