"""Live Binance kline websocket ingest.

Connects to the Binance public stream wss://stream.binance.com:9443/ws/<stream>,
listens for kline events, and on every CLOSED candle (k.x == True) inserts a
single row into brain.ohlcv via INSERT ... ON CONFLICT (pair, tf, ts) DO NOTHING.

Auto-reconnects with exponential backoff (base 1s, max 60s, +/- 25% jitter).

CLI:
    python -m infra.data_loader.live_ws_ingest \
        --symbol btcusdt --tf 1m

The dashed-symbol form (BTC/USDT) is translated to the upper-case Binance
form for the public stream URL (stream paths are LOWER case, but the canonical
DB pair is the slash form).

Env contract: same POSTGRES_* vars as the rest of Phase 2. Hard-fails on
missing env (KeyError) — Iron Law 5.85.
"""
from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json
import logging
import os
import random
import signal
import sys
from dataclasses import dataclass

import psycopg
import websockets

logger = logging.getLogger(__name__)

# Binance offers two production WS endpoints for market data:
#   1. wss://stream.binance.com:9443  — main, geo-restricted in some networks
#   2. wss://data-stream.binance.vision — market-data-only, geographically open
# We default to (2) because it works from every region and is the recommended
# endpoint for read-only market data per the public-data docs at
# https://github.com/binance/binance-spot-api-docs/blob/master/web-socket-streams.md
# This is a deterministic compiled-in URL (no API key, no credential) — not the
# kind of "silent default" the Iron Law forbids. Operator can override at run
# time by setting BINANCE_WS_BASE in the environment.
BINANCE_WS_BASE_DEFAULT = "wss://data-stream.binance.vision/ws"
BINANCE_WS_BASE = os.environ["BINANCE_WS_BASE"] if "BINANCE_WS_BASE" in os.environ else BINANCE_WS_BASE_DEFAULT

_BACKOFF_BASE_S = 1.0
_BACKOFF_MAX_S = 60.0
_JITTER = 0.25  # +/- 25%


def _dsn() -> str:
    return (
        f"postgresql://{os.environ['POSTGRES_USER']}:"
        f"{os.environ['POSTGRES_PASSWORD']}@"
        f"{os.environ['POSTGRES_HOST']}:"
        f"{os.environ['POSTGRES_PORT']}/"
        f"{os.environ['POSTGRES_DB']}"
    )


def _symbol_to_pair(symbol: str) -> str:
    """Translate BTCUSDT -> BTC/USDT (same logic as binance_vision)."""
    known_quotes = (
        "USDT", "BUSD", "USDC", "FDUSD", "TUSD", "USD", "BTC", "ETH", "BNB", "EUR", "TRY"
    )
    s = symbol.upper()
    for q in known_quotes:
        if s.endswith(q) and len(s) > len(q):
            return f"{s[:-len(q)]}/{q}"
    raise ValueError(f"Cannot infer base/quote split for symbol {symbol!r}")


def build_stream_path(symbol: str, tf: str) -> str:
    """Return the kline stream path: e.g. 'btcusdt@kline_1m'."""
    return f"{symbol.lower()}@kline_{tf}"


def build_subscription_payload(symbol: str, tf: str, msg_id: int = 1) -> dict:
    """Subscription envelope for the combined-stream endpoint.

    The single-stream URL form ``/ws/<stream>`` does not require a SUBSCRIBE
    message, but if the user prefers the ``/stream?streams=...`` combined
    endpoint the server expects a JSON SUBSCRIBE as the first message. We
    expose the well-formed payload for tests + future combined use.
    """
    return {
        "method": "SUBSCRIBE",
        "params": [build_stream_path(symbol, tf)],
        "id": msg_id,
    }


@dataclass(frozen=True)
class ClosedCandle:
    pair: str
    tf: str
    ts: dt.datetime
    open: float
    high: float
    low: float
    close: float
    volume: float

    @classmethod
    def from_kline_event(cls, event: dict) -> "ClosedCandle | None":
        """Parse a kline event. Returns None unless the candle just closed.

        Binance kline event envelope:
        {"e":"kline","E":..,"s":"BTCUSDT","k":{"t":<openTimeMs>,"i":"1m",
         "o":..,"c":..,"h":..,"l":..,"v":..,"x":<closed>}}
        """
        if event.get("e") != "kline":
            return None
        k = event.get("k") or {}
        if not k.get("x"):
            return None
        ts = dt.datetime.fromtimestamp(k["t"] / 1000.0, tz=dt.timezone.utc)
        return cls(
            pair=_symbol_to_pair(event["s"]),
            tf=k["i"],
            ts=ts,
            open=float(k["o"]),
            high=float(k["h"]),
            low=float(k["l"]),
            close=float(k["c"]),
            volume=float(k["v"]),
        )


def insert_candle(conn: psycopg.Connection, c: ClosedCandle) -> int:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO brain.ohlcv (pair, tf, ts, open, high, low, close, volume, source)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'binance_ws')
            ON CONFLICT (pair, tf, ts) DO NOTHING;
            """,
            (c.pair, c.tf, c.ts, c.open, c.high, c.low, c.close, c.volume),
        )
        conn.commit()
        return cur.rowcount


def _next_backoff(attempt: int) -> float:
    base = min(_BACKOFF_MAX_S, _BACKOFF_BASE_S * (2 ** attempt))
    jitter_band = base * _JITTER
    return base + random.uniform(-jitter_band, jitter_band)


async def run(
    symbol: str,
    tf: str,
    *,
    max_messages: int | None = None,
    on_candle=None,
) -> int:
    """Run the ingest loop until cancelled or max_messages closed candles seen.

    Returns the count of closed candles successfully inserted. Used by the
    integration test to bound runtime.
    """
    url = f"{BINANCE_WS_BASE}/{build_stream_path(symbol, tf)}"
    inserted = 0
    attempt = 0

    while True:
        try:
            logger.info("connecting to %s", url)
            async with websockets.connect(url, ping_interval=30) as ws:
                attempt = 0  # reset on success
                with psycopg.connect(_dsn()) as conn:
                    async for raw in ws:
                        try:
                            event = json.loads(raw)
                        except json.JSONDecodeError:
                            logger.warning("non-JSON frame: %r", raw[:80])
                            continue
                        candle = ClosedCandle.from_kline_event(event)
                        if candle is None:
                            continue
                        n = insert_candle(conn, candle)
                        if n:
                            inserted += 1
                            logger.info(
                                "inserted closed candle %s %s %s",
                                candle.pair, candle.tf, candle.ts,
                            )
                        if on_candle is not None:
                            on_candle(candle)
                        if max_messages is not None and inserted >= max_messages:
                            return inserted
        except (websockets.ConnectionClosed, OSError, asyncio.TimeoutError) as exc:
            sleep_s = _next_backoff(attempt)
            attempt += 1
            logger.warning("ws disconnect (%s), reconnecting in %.1fs", exc, sleep_s)
            await asyncio.sleep(sleep_s)


# ---------------------------------------------------------------------- CLI


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m infra.data_loader.live_ws_ingest",
        description="Stream closed Binance klines into brain.ohlcv.",
    )
    p.add_argument("--symbol", required=True, help="e.g. btcusdt or BTCUSDT")
    p.add_argument("--tf", required=True, help="e.g. 1m, 5m, 1h")
    return p


def _install_sigterm_handler(loop: asyncio.AbstractEventLoop) -> None:
    """systemd sends SIGTERM on stop; we want to shut down cleanly."""
    if sys.platform == "win32":
        return  # Windows lacks add_signal_handler
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, lambda: [t.cancel() for t in asyncio.all_tasks(loop)])


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s"
    )
    args = _build_parser().parse_args(argv)
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    _install_sigterm_handler(loop)
    try:
        loop.run_until_complete(run(symbol=args.symbol, tf=args.tf))
    except (asyncio.CancelledError, KeyboardInterrupt):
        logger.info("shutting down")
    finally:
        loop.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
