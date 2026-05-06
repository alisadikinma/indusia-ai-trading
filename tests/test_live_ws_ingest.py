"""Phase 2: tests for the live websocket ingest.

Two tests:
1. test_subscription_payload_well_formed — pure unit test, no network.
2. test_kline_close_message_inserts_row — connects to the real Binance public
   websocket and waits up to ~70s for one closed kline event (a 1m candle
   closes at most once per minute), then verifies a row landed in Postgres.
   Marked @pytest.mark.integration AND @pytest.mark.slow.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import os

import pytest

from infra.data_loader.live_ws_ingest import (
    ClosedCandle,
    build_stream_path,
    build_subscription_payload,
    run,
)


def test_subscription_payload_well_formed():
    p = build_subscription_payload("BTCUSDT", "1m")
    assert p["method"] == "SUBSCRIBE"
    assert p["params"] == ["btcusdt@kline_1m"]
    assert p["id"] == 1


def test_stream_path_lowercased():
    assert build_stream_path("BTCUSDT", "1m") == "btcusdt@kline_1m"


def test_closed_candle_from_kline_event_returns_none_when_not_closed():
    ev = {
        "e": "kline", "E": 1, "s": "BTCUSDT",
        "k": {"t": 1700000000000, "i": "1m", "o": "1", "c": "2",
              "h": "3", "l": "0.5", "v": "10", "x": False},
    }
    assert ClosedCandle.from_kline_event(ev) is None


def test_closed_candle_from_kline_event_parses_closed():
    ev = {
        "e": "kline", "E": 1, "s": "BTCUSDT",
        "k": {"t": 1700000000000, "i": "1m", "o": "1", "c": "2",
              "h": "3", "l": "0.5", "v": "10", "x": True},
    }
    c = ClosedCandle.from_kline_event(ev)
    assert c is not None
    assert c.pair == "BTC/USDT"
    assert c.tf == "1m"
    assert c.close == 2.0
    assert c.ts.tzinfo is not None


def _dsn() -> str:
    return (
        f"postgresql://{os.environ['POSTGRES_USER']}:"
        f"{os.environ['POSTGRES_PASSWORD']}@"
        f"{os.environ['POSTGRES_HOST']}:"
        f"{os.environ['POSTGRES_PORT']}/"
        f"{os.environ['POSTGRES_DB']}"
    )


@pytest.mark.integration
@pytest.mark.slow
def test_kline_close_message_inserts_row():
    """Connect to real Binance WS, wait for one closed candle, verify DB insert."""
    psycopg = pytest.importorskip("psycopg")
    captured: list[ClosedCandle] = []

    async def _go():
        return await asyncio.wait_for(
            run("btcusdt", "1m", max_messages=1, on_candle=captured.append),
            timeout=90.0,
        )

    inserted = asyncio.run(_go())
    assert inserted >= 1
    assert captured, "No closed candle observed"
    c = captured[0]
    assert c.pair == "BTC/USDT"
    assert c.tf == "1m"

    # Verify the row landed
    with psycopg.connect(_dsn()) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM brain.ohlcv "
            "WHERE pair=%s AND tf=%s AND ts=%s",
            (c.pair, c.tf, c.ts),
        )
        row = cur.fetchone()
        assert row is not None and row[0] == 1
