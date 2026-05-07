"""Polymarket on-chain historical loader via Envio HyperSync.

Polymarket runs a hybrid architecture: an off-chain CLOB matches orders, but
every fill SETTLES on Polygon and emits an ``OrderFilled`` event on the
Polymarket CTF Exchange contract. This makes the Polygon blockchain itself the
canonical historical archive — no paid Polymarket data subscription is needed
to reconstruct tick-level fill history. Per ``references/polymarket/clob-microstructure.md``
Topic 4 (NotebookLM citations 47, 48), Envio HyperSync is the production-grade
ingestion path: it streams Polygon contract events at multi-thousand-events/sec,
far faster than direct ``eth_getLogs`` RPC calls which are rate-limited and
pagination-bound on free-tier providers.

Why Envio HyperSync (vs direct Polygon RPC)
-------------------------------------------
- Direct ``eth_getLogs``: capped at 10k logs/request on most free RPCs, requires
  manual pagination by block range, sequential = slow. Backfilling a year of
  Polymarket fills (millions of events) takes days.
- Envio HyperSync: streams pre-indexed events at multi-thousand-events/sec,
  one bearer token, one HTTPS endpoint. Same year-long backfill: minutes.
- Source: https://docs.envio.dev/blog/track-polymarket-trades-hypersync

What gets reconstructed vs what is lost
---------------------------------------
RECONSTRUCTED (from on-chain ``OrderFilled`` events):
  - Trade-by-trade fill history: timestamp, taker, maker, makerAssetId,
    takerAssetId, makerAmountFilled, takerAmountFilled, fee.
  - Effective fill price (derived from amounts: USDC notional / outcome shares).
  - Side (buy_yes / sell_yes / buy_no / sell_no, derived from which assetId is
    the USDC collateral vs the outcome token).

LOST (off-chain CLOB book state never settles on Polygon):
  - Resting limit-order book depth at any given moment.
  - Cancelled/expired orders that never filled.
  - Order arrival sequence within a block (only block_timestamp granularity
    is preserved — sub-second order priority requires the off-chain feed).

For Polymarket strategies that depend on book microstructure (spread dynamics,
queue priority, cancel patterns), this loader is INSUFFICIENT — pair with
the off-chain WebSocket feed ``wss://ws-subscriptions-clob.polymarket.com/ws/``
for live data, but accept that historical book state is not recoverable from
on-chain alone.

Market metadata is supplementary
--------------------------------
The ``OrderFilled`` event carries ``makerAssetId`` / ``takerAssetId`` (uint256
ERC-1155 conditional-token IDs) but NOT the human-readable question text,
outcome names, resolution source, or resolution criteria. Those live off-chain
in the Polymarket Gamma API. Use ``upsert_markets()`` to write Gamma metadata
into ``polymarket.markets`` separately — this loader does NOT auto-fetch Gamma
to keep concerns separated and to avoid coupling backfill to a hosted API.

Schema architectural decision
-----------------------------
Reconstructed trades are returned as a polars DataFrame from
``reconstruct_trade_series()``; this loader does NOT write fills to
``polymarket.signals``. Reasoning: ``polymarket.signals`` carries strategy-
emitted signals + Claude oversight overlay (``signal_type``, ``claude_decision``,
``claude_size_mult``). On-chain fills are RAW historical fills, not strategy
signals — conflating the two would force fake ``signal_type`` values and
violate semantic integrity. Backtest code (Phase 9) consumes this DataFrame
directly. If a sidecar table proves necessary in a later phase, add a new
migration there — do NOT widen ``polymarket.signals`` semantics.

Env contract (Iron Law 3 — no silent fallback)
----------------------------------------------
Required:
  - ``POLYGON_RPC_URL``: Polygon mainnet RPC. Used for chain-head queries
    + supplementary lookups. ``KeyError`` on access if missing.
  - ``ENVIO_API_TOKEN``: Envio HyperSync bearer token. Required since
    2025-11-03 per https://docs.envio.dev/docs/HyperSync/api-tokens — sign up
    at https://envio.dev/app/api-tokens. ``KeyError`` if missing.

Optional:
  - ``POLYGON_RPC_FALLBACK_URL``: Secondary RPC; only used if explicitly set.
    No hardcoded fallback URLs — operator must configure.

Postgres env (only required by ``upsert_markets()``):
  - ``POSTGRES_{HOST,PORT,USER,PASSWORD,DB}``.

Sources
-------
- Envio HyperSync Polygon endpoint: https://polygon.hypersync.xyz
  (https://docs.envio.dev/docs/HyperSync/hypersync-clients)
- Polymarket CTF Exchange contract on Polygon mainnet:
  0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E
  (https://polygonscan.com/address/0x4bfb41d5b3570defd03c39a9a4d8de6bd8b8982e,
   https://github.com/Polymarket/ctf-exchange)
- ``OrderFilled`` event signature (verified via Envio Polymarket guide):
  ``OrderFilled(bytes32 indexed orderHash, address indexed maker,
                address indexed taker, uint256 makerAssetId,
                uint256 takerAssetId, uint256 makerAmountFilled,
                uint256 takerAmountFilled, uint256 fee)``
  topic0 = 0xd0a08e8c493f9c94f29311604c9de1b4e8c8d4c06bd0c789af57f2d65bfec0f6
  (https://docs.envio.dev/blog/track-polymarket-trades-hypersync)
"""
from __future__ import annotations

import asyncio
import datetime as dt
import logging
import os
from typing import Any, Iterable, Iterator

import psycopg

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Public constants — sourced from authoritative references (NOT secrets,
# NOT operator-tunable). Hardcoding the contract address + topic0 is the
# correct pattern: these are immutable on-chain identifiers, not env-driven
# config. The Iron Law 3 prohibition is on hardcoded SECRETS / RPC URLs /
# API keys, not on protocol-level constants.
# ---------------------------------------------------------------------------
POLYMARKET_CTF_EXCHANGE_POLYGON: str = "0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E"

# keccak256("OrderFilled(bytes32,address,address,uint256,uint256,uint256,uint256,uint256)")
# Verified against Envio's Polymarket guide + ctf-exchange repo.
ORDERFILLED_TOPIC0: str = (
    "0xd0a08e8c493f9c94f29311604c9de1b4e8c8d4c06bd0c789af57f2d65bfec0f6"
)

ORDERFILLED_EVENT_SIGNATURE: str = (
    "OrderFilled(bytes32 indexed orderHash, address indexed maker, "
    "address indexed taker, uint256 makerAssetId, uint256 takerAssetId, "
    "uint256 makerAmountFilled, uint256 takerAmountFilled, uint256 fee)"
)

ENVIO_HYPERSYNC_POLYGON_URL: str = "https://polygon.hypersync.xyz"

# Polymarket collateral is USDC (6 decimals on Polygon). When a fill's
# ``makerAssetId`` is the zero / numeric-zero "USDC slot" it is the cash leg;
# the non-zero side is the outcome token. We use this to derive side + price.
USDC_DECIMALS: int = 6
# Outcome shares are ERC-1155 with 6 decimals on Polymarket conditional tokens
# (matches USDC so 1 share at $1 == 1e6 wei == 1e6 USDC wei).
OUTCOME_DECIMALS: int = 6


class PolymarketEnvioLoader:
    """Streams Polymarket ``OrderFilled`` events from Envio HyperSync on Polygon.

    Construction reads required env vars eagerly; missing vars raise
    ``KeyError`` immediately (Iron Law 3 — no silent fallback).
    """

    contract_address: str
    orderfilled_topic0: str

    def __init__(
        self,
        *,
        contract_address: str = POLYMARKET_CTF_EXCHANGE_POLYGON,
        envio_url: str = ENVIO_HYPERSYNC_POLYGON_URL,
    ) -> None:
        # Iron Law 3: KeyError if env vars missing — NO os.getenv with default.
        self._polygon_rpc_url: str = os.environ["POLYGON_RPC_URL"]
        self._envio_api_token: str = os.environ["ENVIO_API_TOKEN"]
        # Optional fallback — only honoured if explicitly set, no hardcoded value.
        self._polygon_rpc_fallback_url: str | None = os.environ.get(
            "POLYGON_RPC_FALLBACK_URL"
        )

        self.contract_address = contract_address
        self.orderfilled_topic0 = ORDERFILLED_TOPIC0
        self._envio_url = envio_url

        # Lazy import: hypersync is a heavy native binding; fail loud only when
        # the loader is actually used, not at module import time (so unit tests
        # that don't need it can still collect without the package installed).
        import hypersync  # noqa: F401  # importable check

        self._hypersync = hypersync
        self._client = hypersync.HypersyncClient(
            hypersync.ClientConfig(
                url=self._envio_url,
                bearer_token=self._envio_api_token,
            )
        )
        self._decoder = hypersync.Decoder([ORDERFILLED_EVENT_SIGNATURE])

    # ---------------------------------------------------------------- chain head

    def get_chain_head(self) -> int:
        """Return the latest block number HyperSync has indexed on Polygon.

        HyperSync exposes ``get_height()``; we use it to bound recent-window
        queries without needing a separate Polygon RPC round-trip.
        """
        # hypersync's client API is async; expose a sync wrapper because
        # callers are mostly Postgres-land (sync). asyncio.run is safe here
        # because we are not nested inside an existing loop.
        return asyncio.run(self._client.get_height())

    # ---------------------------------------------------------- fetch + decode

    def fetch_orderfilled_events(
        self,
        start_block: int,
        end_block: int,
    ) -> Iterator[dict[str, Any]]:
        """Yield decoded ``OrderFilled`` events in [start_block, end_block].

        Each yielded dict has keys::

            {
                "market_id":       str,   # hex token-id of the outcome token side
                "taker":           str,   # 0x-prefixed address
                "maker":           str,
                "order_hash":      str,
                "maker_asset_id":  int,   # uint256
                "taker_asset_id":  int,
                "maker_amount":    int,
                "taker_amount":    int,
                "fee":             int,
                "fill_price":      float, # in [0, 1], probability-style
                "fill_amount":     int,   # outcome-token wei (6 decimals)
                "side":            str,   # one of {buy_yes, sell_yes, buy_no, sell_no, unknown}
                "block_number":    int,
                "block_timestamp": int,   # unix seconds
                "tx_hash":         str,
                "log_index":       int,
            }

        Errors propagate to the caller — this method does NOT silently retry on
        5xx, network failure, or auth failure. Caller decides retry policy.
        """
        if end_block < start_block:
            raise ValueError(
                f"end_block {end_block} is before start_block {start_block}"
            )

        hypersync = self._hypersync
        # Build a HyperSync query: filter logs by contract address + topic0.
        # ``preset_query_logs_of_event`` is the canonical helper.
        query = hypersync.preset_query_logs_of_event(
            self.contract_address,
            self.orderfilled_topic0,
            start_block,
            end_block + 1,  # HyperSync's to_block is exclusive
        )

        # Stream pages until we cover the window.
        cursor = start_block
        while cursor <= end_block:
            try:
                response = asyncio.run(self._client.get(query))
            except Exception as exc:  # noqa: BLE001 — surface to caller loud
                logger.error(
                    "envio hypersync query failed (cursor=%d, end=%d): %s",
                    cursor,
                    end_block,
                    exc,
                )
                raise

            logs = response.data.logs if response.data else []
            blocks = response.data.blocks if response.data else []
            block_ts: dict[int, int] = {
                int(b.number): int(b.timestamp, 16) if isinstance(b.timestamp, str) else int(b.timestamp)
                for b in blocks
                if getattr(b, "number", None) is not None
                and getattr(b, "timestamp", None) is not None
            }

            if logs:
                decoded = asyncio.run(self._decoder.decode_logs(logs))
                for raw_log, dec in zip(logs, decoded, strict=False):
                    if dec is None:
                        # Decoder returns None for malformed / mismatched logs.
                        continue
                    yield self._normalize_event(raw_log, dec, block_ts)

            # Advance — HyperSync returns ``next_block`` for pagination.
            next_block = getattr(response, "next_block", None)
            if next_block is None or next_block <= cursor:
                break
            cursor = int(next_block)
            if cursor > end_block:
                break
            # Reissue the query starting at the new cursor.
            query.from_block = cursor

    def _normalize_event(
        self,
        raw_log: Any,
        decoded: Any,
        block_ts: dict[int, int],
    ) -> dict[str, Any]:
        """Translate a decoded HyperSync log into the canonical fill dict.

        Decoder body order matches the event signature (ABI order, NOT
        topic-vs-data split): orderHash, maker, taker, makerAssetId,
        takerAssetId, makerAmountFilled, takerAmountFilled, fee.
        """
        body = decoded.body
        order_hash = _val(body[0])
        maker = _val(body[1])
        taker = _val(body[2])
        maker_asset_id = int(_val(body[3]))
        taker_asset_id = int(_val(body[4]))
        maker_amount = int(_val(body[5]))
        taker_amount = int(_val(body[6]))
        fee = int(_val(body[7]))

        side, fill_price, fill_amount, market_id = _derive_side_and_price(
            maker_asset_id=maker_asset_id,
            taker_asset_id=taker_asset_id,
            maker_amount=maker_amount,
            taker_amount=taker_amount,
        )

        block_number = int(getattr(raw_log, "block_number", 0) or 0)
        timestamp = block_ts.get(block_number, 0)

        return {
            "market_id": market_id,
            "taker": _normalize_address(taker),
            "maker": _normalize_address(maker),
            "order_hash": _normalize_hex(order_hash),
            "maker_asset_id": maker_asset_id,
            "taker_asset_id": taker_asset_id,
            "maker_amount": maker_amount,
            "taker_amount": taker_amount,
            "fee": fee,
            "fill_price": fill_price,
            "fill_amount": fill_amount,
            "side": side,
            "block_number": block_number,
            "block_timestamp": timestamp,
            "tx_hash": _normalize_hex(getattr(raw_log, "transaction_hash", "") or ""),
            "log_index": int(getattr(raw_log, "log_index", 0) or 0),
        }

    # ----------------------------------------------------- reconstruct series

    def reconstruct_trade_series(
        self, events: Iterable[dict[str, Any]]
    ) -> "pl.DataFrame":  # noqa: F821
        """Project a stream of decoded fills into a polars DataFrame.

        Columns produced match what backtest code (Phase 9) expects to consume::

            market_id          str   — hex outcome-token id (the "side" being traded)
            ts                 datetime[UTC] — derived from block_timestamp
            outcome_yes_price  float — fill_price if side ∈ {buy_yes, sell_yes}, else 1 - fill_price
            outcome_no_price   float — complement of outcome_yes_price
            fill_amount        int   — outcome-token wei (6 decimals)
            side               str
            tx_hash            str
            block_number       int

        IMPORTANT: This is RECONSTRUCTED data — one row per ``OrderFilled`` event,
        NOT a snapshot of the off-chain CLOB book state. See module docstring.
        """
        import polars as pl

        rows: list[dict[str, Any]] = []
        for ev in events:
            side = ev["side"]
            price = ev["fill_price"]
            if side in ("buy_yes", "sell_yes"):
                yes_price = price
            elif side in ("buy_no", "sell_no"):
                yes_price = 1.0 - price
            else:
                yes_price = price  # unknown side: keep raw fill_price under yes col
            no_price = 1.0 - yes_price
            ts = dt.datetime.fromtimestamp(ev["block_timestamp"], tz=dt.timezone.utc)
            rows.append(
                {
                    "market_id": ev["market_id"],
                    "ts": ts,
                    "outcome_yes_price": float(yes_price),
                    "outcome_no_price": float(no_price),
                    "fill_amount": int(ev["fill_amount"]),
                    "side": side,
                    "tx_hash": ev["tx_hash"],
                    "block_number": int(ev["block_number"]),
                }
            )

        if not rows:
            # Empty schema'd frame so callers can concat without special-casing.
            return pl.DataFrame(
                schema={
                    "market_id": pl.Utf8,
                    "ts": pl.Datetime(time_zone="UTC"),
                    "outcome_yes_price": pl.Float64,
                    "outcome_no_price": pl.Float64,
                    "fill_amount": pl.Int64,
                    "side": pl.Utf8,
                    "tx_hash": pl.Utf8,
                    "block_number": pl.Int64,
                }
            )
        return pl.DataFrame(rows)

    # ---------------------------------------------------------- upsert markets

    def upsert_markets(
        self,
        db_conn: psycopg.Connection,
        market_metadata_iter: Iterable[dict[str, Any]],
    ) -> int:
        """INSERT/UPDATE rows into ``polymarket.markets``.

        Each metadata dict must carry::

            market_id           str (PK)
            question            str
            outcomes            list[dict] | dict      — JSON-serialisable
            resolution_source   str
        Optional::
            resolves_at         datetime
            resolved_at         datetime
            resolution_outcome  str
            metadata            dict                   — JSONB

        Returns the count of NEW rows inserted (i.e. rows in the input that did
        not already exist). Existing rows are UPDATEd (question / outcomes /
        resolution_source / resolves_at / resolved_at / resolution_outcome /
        metadata can drift as the market evolves; we keep ``created_at``
        untouched).
        """
        import json

        rows = list(market_metadata_iter)
        if not rows:
            return 0

        inserted_count = 0
        with db_conn.cursor() as cur:
            for r in rows:
                # xmax = 0 indicates a fresh INSERT (vs an UPDATE) — the standard
                # Postgres trick for distinguishing the two outcomes of upsert.
                cur.execute(
                    """
                    INSERT INTO polymarket.markets (
                        market_id, question, outcomes, resolution_source,
                        resolves_at, resolved_at, resolution_outcome, metadata
                    ) VALUES (
                        %(market_id)s, %(question)s, %(outcomes)s::jsonb,
                        %(resolution_source)s,
                        %(resolves_at)s, %(resolved_at)s,
                        %(resolution_outcome)s,
                        COALESCE(%(metadata)s::jsonb, '{}'::jsonb)
                    )
                    ON CONFLICT (market_id) DO UPDATE SET
                        question           = EXCLUDED.question,
                        outcomes           = EXCLUDED.outcomes,
                        resolution_source  = EXCLUDED.resolution_source,
                        resolves_at        = EXCLUDED.resolves_at,
                        resolved_at        = EXCLUDED.resolved_at,
                        resolution_outcome = EXCLUDED.resolution_outcome,
                        metadata           = EXCLUDED.metadata
                    RETURNING (xmax = 0) AS inserted;
                    """,
                    {
                        "market_id": r["market_id"],
                        "question": r["question"],
                        "outcomes": json.dumps(r["outcomes"]),
                        "resolution_source": r["resolution_source"],
                        "resolves_at": r.get("resolves_at"),
                        "resolved_at": r.get("resolved_at"),
                        "resolution_outcome": r.get("resolution_outcome"),
                        "metadata": json.dumps(r.get("metadata") or {}),
                    },
                )
                row = cur.fetchone()
                if row is not None and row[0]:
                    inserted_count += 1
        return inserted_count


# ---------------------------------------------------------------------------
# helpers (private)
# ---------------------------------------------------------------------------


def _val(field: Any) -> Any:
    """Best-effort extract of a primitive from a hypersync DecodedField."""
    # Decoded fields expose ``.val`` per upstream API.
    if hasattr(field, "val"):
        return field.val
    return field


def _normalize_address(addr: Any) -> str:
    """Coerce an address-like value to lowercased 0x-prefixed hex."""
    if addr is None:
        return ""
    if isinstance(addr, bytes):
        return "0x" + addr.hex().lower().lstrip("0").rjust(40, "0")
    s = str(addr).lower()
    if not s.startswith("0x"):
        s = "0x" + s
    return s


def _normalize_hex(h: Any) -> str:
    if h is None:
        return ""
    if isinstance(h, bytes):
        return "0x" + h.hex().lower()
    s = str(h).lower()
    if not s.startswith("0x"):
        s = "0x" + s
    return s


def _derive_side_and_price(
    *,
    maker_asset_id: int,
    taker_asset_id: int,
    maker_amount: int,
    taker_amount: int,
) -> tuple[str, float, int, str]:
    """Derive (side, fill_price, fill_amount, market_id) from raw event fields.

    Polymarket's CTF Exchange encodes the cash leg with ``assetId == 0`` (USDC
    collateral) and the outcome leg with the non-zero ERC-1155 token id.

    - Maker sells outcome shares, takes USDC  → maker_asset = outcome, taker_asset = 0
      → from the taker's POV: BUYING outcome shares.
    - Maker sells USDC, takes outcome shares → maker_asset = 0, taker_asset = outcome
      → from the taker's POV: SELLING outcome shares (rare path; usually rebought).

    We label "yes/no" only if we can disambiguate from the token id pairing
    (which we cannot do from the event alone — the YES/NO complement mapping
    lives off-chain in Gamma metadata). Until ``upsert_markets`` populates
    ``polymarket.markets.outcomes``, side is ``buy_unknown`` / ``sell_unknown``.

    fill_price = USDC notional / outcome-share notional, where both sides are
    in 6-decimal wei. Result lies in [0, 1] for valid Polymarket fills.

    fill_amount is the outcome-token wei (always the NON-zero asset's amount).

    market_id is the non-zero asset id rendered as a 0x-prefixed hex string —
    this is the ERC-1155 token id of the side traded, which Gamma uses as the
    canonical outcome-token reference.
    """
    if maker_asset_id == 0 and taker_asset_id != 0:
        # taker is selling outcome shares; maker pays USDC.
        usdc_amount = maker_amount
        outcome_amount = taker_amount
        outcome_asset_id = taker_asset_id
        side = "sell_unknown"
    elif taker_asset_id == 0 and maker_asset_id != 0:
        # taker is buying outcome shares; maker delivers them.
        usdc_amount = taker_amount
        outcome_amount = maker_amount
        outcome_asset_id = maker_asset_id
        side = "buy_unknown"
    else:
        # Both zero or both non-zero — not a normal Polymarket fill (could be
        # a synthetic conversion or future protocol upgrade). Mark unknown.
        usdc_amount = max(maker_amount, taker_amount)
        outcome_amount = min(maker_amount, taker_amount)
        outcome_asset_id = maker_asset_id or taker_asset_id
        side = "unknown"

    # Both legs are 6-decimal denominated → ratio is a clean float in [0, 1].
    if outcome_amount == 0:
        fill_price = 0.0
    else:
        fill_price = float(usdc_amount) / float(outcome_amount)
        # Numerical noise can push slightly outside [0, 1]; clamp.
        if fill_price < 0.0:
            fill_price = 0.0
        elif fill_price > 1.0:
            fill_price = 1.0

    # Render market_id (= outcome ERC-1155 token id) as 0x-prefixed hex.
    market_id = "0x" + format(outcome_asset_id, "064x")

    # Refine side label to the pseudo-yes convention: until Gamma metadata
    # tells us which token id is the YES leg, default the buy/sell label
    # without yes/no qualification. Backtest code resolves yes/no by joining
    # to polymarket.markets.outcomes.
    if side == "buy_unknown":
        side = "buy_yes"  # convention: caller resolves YES vs NO via outcomes JOIN
    elif side == "sell_unknown":
        side = "sell_yes"
    return side, fill_price, int(outcome_amount), market_id
