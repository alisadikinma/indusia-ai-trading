"""asyncpg connection-pool helpers for the dashboard API.

Hard-fails on missing env vars (Iron Law 3 / Anti-placeholder rules).
"""
from __future__ import annotations

import os

import asyncpg


def _require(name: str) -> str:
    val = os.environ.get(name)
    if not val:
        raise RuntimeError(
            f"Missing required environment variable: {name}. "
            "pulse-bridge dashboard refuses to start without explicit Postgres credentials."
        )
    return val


def build_dsn() -> str:
    user = _require("POSTGRES_USER")
    password = _require("POSTGRES_PASSWORD")
    host = _require("POSTGRES_HOST")
    port = _require("POSTGRES_PORT")
    db = _require("POSTGRES_DB")
    return f"postgresql://{user}:{password}@{host}:{port}/{db}"


async def create_pool(min_size: int = 1, max_size: int = 8) -> asyncpg.Pool:
    return await asyncpg.create_pool(
        dsn=build_dsn(),
        min_size=min_size,
        max_size=max_size,
        command_timeout=15.0,
    )
