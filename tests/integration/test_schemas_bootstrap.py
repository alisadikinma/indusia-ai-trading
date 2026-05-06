"""Phase 1 integration test: bootstrap schemas exist after migration applied.

Verifies that 000_bootstrap_schemas.sql created all 6 brain.* tables that the UI
in Phase 1.5 will query, and that Freqtrade will be free to create its public.*
tables (trades, pairlocks) at first run in Phase 3.

Architectural deviation from plan:
  Plan listed 8 tables to bootstrap (including trades, positions).
  Reality: Freqtrade owns and manages trades + pairlocks via its ORM in
  public schema. Pre-creating those would conflict at Freqtrade init.
  Cleaner: schema-separate ownership.
    brain.*  -> our owned tables (6, listed below)
    public.* -> Freqtrade-owned (trades, pairlocks, etc.; auto-created Phase 3)
  UI joins across schemas as needed in Phase 1.5.
"""
from __future__ import annotations

import os

import pytest


REQUIRED_BRAIN_TABLES = (
    "ohlcv",
    "signals",
    "brain_journal",
    "backtest_runs",
    "iteration_runs",
    "equity_curve",
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
@pytest.mark.parametrize("table_name", REQUIRED_BRAIN_TABLES)
def test_brain_table_exists(table_name: str) -> None:
    """Each of the 6 brain.* tables must exist (empty is fine — populated later)."""
    psycopg = pytest.importorskip("psycopg")
    with psycopg.connect(_dsn()) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT EXISTS ("
            "  SELECT 1 FROM information_schema.tables "
            "  WHERE table_schema = 'brain' AND table_name = %s"
            ")",
            (table_name,),
        )
        row = cur.fetchone()
        assert row is not None and row[0] is True, (
            f"brain.{table_name} not found — was 000_bootstrap_schemas.sql applied?"
        )


@pytest.mark.integration
def test_brain_journal_rejects_update_and_delete() -> None:
    """brain.brain_journal must be append-only (Iron Law 5)."""
    psycopg = pytest.importorskip("psycopg")
    with psycopg.connect(_dsn(), autocommit=True) as conn, conn.cursor() as cur:
        # Insert a probe row first so UPDATE/DELETE has a target.
        cur.execute(
            "INSERT INTO brain.brain_journal "
            "(ts, regime, decision, reasoning, confidence) "
            "VALUES (now(), 'test_regime', 'approve', 'iron_law_test', 5) "
            "RETURNING id"
        )
        result = cur.fetchone()
        assert result is not None
        probe_id = result[0]

        # UPDATE must be denied.
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            cur.execute(
                "UPDATE brain.brain_journal SET reasoning = 'tampered' WHERE id = %s",
                (probe_id,),
            )

        # DELETE must be denied.
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            cur.execute(
                "DELETE FROM brain.brain_journal WHERE id = %s",
                (probe_id,),
            )


@pytest.mark.integration
def test_freqtrade_can_create_in_public_schema() -> None:
    """Freqtrade must be able to CREATE TABLE in public schema at first run."""
    psycopg = pytest.importorskip("psycopg")
    with psycopg.connect(_dsn(), autocommit=True) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT has_schema_privilege('trader', 'public', 'CREATE')"
        )
        row = cur.fetchone()
        assert row is not None and row[0] is True, (
            "trader role lacks CREATE on public schema — Freqtrade can't init"
        )
