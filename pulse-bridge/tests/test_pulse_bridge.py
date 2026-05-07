"""Phase 4 — pulse-bridge /v1/* tests (HMAC, /v1/decide, /v1/pending_signals,
/v1/context_bundle).

Real Postgres on 127.0.0.1:5544 (Iron Law 3 — no mocks). HMAC verification is
real (constant-time hmac.compare_digest). brain.brain_journal stays append-only
(Iron Law 5) — tests INSERT only, never UPDATE/DELETE.

TDD step 1: ``test_decide_rejects_no_signature`` is the failing-first test. It
will fail with ImportError or 404 until pulse_bridge/main.py and the v1 routes
are wired.
"""
from __future__ import annotations

import hashlib
import hmac as _hmac
import json
import os
import secrets as _secrets
import time
from collections.abc import AsyncIterator
from datetime import datetime, timedelta, timezone

import asyncpg
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient


# ---------------------------------------------------------------------------
# Local fixtures (extend the dashboard conftest with v1-specific helpers).
# ---------------------------------------------------------------------------
# Provide a deterministic HMAC secret for tests if operator hasn't set one.
# We do NOT silently default in production — only inject when running pytest.
if not os.environ.get("PULSE_HMAC_SECRET"):
    os.environ["PULSE_HMAC_SECRET"] = _secrets.token_urlsafe(48)


def _sign(method: str, path: str, body: str, ts: int | None = None) -> dict[str, str]:
    """Return the X-PULSE-* headers Claude must send to /v1/*."""
    if ts is None:
        ts = int(time.time())
    secret = os.environ["PULSE_HMAC_SECRET"].encode("utf-8")
    msg = f"{method}\n{path}\n{ts}\n{body}".encode("utf-8")
    sig = _hmac.new(secret, msg, hashlib.sha256).hexdigest()
    return {
        "X-PULSE-Timestamp": str(ts),
        "X-PULSE-Signature": sig,
    }


@pytest_asyncio.fixture
async def v1_client() -> AsyncIterator[AsyncClient]:
    """Async client bound to the /v1 FastAPI app (pulse_bridge.main:app)."""
    from pulse_bridge.main import app, lifespan_state

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await lifespan_state.startup()
        try:
            yield client
        finally:
            await lifespan_state.shutdown()


async def _insert_pending_signal(
    pool: asyncpg.Pool,
    pair: str = "BTC/USDT",
    tf: str = "15m",
    signal_type: str = "enter_long",
    price: float = 50000.0,
    ts: datetime | None = None,
) -> int:
    """Insert a signal with claude_decision NULL and return its id."""
    if ts is None:
        ts = datetime.now(tz=timezone.utc)
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "INSERT INTO brain.signals (ts, pair, tf, signal_type, price_at_signal, indicators) "
            "VALUES ($1, $2, $3, $4, $5, $6::jsonb) RETURNING id",
            ts,
            pair,
            tf,
            signal_type,
            price,
            "{}",
        )
        return int(row["id"])


# ---------------------------------------------------------------------------
# HMAC auth gate
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_decide_rejects_no_signature(v1_client: AsyncClient) -> None:
    """TDD step 1 — request without HMAC headers must be rejected with 401."""
    body = {
        "signal_id": 1,
        "regime": "trending_up",
        "decision": "approve",
        "reasoning": "test reasoning that is long enough",
        "confidence": 7,
    }
    r = await v1_client.post("/v1/decide", json=body)
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_decide_rejects_invalid_signature(v1_client: AsyncClient) -> None:
    body_str = json.dumps({"signal_id": 1, "regime": "trending_up", "decision": "approve",
                           "reasoning": "x" * 20, "confidence": 5})
    headers = {
        "X-PULSE-Timestamp": str(int(time.time())),
        "X-PULSE-Signature": "deadbeef" * 8,
        "content-type": "application/json",
    }
    r = await v1_client.post("/v1/decide", content=body_str, headers=headers)
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_decide_rejects_stale_timestamp(v1_client: AsyncClient) -> None:
    body_str = json.dumps({"signal_id": 1, "regime": "trending_up", "decision": "approve",
                           "reasoning": "x" * 20, "confidence": 5})
    stale_ts = int(time.time()) - 90
    headers = _sign("POST", "/v1/decide", body_str, ts=stale_ts)
    headers["content-type"] = "application/json"
    r = await v1_client.post("/v1/decide", content=body_str, headers=headers)
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_decide_rejects_future_timestamp(v1_client: AsyncClient) -> None:
    body_str = json.dumps({"signal_id": 1, "regime": "trending_up", "decision": "approve",
                           "reasoning": "x" * 20, "confidence": 5})
    future_ts = int(time.time()) + 90
    headers = _sign("POST", "/v1/decide", body_str, ts=future_ts)
    headers["content-type"] = "application/json"
    r = await v1_client.post("/v1/decide", content=body_str, headers=headers)
    assert r.status_code == 401


# ---------------------------------------------------------------------------
# POST /v1/decide
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_decide_approve_writes_signals_and_journal(
    v1_client: AsyncClient, clean_db: asyncpg.Pool
) -> None:
    signal_id = await _insert_pending_signal(clean_db)
    body = {
        "signal_id": signal_id,
        "regime": "trending_up",
        "decision": "approve",
        "reasoning": "EMA20>EMA50 with ADX rising; trend-confirmed long.",
        "confidence": 8,
        "expected_outcome": "Hit ROI ladder within 4h.",
    }
    body_str = json.dumps(body)
    headers = _sign("POST", "/v1/decide", body_str)
    headers["content-type"] = "application/json"
    r = await v1_client.post("/v1/decide", content=body_str, headers=headers)
    assert r.status_code == 200, r.text
    payload = r.json()
    assert payload["signal_id"] == signal_id
    assert payload["journal_id"] > 0
    assert "decision_recorded_at" in payload

    async with clean_db.acquire() as conn:
        sig_row = await conn.fetchrow(
            "SELECT claude_decision, claude_size_mult, claude_decided_at "
            "FROM brain.signals WHERE id = $1",
            signal_id,
        )
        assert sig_row["claude_decision"] == "approve"
        assert sig_row["claude_size_mult"] is None
        assert sig_row["claude_decided_at"] is not None

        j_row = await conn.fetchrow(
            "SELECT decision, regime, confidence, reasoning "
            "FROM brain.brain_journal WHERE id = $1",
            payload["journal_id"],
        )
        assert j_row["decision"] == "approve"
        assert j_row["regime"] == "trending_up"
        assert j_row["confidence"] == 8


@pytest.mark.asyncio
async def test_decide_veto_writes_journal(
    v1_client: AsyncClient, clean_db: asyncpg.Pool
) -> None:
    signal_id = await _insert_pending_signal(clean_db, pair="ETH/USDT")
    body = {
        "signal_id": signal_id,
        "regime": "ranging",
        "decision": "veto",
        "reasoning": "ADX too low; ranging market, vetoing trend entry.",
        "confidence": 9,
    }
    body_str = json.dumps(body)
    headers = _sign("POST", "/v1/decide", body_str)
    headers["content-type"] = "application/json"
    r = await v1_client.post("/v1/decide", content=body_str, headers=headers)
    assert r.status_code == 200, r.text

    async with clean_db.acquire() as conn:
        sig_row = await conn.fetchrow(
            "SELECT claude_decision FROM brain.signals WHERE id = $1", signal_id
        )
        assert sig_row["claude_decision"] == "veto"


@pytest.mark.asyncio
async def test_decide_resize_validates_size_mult_required(
    v1_client: AsyncClient, clean_db: asyncpg.Pool
) -> None:
    signal_id = await _insert_pending_signal(clean_db, pair="SOL/USDT")
    body = {
        "signal_id": signal_id,
        "regime": "volatile",
        "decision": "resize",
        # size_mult missing
        "reasoning": "Volatility high; downsize but proceed.",
        "confidence": 6,
    }
    body_str = json.dumps(body)
    headers = _sign("POST", "/v1/decide", body_str)
    headers["content-type"] = "application/json"
    r = await v1_client.post("/v1/decide", content=body_str, headers=headers)
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_decide_resize_with_size_mult_succeeds(
    v1_client: AsyncClient, clean_db: asyncpg.Pool
) -> None:
    signal_id = await _insert_pending_signal(clean_db, pair="ADA/USDT")
    body = {
        "signal_id": signal_id,
        "regime": "volatile",
        "decision": "resize",
        "size_mult": 0.6,
        "reasoning": "Vol elevated; halve size to bound drawdown.",
        "confidence": 6,
    }
    body_str = json.dumps(body)
    headers = _sign("POST", "/v1/decide", body_str)
    headers["content-type"] = "application/json"
    r = await v1_client.post("/v1/decide", content=body_str, headers=headers)
    assert r.status_code == 200, r.text
    async with clean_db.acquire() as conn:
        sig_row = await conn.fetchrow(
            "SELECT claude_decision, claude_size_mult FROM brain.signals WHERE id = $1",
            signal_id,
        )
        assert sig_row["claude_decision"] == "resize"
        assert float(sig_row["claude_size_mult"]) == pytest.approx(0.6)


@pytest.mark.asyncio
async def test_decide_idempotency_409_when_already_decided(
    v1_client: AsyncClient, clean_db: asyncpg.Pool
) -> None:
    signal_id = await _insert_pending_signal(clean_db, pair="DOT/USDT")
    body = {
        "signal_id": signal_id,
        "regime": "trending_up",
        "decision": "approve",
        "reasoning": "First decision, should win.",
        "confidence": 7,
    }
    body_str = json.dumps(body)
    headers = _sign("POST", "/v1/decide", body_str)
    headers["content-type"] = "application/json"
    r1 = await v1_client.post("/v1/decide", content=body_str, headers=headers)
    assert r1.status_code == 200

    # Second attempt — same signal_id, fresh ts/sig
    headers2 = _sign("POST", "/v1/decide", body_str)
    headers2["content-type"] = "application/json"
    r2 = await v1_client.post("/v1/decide", content=body_str, headers=headers2)
    assert r2.status_code == 409


@pytest.mark.asyncio
async def test_decide_404_when_signal_not_found(
    v1_client: AsyncClient, clean_db: asyncpg.Pool
) -> None:
    body = {
        "signal_id": 999_999_999,
        "regime": "trending_up",
        "decision": "approve",
        "reasoning": "phantom signal — should 404",
        "confidence": 7,
    }
    body_str = json.dumps(body)
    headers = _sign("POST", "/v1/decide", body_str)
    headers["content-type"] = "application/json"
    r = await v1_client.post("/v1/decide", content=body_str, headers=headers)
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_decide_validates_size_mult_range(
    v1_client: AsyncClient, clean_db: asyncpg.Pool
) -> None:
    signal_id = await _insert_pending_signal(clean_db, pair="LINK/USDT")
    for bad in (0.4, 1.6):
        body = {
            "signal_id": signal_id,
            "regime": "volatile",
            "decision": "resize",
            "size_mult": bad,
            "reasoning": "out-of-range size_mult must be rejected",
            "confidence": 5,
        }
        body_str = json.dumps(body)
        headers = _sign("POST", "/v1/decide", body_str)
        headers["content-type"] = "application/json"
        r = await v1_client.post("/v1/decide", content=body_str, headers=headers)
        assert r.status_code == 422


@pytest.mark.asyncio
async def test_decide_validates_confidence_range(
    v1_client: AsyncClient, clean_db: asyncpg.Pool
) -> None:
    signal_id = await _insert_pending_signal(clean_db, pair="MATIC/USDT")
    for bad in (0, 11):
        body = {
            "signal_id": signal_id,
            "regime": "trending_up",
            "decision": "approve",
            "reasoning": "confidence out of [1,10] — must be rejected",
            "confidence": bad,
        }
        body_str = json.dumps(body)
        headers = _sign("POST", "/v1/decide", body_str)
        headers["content-type"] = "application/json"
        r = await v1_client.post("/v1/decide", content=body_str, headers=headers)
        assert r.status_code == 422


@pytest.mark.asyncio
async def test_decide_rejects_size_mult_when_not_resize(
    v1_client: AsyncClient, clean_db: asyncpg.Pool
) -> None:
    signal_id = await _insert_pending_signal(clean_db, pair="AVAX/USDT")
    body = {
        "signal_id": signal_id,
        "regime": "trending_up",
        "decision": "approve",
        "size_mult": 1.0,  # not allowed unless resize
        "reasoning": "size_mult only valid on resize",
        "confidence": 5,
    }
    body_str = json.dumps(body)
    headers = _sign("POST", "/v1/decide", body_str)
    headers["content-type"] = "application/json"
    r = await v1_client.post("/v1/decide", content=body_str, headers=headers)
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# GET /v1/pending_signals
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_pending_returns_empty_when_no_pending(
    v1_client: AsyncClient, clean_db: asyncpg.Pool
) -> None:
    headers = _sign("GET", "/v1/pending_signals", "")
    r = await v1_client.get("/v1/pending_signals", headers=headers)
    assert r.status_code == 200
    assert r.json() == []


@pytest.mark.asyncio
async def test_pending_returns_signals_with_null_decision(
    v1_client: AsyncClient, clean_db: asyncpg.Pool
) -> None:
    sid1 = await _insert_pending_signal(clean_db, pair="BTC/USDT")
    sid2 = await _insert_pending_signal(clean_db, pair="ETH/USDT")
    headers = _sign("GET", "/v1/pending_signals", "")
    r = await v1_client.get("/v1/pending_signals", headers=headers)
    assert r.status_code == 200
    body = r.json()
    ids = {row["id"] for row in body}
    assert sid1 in ids and sid2 in ids


@pytest.mark.asyncio
async def test_pending_excludes_already_decided(
    v1_client: AsyncClient, clean_db: asyncpg.Pool
) -> None:
    sid_decided = await _insert_pending_signal(clean_db, pair="BTC/USDT")
    sid_pending = await _insert_pending_signal(clean_db, pair="ETH/USDT")
    async with clean_db.acquire() as conn:
        await conn.execute(
            "UPDATE brain.signals SET claude_decision='approve', claude_decided_at=now() "
            "WHERE id=$1",
            sid_decided,
        )
    headers = _sign("GET", "/v1/pending_signals", "")
    r = await v1_client.get("/v1/pending_signals", headers=headers)
    assert r.status_code == 200
    ids = {row["id"] for row in r.json()}
    assert sid_pending in ids
    assert sid_decided not in ids


@pytest.mark.asyncio
async def test_pending_honors_since_filter(
    v1_client: AsyncClient, clean_db: asyncpg.Pool
) -> None:
    old_ts = datetime.now(tz=timezone.utc) - timedelta(hours=6)
    new_ts = datetime.now(tz=timezone.utc) - timedelta(minutes=5)
    sid_old = await _insert_pending_signal(clean_db, pair="BTC/USDT", ts=old_ts)
    sid_new = await _insert_pending_signal(clean_db, pair="ETH/USDT", ts=new_ts)
    # Use a tz-Z-suffixed ISO timestamp so the URL-encoded form matches what
    # httpx puts on the wire (no '+' to wrestle with).
    since_dt = datetime.now(tz=timezone.utc) - timedelta(hours=1)
    since = since_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    path = f"/v1/pending_signals?since={since}"
    headers = _sign("GET", path, "")
    r = await v1_client.get(path, headers=headers)
    assert r.status_code == 200
    ids = {row["id"] for row in r.json()}
    assert sid_new in ids
    assert sid_old not in ids


@pytest.mark.asyncio
async def test_pending_honors_limit(
    v1_client: AsyncClient, clean_db: asyncpg.Pool
) -> None:
    base_ts = datetime.now(tz=timezone.utc) - timedelta(minutes=30)
    for i in range(5):
        await _insert_pending_signal(
            clean_db, pair=f"P{i}/USDT", ts=base_ts + timedelta(seconds=i)
        )
    path = "/v1/pending_signals?limit=2"
    headers = _sign("GET", path, "")
    r = await v1_client.get(path, headers=headers)
    assert r.status_code == 200
    assert len(r.json()) == 2


# ---------------------------------------------------------------------------
# GET /v1/context_bundle
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_context_bundle_has_stable_block_with_iron_laws(
    v1_client: AsyncClient, clean_db: asyncpg.Pool
) -> None:
    path = "/v1/context_bundle?pair=BTC/USDT&tf=15m"
    headers = _sign("GET", path, "")
    r = await v1_client.get(path, headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert "stable" in body
    assert isinstance(body["stable"]["iron_laws"], list)
    assert len(body["stable"]["iron_laws"]) == 5
    # The text must reflect real Iron Laws (not placeholders).
    joined = " ".join(body["stable"]["iron_laws"]).lower()
    assert "risk rail" in joined
    assert "append-only" in joined
    assert "playbook_skills" in body["stable"]


@pytest.mark.asyncio
async def test_context_bundle_has_dynamic_block(
    v1_client: AsyncClient, clean_db: asyncpg.Pool
) -> None:
    path = "/v1/context_bundle?pair=BTC/USDT&tf=15m"
    headers = _sign("GET", path, "")
    r = await v1_client.get(path, headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert "dynamic" in body
    d = body["dynamic"]
    for k in (
        "now",
        "ohlcv_last_4h",
        "open_positions",
        "pending_signals",
        "recent_journal",
        "current_equity_pct",
        "drawdown_pct",
    ):
        assert k in d, f"missing dynamic field: {k}"


@pytest.mark.asyncio
async def test_context_bundle_includes_recent_ohlcv(
    v1_client: AsyncClient, clean_db: asyncpg.Pool
) -> None:
    # Seed some OHLCV rows in the last 4h on a synthetic test pair so the route
    # has data to return regardless of bulk-loaded BTC content.
    pair = "TESTCTX/USDT"
    tf = "15m"
    base = datetime.now(tz=timezone.utc) - timedelta(hours=2)
    async with clean_db.acquire() as conn:
        for i in range(8):
            await conn.execute(
                "INSERT INTO brain.ohlcv (pair, tf, ts, open, high, low, close, volume) "
                "VALUES ($1, $2, $3, $4, $5, $6, $7, $8) "
                "ON CONFLICT DO NOTHING",
                pair, tf, base + timedelta(minutes=15 * i),
                100.0 + i, 101.0 + i, 99.0 + i, 100.5 + i, 1000.0,
            )
    path = f"/v1/context_bundle?pair={pair}&tf={tf}"
    headers = _sign("GET", path, "")
    r = await v1_client.get(path, headers=headers)
    assert r.status_code == 200
    rows = r.json()["dynamic"]["ohlcv_last_4h"]
    assert len(rows) >= 8
    assert {"ts", "o", "h", "l", "c", "v"}.issubset(rows[0].keys())

    # cleanup synthetic rows so reruns stay deterministic
    async with clean_db.acquire() as conn:
        await conn.execute("DELETE FROM brain.ohlcv WHERE pair = $1", pair)


@pytest.mark.asyncio
async def test_context_bundle_includes_pending_signals(
    v1_client: AsyncClient, clean_db: asyncpg.Pool
) -> None:
    sid = await _insert_pending_signal(clean_db, pair="BTC/USDT")
    path = "/v1/context_bundle?pair=BTC/USDT&tf=15m"
    headers = _sign("GET", path, "")
    r = await v1_client.get(path, headers=headers)
    assert r.status_code == 200
    pending_ids = {p["id"] for p in r.json()["dynamic"]["pending_signals"]}
    assert sid in pending_ids


@pytest.mark.asyncio
async def test_context_bundle_includes_recent_journal(
    v1_client: AsyncClient, clean_db: asyncpg.Pool
) -> None:
    # First create a signal + journal row (use the /v1/decide path so the trigger fires).
    sid = await _insert_pending_signal(clean_db, pair="BTC/USDT")
    body = {
        "signal_id": sid,
        "regime": "trending_up",
        "decision": "approve",
        "reasoning": "context_bundle should surface this entry in recent_journal.",
        "confidence": 7,
    }
    body_str = json.dumps(body)
    headers = _sign("POST", "/v1/decide", body_str)
    headers["content-type"] = "application/json"
    r1 = await v1_client.post("/v1/decide", content=body_str, headers=headers)
    assert r1.status_code == 200, r1.text

    path = "/v1/context_bundle?pair=BTC/USDT&tf=15m"
    headers = _sign("GET", path, "")
    r = await v1_client.get(path, headers=headers)
    assert r.status_code == 200
    recent = r.json()["dynamic"]["recent_journal"]
    assert len(recent) >= 1
    assert any(e["decision"] == "approve" for e in recent)
