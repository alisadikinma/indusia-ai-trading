"""Phase 2: tests for GapDetector against real Postgres."""
from __future__ import annotations

import datetime as dt
import os
import uuid

import pytest

from infra.data_loader.gap_detector import GapDetector

UTC = dt.timezone.utc


def _dsn() -> str:
    return (
        f"postgresql://{os.environ['POSTGRES_USER']}:"
        f"{os.environ['POSTGRES_PASSWORD']}@"
        f"{os.environ['POSTGRES_HOST']}:"
        f"{os.environ['POSTGRES_PORT']}/"
        f"{os.environ['POSTGRES_DB']}"
    )


@pytest.fixture
def synthetic_pair():
    """Create + clean up an isolated synthetic pair so we don't touch real data."""
    psycopg = pytest.importorskip("psycopg")
    pair = f"GAPTEST/USDT-{uuid.uuid4().hex[:8]}"
    yield pair
    with psycopg.connect(_dsn()) as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM brain.ohlcv WHERE pair = %s", (pair,))
        conn.commit()


def _insert(rows):
    import psycopg
    with psycopg.connect(_dsn()) as conn, conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO brain.ohlcv (pair, tf, ts, open, high, low, close, volume) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
            rows,
        )
        conn.commit()


@pytest.mark.integration
def test_no_gaps_in_continuous_data(synthetic_pair):
    pair = synthetic_pair
    start = dt.datetime(2024, 6, 1, tzinfo=UTC)
    end = dt.datetime(2024, 6, 1, 0, 9, tzinfo=UTC)  # 10 minutes
    rows = [
        (pair, "1m", start + dt.timedelta(minutes=i), 1, 1, 1, 1, 1)
        for i in range(10)
    ]
    _insert(rows)
    gaps = GapDetector().find_gaps(pair, "1m", start, end)
    assert gaps == []


@pytest.mark.integration
def test_finds_synthetic_gap(synthetic_pair):
    pair = synthetic_pair
    start = dt.datetime(2024, 6, 1, tzinfo=UTC)
    end = dt.datetime(2024, 6, 1, 0, 9, tzinfo=UTC)
    # Insert 0,1,2, ..skip 3,4,5.. ,6,7,8,9
    rows = [
        (pair, "1m", start + dt.timedelta(minutes=i), 1, 1, 1, 1, 1)
        for i in (0, 1, 2, 6, 7, 8, 9)
    ]
    _insert(rows)
    gaps = GapDetector().find_gaps(pair, "1m", start, end)
    assert len(gaps) == 1
    assert gaps[0][0] == start + dt.timedelta(minutes=3)
    assert gaps[0][1] == start + dt.timedelta(minutes=5)


@pytest.mark.integration
def test_returns_merged_gap_ranges(synthetic_pair):
    pair = synthetic_pair
    start = dt.datetime(2024, 6, 1, tzinfo=UTC)
    end = dt.datetime(2024, 6, 1, 0, 9, tzinfo=UTC)
    # Two distinct gap runs: skip 1-2 and skip 6-7
    rows = [
        (pair, "1m", start + dt.timedelta(minutes=i), 1, 1, 1, 1, 1)
        for i in (0, 3, 4, 5, 8, 9)
    ]
    _insert(rows)
    gaps = GapDetector().find_gaps(pair, "1m", start, end)
    assert len(gaps) == 2
    assert gaps[0] == (
        start + dt.timedelta(minutes=1),
        start + dt.timedelta(minutes=2),
    )
    assert gaps[1] == (
        start + dt.timedelta(minutes=6),
        start + dt.timedelta(minutes=7),
    )
