"""Phase 1 integration test: Postgres connectivity + TimescaleDB extension.

Requires a running Postgres+TimescaleDB instance (locally via docker compose,
or on the VPS). Connection params loaded from env (see infra/secrets/.env.example).

Run locally:
    docker compose -f infra/docker-compose.yml up -d
    cp infra/secrets/.env.example .env  # edit values
    pytest tests/integration/test_postgres_connection.py -v
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def _postgres_dsn() -> str:
    """Build DSN from env. Hard-fail (KeyError) if any var missing — no silent defaults."""
    return (
        f"postgresql://{os.environ['POSTGRES_USER']}:"
        f"{os.environ['POSTGRES_PASSWORD']}@"
        f"{os.environ['POSTGRES_HOST']}:"
        f"{os.environ['POSTGRES_PORT']}/"
        f"{os.environ['POSTGRES_DB']}"
    )


@pytest.mark.integration
def test_postgres_connects() -> None:
    """Postgres must be reachable on the configured host/port with the configured creds."""
    psycopg = pytest.importorskip("psycopg")
    with psycopg.connect(_postgres_dsn()) as conn, conn.cursor() as cur:
        cur.execute("SELECT 1")
        assert cur.fetchone() == (1,), "Postgres returned unexpected value for SELECT 1"


@pytest.mark.integration
def test_timescaledb_extension_loaded() -> None:
    """TimescaleDB extension must be present in the trading database."""
    psycopg = pytest.importorskip("psycopg")
    with psycopg.connect(_postgres_dsn()) as conn, conn.cursor() as cur:
        cur.execute("SELECT extname FROM pg_extension WHERE extname = 'timescaledb'")
        row = cur.fetchone()
        assert row is not None, (
            "timescaledb extension not loaded. "
            "Verify infra/postgres/init.sql ran and image is timescale/timescaledb."
        )
        assert row[0] == "timescaledb"


@pytest.mark.integration
def test_trader_role_has_correct_grants() -> None:
    """The 'trader' role must exist and own (or have access to) the brain schema."""
    psycopg = pytest.importorskip("psycopg")
    with psycopg.connect(_postgres_dsn()) as conn, conn.cursor() as cur:
        cur.execute("SELECT 1 FROM pg_roles WHERE rolname = 'trader'")
        assert cur.fetchone() is not None, "Role 'trader' missing"

        cur.execute(
            "SELECT has_schema_privilege('trader', 'brain', 'USAGE')"
        )
        row = cur.fetchone()
        assert row is not None and row[0] is True, "trader role lacks USAGE on brain schema"
