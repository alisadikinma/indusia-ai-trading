"""Phase E integration test: polymarket.* schema exists after migration applied.

Verifies that 003_polymarket_schema.sql created the 6 polymarket.* tables
(mirroring brain.* with Polymarket-specific additions: polymarket.markets) and
that the append-only Iron Law 5 trigger applies to polymarket.brain_journal
identically to brain.brain_journal.

Per ADR-001:
  - Crypto bot owns brain.* schema (legacy name kept for stability).
  - Polymarket bot owns polymarket.* schema (canonical bot-named forward).
"""
from __future__ import annotations

import os

import pytest


REQUIRED_POLYMARKET_TABLES = (
    "markets",  # Polymarket-specific: market metadata + resolution outcome
    "signals",
    "brain_journal",
    "backtest_runs",
    "iteration_runs",
    "equity_curve",
)


REQUIRED_MARKETS_COLUMNS = (
    "market_id",
    "question",
    "outcomes",
    "resolution_source",
    "created_at",
    "resolves_at",
    "resolved_at",
    "resolution_outcome",
    "metadata",
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
def test_polymarket_schema_exists() -> None:
    """polymarket schema must exist as a top-level Postgres schema."""
    psycopg = pytest.importorskip("psycopg")
    with psycopg.connect(_dsn()) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT EXISTS ("
            "  SELECT 1 FROM information_schema.schemata "
            "  WHERE schema_name = 'polymarket'"
            ")"
        )
        row = cur.fetchone()
        assert row is not None and row[0] is True, (
            "polymarket schema not found — was 003_polymarket_schema.sql applied?"
        )


@pytest.mark.integration
@pytest.mark.parametrize("table_name", REQUIRED_POLYMARKET_TABLES)
def test_polymarket_table_exists(table_name: str) -> None:
    """Each of the 6 polymarket.* tables must exist (empty is fine)."""
    psycopg = pytest.importorskip("psycopg")
    with psycopg.connect(_dsn()) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT EXISTS ("
            "  SELECT 1 FROM information_schema.tables "
            "  WHERE table_schema = 'polymarket' AND table_name = %s"
            ")",
            (table_name,),
        )
        row = cur.fetchone()
        assert row is not None and row[0] is True, (
            f"polymarket.{table_name} not found — was 003_polymarket_schema.sql applied?"
        )


@pytest.mark.integration
@pytest.mark.parametrize("column_name", REQUIRED_MARKETS_COLUMNS)
def test_polymarket_markets_has_required_columns(column_name: str) -> None:
    """polymarket.markets must have all the metadata columns the bot will write."""
    psycopg = pytest.importorskip("psycopg")
    with psycopg.connect(_dsn()) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT EXISTS ("
            "  SELECT 1 FROM information_schema.columns "
            "  WHERE table_schema = 'polymarket' "
            "    AND table_name = 'markets' "
            "    AND column_name = %s"
            ")",
            (column_name,),
        )
        row = cur.fetchone()
        assert row is not None and row[0] is True, (
            f"polymarket.markets.{column_name} not found"
        )


@pytest.mark.integration
def test_polymarket_brain_journal_rejects_update_and_delete() -> None:
    """polymarket.brain_journal must be append-only (Iron Law 5).

    Trigger function must reference polymarket.brain_journal explicitly,
    NOT copy-paste-leftover brain.brain_journal — that would silently allow
    UPDATE/DELETE on the polymarket side.
    """
    psycopg = pytest.importorskip("psycopg")
    with psycopg.connect(_dsn(), autocommit=True) as conn, conn.cursor() as cur:
        # Insert a probe row.
        cur.execute(
            "INSERT INTO polymarket.brain_journal "
            "(ts, regime, decision, reasoning, confidence) "
            "VALUES (now(), 'test_regime_polymarket', 'approve', "
            "'iron_law_5_polymarket_probe', 5) "
            "RETURNING id"
        )
        result = cur.fetchone()
        assert result is not None
        probe_id = result[0]

        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            cur.execute(
                "UPDATE polymarket.brain_journal SET reasoning = 'tampered' WHERE id = %s",
                (probe_id,),
            )

        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            cur.execute(
                "DELETE FROM polymarket.brain_journal WHERE id = %s",
                (probe_id,),
            )


@pytest.mark.integration
def test_polymarket_markets_resolution_outcome_nullable_until_resolved() -> None:
    """resolution_outcome must accept NULL (sane: market may not be resolved yet)."""
    psycopg = pytest.importorskip("psycopg")
    with psycopg.connect(_dsn(), autocommit=True) as conn, conn.cursor() as cur:
        # Probe: insert an unresolved market, must succeed.
        cur.execute(
            "INSERT INTO polymarket.markets "
            "(market_id, question, outcomes, resolution_source) "
            "VALUES ('test_probe_unresolved_001', "
            "'Will the test pass?', "
            "'[{\"name\": \"YES\", \"token_id\": \"y1\"},"
            " {\"name\": \"NO\", \"token_id\": \"n1\"}]'::jsonb, "
            "'UMA optimistic oracle') "
            "ON CONFLICT (market_id) DO NOTHING"
        )
        cur.execute(
            "SELECT resolution_outcome FROM polymarket.markets "
            "WHERE market_id = 'test_probe_unresolved_001'"
        )
        row = cur.fetchone()
        assert row is not None
        assert row[0] is None, (
            "Unresolved market must have NULL resolution_outcome"
        )
        # Cleanup.
        cur.execute(
            "DELETE FROM polymarket.markets WHERE market_id = 'test_probe_unresolved_001'"
        )
