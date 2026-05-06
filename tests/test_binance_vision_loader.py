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
