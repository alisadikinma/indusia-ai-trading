"""Phase 2 integration test: Polymarket on-chain historical ingestion via Envio HyperSync.

Validates infra/data_loader/polymarket_envio.py end-to-end against the real
Envio HyperSync Polygon endpoint (https://polygon.hypersync.xyz) and the real
Polymarket CTF Exchange contract on Polygon mainnet
(0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E).

Per ADR-002 + Iron Law 3 (no placeholder data in production code paths):
  - Tests use REAL Envio HyperSync (no mocks).
  - Tests use REAL Postgres for the markets-upsert smoke test.
  - If required env is unset (POLYGON_RPC_URL / ENVIO_API_TOKEN / POSTGRES_*),
    tests skip with a clear reason — they DO NOT silently fall back to mock data.

Required env vars (any missing => skip with explicit reason, except the
"loud-fail" test which deliberately ASSERTS that missing vars raise KeyError):
  - POLYGON_RPC_URL          : Polygon mainnet RPC (any provider — Chainstack,
                               Alchemy, public-node, QuickNode). Loader uses it
                               for supplementary lookups; HyperSync does not need
                               this directly but the constructor demands it per
                               Iron Law 3.
  - ENVIO_API_TOKEN          : Envio HyperSync bearer token. Required since
                               2025-11-03 per https://docs.envio.dev/docs/HyperSync/api-tokens
                               — sign up at https://envio.dev/app/api-tokens.
  - POSTGRES_{HOST,PORT,USER,PASSWORD,DB}: Postgres connection for the upsert test.

Run locally (PowerShell):
    $env:POLYGON_RPC_URL="https://polygon-rpc.com"
    $env:ENVIO_API_TOKEN="<token>"
    pytest tests/integration/test_polymarket_envio.py -v -m integration
"""
from __future__ import annotations

import os
import secrets
from typing import Any

import pytest


REQUIRED_ENV_FOR_LIVE = ("POLYGON_RPC_URL", "ENVIO_API_TOKEN")
REQUIRED_ENV_FOR_DB = (
    "POSTGRES_HOST",
    "POSTGRES_PORT",
    "POSTGRES_USER",
    "POSTGRES_PASSWORD",
    "POSTGRES_DB",
)

REQUIRED_FILL_KEYS = (
    "market_id",
    "taker",
    "maker",
    "fill_price",
    "fill_amount",
    "side",
    "block_timestamp",
)


def _skip_if_missing(env_keys: tuple[str, ...]) -> None:
    missing = [k for k in env_keys if not os.environ.get(k)]
    if missing:
        pytest.skip(
            f"Required env vars not set: {missing}. "
            f"See test docstring for setup. ENVIO_API_TOKEN must be created at "
            f"https://envio.dev/app/api-tokens (free tier, signup required since "
            f"2025-11-03)."
        )


def _dsn() -> str:
    return (
        f"postgresql://{os.environ['POSTGRES_USER']}:"
        f"{os.environ['POSTGRES_PASSWORD']}@"
        f"{os.environ['POSTGRES_HOST']}:"
        f"{os.environ['POSTGRES_PORT']}/"
        f"{os.environ['POSTGRES_DB']}"
    )


@pytest.mark.integration
def test_loader_instantiates_with_required_env() -> None:
    """Loader constructs cleanly when POLYGON_RPC_URL + ENVIO_API_TOKEN set."""
    _skip_if_missing(REQUIRED_ENV_FOR_LIVE)
    pytest.importorskip("hypersync")
    from infra.data_loader.polymarket_envio import PolymarketEnvioLoader

    loader = PolymarketEnvioLoader()
    assert loader.contract_address.lower() == (
        "0x4bfb41d5b3570defd03c39a9a4d8de6bd8b8982e"
    )
    # OrderFilled topic0 (keccak256 of canonical signature with field types):
    assert loader.orderfilled_topic0.startswith("0x")
    assert len(loader.orderfilled_topic0) == 66  # 0x + 64 hex chars


@pytest.mark.integration
def test_missing_envio_token_raises_keyerror() -> None:
    """Iron Law 3: no silent fallback. Missing ENVIO_API_TOKEN must KeyError loudly.

    We monkey-patch os.environ to simulate the missing var rather than mutating
    the test runner's actual env (would break other parametrized tests).
    """
    pytest.importorskip("hypersync")
    from infra.data_loader.polymarket_envio import PolymarketEnvioLoader

    # Save and clear both required vars; confirm KeyError on construction.
    saved = {
        k: os.environ.pop(k)
        for k in REQUIRED_ENV_FOR_LIVE
        if k in os.environ
    }
    try:
        with pytest.raises(KeyError):
            PolymarketEnvioLoader()
    finally:
        os.environ.update(saved)


@pytest.mark.integration
def test_fetch_orderfilled_events_returns_decoded_fills() -> None:
    """Live HyperSync probe: 1k recent blocks must yield > 0 OrderFilled events.

    Polymarket has high enough volume that any 1000-block window (~33 min on
    Polygon @ 2s blocks) contains fills. We pick the most recent finalized block
    minus a safety margin, fetch the prior 1000-block window, and assert at
    least one decoded fill matches the expected dict shape.
    """
    _skip_if_missing(REQUIRED_ENV_FOR_LIVE)
    pytest.importorskip("hypersync")
    from infra.data_loader.polymarket_envio import PolymarketEnvioLoader

    loader = PolymarketEnvioLoader()
    head = loader.get_chain_head()
    # Step back from head to avoid reorg-edge issues; window is 1000 blocks.
    end_block = head - 32
    start_block = end_block - 1000

    events = list(
        loader.fetch_orderfilled_events(
            start_block=start_block, end_block=end_block
        )
    )
    assert len(events) > 0, (
        f"No OrderFilled events found in blocks [{start_block}, {end_block}]. "
        f"Either Polymarket volume crashed (unlikely), the contract address is "
        f"wrong, or the topic0 hash is wrong. Investigate before relaxing."
    )

    sample = events[0]
    for key in REQUIRED_FILL_KEYS:
        assert key in sample, f"Decoded fill missing key {key!r}: keys={list(sample)}"

    # Type sanity:
    assert isinstance(sample["fill_amount"], int) and sample["fill_amount"] >= 0
    assert isinstance(sample["fill_price"], float)
    assert 0.0 <= sample["fill_price"] <= 1.0, (
        f"fill_price {sample['fill_price']} outside [0,1] — Polymarket binary "
        f"outcome prices must lie in this range."
    )
    assert sample["side"] in ("buy_yes", "sell_yes", "buy_no", "sell_no", "unknown")
    assert sample["block_timestamp"] > 0


@pytest.mark.integration
def test_reconstruct_trade_series_shape() -> None:
    """reconstruct_trade_series must produce a polars DataFrame with the columns
    the polymarket.signals table expects (modulo signal_type which is strategy-emitted)."""
    _skip_if_missing(REQUIRED_ENV_FOR_LIVE)
    pytest.importorskip("hypersync")
    pytest.importorskip("polars")
    import polars as pl

    from infra.data_loader.polymarket_envio import PolymarketEnvioLoader

    loader = PolymarketEnvioLoader()
    head = loader.get_chain_head()
    end_block = head - 32
    start_block = end_block - 500

    events = list(
        loader.fetch_orderfilled_events(
            start_block=start_block, end_block=end_block
        )
    )
    if not events:
        pytest.skip("No fills in window — try a larger window or different timing.")

    df = loader.reconstruct_trade_series(events)
    assert isinstance(df, pl.DataFrame)
    expected_cols = {
        "market_id",
        "ts",
        "outcome_yes_price",
        "outcome_no_price",
        "fill_amount",
    }
    assert expected_cols.issubset(set(df.columns)), (
        f"DataFrame missing columns: {expected_cols - set(df.columns)}"
    )
    # Probability invariant: outcome_yes_price + outcome_no_price == 1 for the
    # SAME market at the SAME instant. We only enforce per-row range here
    # because reconstruction emits one row per fill (one side at a time).
    assert (df["outcome_yes_price"] >= 0).all()
    assert (df["outcome_yes_price"] <= 1).all()


@pytest.mark.integration
def test_upsert_markets_round_trips_through_postgres() -> None:
    """Smoke test: upsert_markets writes to real polymarket.markets and idempotent
    re-runs do not error or duplicate.

    Uses a sentinel market_id prefix `test_envio_probe_<random>` and cleans up
    in finally — does NOT pollute production market table.
    """
    _skip_if_missing(REQUIRED_ENV_FOR_LIVE + REQUIRED_ENV_FOR_DB)
    pytest.importorskip("hypersync")
    psycopg = pytest.importorskip("psycopg")

    from infra.data_loader.polymarket_envio import PolymarketEnvioLoader

    loader = PolymarketEnvioLoader()
    probe_id = f"test_envio_probe_{secrets.token_hex(6)}"
    fixture: list[dict[str, Any]] = [
        {
            "market_id": probe_id,
            "question": "Probe: will the test pass?",
            "outcomes": [
                {"name": "YES", "token_id": "probe_yes"},
                {"name": "NO", "token_id": "probe_no"},
            ],
            "resolution_source": "test_envio_probe",
            "metadata": {"source": "envio_test_probe"},
        }
    ]

    try:
        with psycopg.connect(_dsn()) as conn:
            inserted = loader.upsert_markets(conn, fixture)
            conn.commit()
            assert inserted == 1, f"expected 1 insert on first run, got {inserted}"

            # Idempotent re-run — same market_id, must not double-insert nor
            # raise on conflict.
            reinserted = loader.upsert_markets(conn, fixture)
            conn.commit()
            assert reinserted == 0, (
                f"expected 0 inserts on idempotent re-run, got {reinserted}"
            )

            # Confirm row landed.
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT question, resolution_source FROM polymarket.markets "
                    "WHERE market_id = %s",
                    (probe_id,),
                )
                row = cur.fetchone()
                assert row is not None
                assert row[0] == "Probe: will the test pass?"
                assert row[1] == "test_envio_probe"
    finally:
        # Cleanup — never leave probe rows behind.
        with psycopg.connect(_dsn(), autocommit=True) as conn, conn.cursor() as cur:
            cur.execute(
                "DELETE FROM polymarket.markets WHERE market_id LIKE 'test_envio_probe_%'"
            )
