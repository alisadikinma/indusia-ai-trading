"""Gap detector for brain.ohlcv.

For a given (pair, tf, [start, end]) window, returns the list of contiguous
missing-bar ranges. Implementation uses Postgres-side generate_series LEFT
JOIN — much faster than pulling all rows into Python.

Only timeframes whose bar interval can be expressed as a Postgres INTERVAL
are supported here; the production set is {1m, 5m, 15m, 1h, 4h, 1d}.

CLI:
    python -m infra.data_loader.gap_detector \
        --pair BTC/USDT --tf 1m --start 2024-01-02 --end 2024-01-30 [--json]
"""
from __future__ import annotations

import argparse
import dataclasses
import datetime as dt
import json
import logging
import os
import sys

import psycopg

logger = logging.getLogger(__name__)

_TF_TO_INTERVAL = {
    "1m": "1 minute",
    "5m": "5 minutes",
    "15m": "15 minutes",
    "1h": "1 hour",
    "4h": "4 hours",
    "1d": "1 day",
}


@dataclasses.dataclass(frozen=True)
class Gap:
    start: dt.datetime
    end: dt.datetime  # inclusive (last missing bar timestamp)

    def to_tuple(self) -> tuple[dt.datetime, dt.datetime]:
        return (self.start, self.end)


def _dsn() -> str:
    return (
        f"postgresql://{os.environ['POSTGRES_USER']}:"
        f"{os.environ['POSTGRES_PASSWORD']}@"
        f"{os.environ['POSTGRES_HOST']}:"
        f"{os.environ['POSTGRES_PORT']}/"
        f"{os.environ['POSTGRES_DB']}"
    )


class GapDetector:
    def __init__(self, dsn: str | None = None) -> None:
        self._dsn = dsn or _dsn()

    def find_gaps(
        self,
        pair: str,
        tf: str,
        start: dt.datetime,
        end: dt.datetime,
    ) -> list[tuple[dt.datetime, dt.datetime]]:
        """Return list of (gap_start, gap_end) tuples (UTC, inclusive endpoints).

        Consecutive missing bars are merged into a single range.
        """
        if tf not in _TF_TO_INTERVAL:
            raise ValueError(f"Unsupported tf {tf!r}")
        if end < start:
            raise ValueError(f"end {end} before start {start}")

        interval = _TF_TO_INTERVAL[tf]
        # Identify each missing bar, then collapse runs by tagging breakpoints.
        # The "island" trick: subtract row_number * interval from each missing
        # bar's ts; a contiguous run shares the same anchor.
        sql = f"""
            WITH bars AS (
                SELECT generate_series(
                    %(start)s::timestamptz,
                    %(end)s::timestamptz,
                    INTERVAL '{interval}'
                ) AS ts
            ),
            missing AS (
                SELECT b.ts
                FROM bars b
                LEFT JOIN brain.ohlcv o
                  ON o.pair = %(pair)s
                 AND o.tf   = %(tf)s
                 AND o.ts   = b.ts
                WHERE o.ts IS NULL
            ),
            islands AS (
                SELECT
                    ts,
                    ts - (
                        ROW_NUMBER() OVER (ORDER BY ts) * INTERVAL '{interval}'
                    ) AS anchor
                FROM missing
            )
            SELECT MIN(ts) AS gap_start, MAX(ts) AS gap_end
            FROM islands
            GROUP BY anchor
            ORDER BY gap_start;
        """
        with psycopg.connect(self._dsn) as conn, conn.cursor() as cur:
            cur.execute(
                sql,
                {"pair": pair, "tf": tf, "start": start, "end": end},
            )
            rows = cur.fetchall()
        return [(s, e) for (s, e) in rows]


# ---------------------------------------------------------------------- CLI


def _parse_iso(s: str) -> dt.datetime:
    # Accept date-only (interpret as 00:00 UTC) or full ISO datetime.
    if len(s) == 10:
        d = dt.date.fromisoformat(s)
        return dt.datetime(d.year, d.month, d.day, tzinfo=dt.timezone.utc)
    out = dt.datetime.fromisoformat(s)
    if out.tzinfo is None:
        out = out.replace(tzinfo=dt.timezone.utc)
    return out


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m infra.data_loader.gap_detector",
        description="Find missing OHLCV bars in brain.ohlcv.",
    )
    p.add_argument("--pair", required=True, help="e.g. BTC/USDT")
    p.add_argument("--tf", required=True, choices=sorted(_TF_TO_INTERVAL))
    p.add_argument("--start", required=True, help="YYYY-MM-DD or ISO datetime")
    p.add_argument("--end", required=True, help="YYYY-MM-DD or ISO datetime")
    p.add_argument("--json", action="store_true", help="JSON output")
    return p


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO)
    args = _build_parser().parse_args(argv)
    gd = GapDetector()
    gaps = gd.find_gaps(
        pair=args.pair,
        tf=args.tf,
        start=_parse_iso(args.start),
        end=_parse_iso(args.end),
    )
    payload = {
        "pair": args.pair,
        "tf": args.tf,
        "start": args.start,
        "end": args.end,
        "gaps": [
            {"start": s.isoformat(), "end": e.isoformat()} for (s, e) in gaps
        ],
        "gap_count": len(gaps),
    }
    # Default output is JSON (CLI is consumed programmatically by the post-mortem
    # cron in Phase 6). The --json flag is accepted for forward-compat / clarity.
    _ = args.json
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
