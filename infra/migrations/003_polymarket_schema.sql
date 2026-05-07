-- 003_polymarket_schema.sql — Phase E of multi-bot restructure plan.
--
-- Mirrors the brain.* schema (per ADR-001) into a polymarket.* schema for the
-- second bot. Adds one Polymarket-specific table (polymarket.markets) for
-- market metadata + resolution outcome that has no equivalent on the crypto
-- side.
--
-- Per ADR-001:
--   - Crypto bot keeps brain.* (legacy name preserved for stability).
--   - Polymarket bot uses polymarket.* (canonical bot-named forward).
--   - Future bots use their own bot-named schema (e.g. <bot>.*).
--
-- Per ADR-002 + Iron Law 5:
--   - polymarket.brain_journal MUST be append-only. Trigger function references
--     polymarket.brain_journal explicitly — NOT a copy-paste of
--     brain.reject_journal_mutation() that would silently allow mutation on the
--     polymarket side.
--
-- Rollback (emergency only — destructive):
--   DROP SCHEMA polymarket CASCADE;
--   That's it. No cross-schema FKs to worry about.

BEGIN;

-- ---------------------------------------------------------------------------
-- 0. Schema + grants (idempotent for existing deployments).
-- ---------------------------------------------------------------------------
CREATE SCHEMA IF NOT EXISTS polymarket;
GRANT ALL ON SCHEMA polymarket TO trader;

ALTER DEFAULT PRIVILEGES IN SCHEMA polymarket
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO trader;
ALTER DEFAULT PRIVILEGES IN SCHEMA polymarket
    GRANT USAGE, SELECT ON SEQUENCES TO trader;

COMMENT ON SCHEMA polymarket IS 'AI Trading 24/7 polymarket-bot tables (Claude oversight + py-clob-client body). Created by 003_polymarket_schema.sql (Phase E of multi-bot restructure plan, 2026-05-07). Mirrors brain.* schema; adds polymarket.markets unique to this bot.';

-- ---------------------------------------------------------------------------
-- 1. polymarket.markets — market metadata + resolution outcome
--    (unique to this bot — no brain.* equivalent)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS polymarket.markets (
    market_id           TEXT        PRIMARY KEY,                    -- Polymarket condition ID or slug
    question            TEXT        NOT NULL,
    outcomes            JSONB       NOT NULL,                        -- [{"name": "YES", "token_id": "..."}, ...]
    resolution_source   TEXT        NOT NULL,                        -- e.g. 'UMA optimistic oracle'
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    resolves_at         TIMESTAMPTZ,                                 -- expected resolution time (NULL if unknown)
    resolved_at         TIMESTAMPTZ,                                 -- actual resolution time (NULL until resolved)
    resolution_outcome  TEXT,                                        -- winning outcome name (NULL until resolved)
    metadata            JSONB       NOT NULL DEFAULT '{}'::jsonb     -- category, tags, liquidity_usd, dispute_history, etc.
);

CREATE INDEX IF NOT EXISTS idx_markets_resolves_at ON polymarket.markets (resolves_at) WHERE resolved_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_markets_resolved_at ON polymarket.markets (resolved_at DESC) WHERE resolved_at IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_markets_resolution_source ON polymarket.markets (resolution_source);

-- ---------------------------------------------------------------------------
-- 2. polymarket.signals — strategy signals + Claude oversight decision
--    (mirrors brain.signals shape, with binary-outcome price columns instead
--    of OHLC indicators)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS polymarket.signals (
    id                  BIGSERIAL PRIMARY KEY,
    ts                  TIMESTAMPTZ NOT NULL DEFAULT now(),
    market_id           TEXT        NOT NULL REFERENCES polymarket.markets(market_id),
    signal_type         TEXT        NOT NULL CHECK (signal_type IN (
                            'enter_yes', 'enter_no', 'exit_yes', 'exit_no'
                        )),
    outcome_yes_price   NUMERIC     NOT NULL CHECK (outcome_yes_price >= 0 AND outcome_yes_price <= 1),
    outcome_no_price    NUMERIC     NOT NULL CHECK (outcome_no_price >= 0 AND outcome_no_price <= 1),
    edge_bps            NUMERIC,                                     -- estimated edge in basis points (signal generator's prior)
    indicators          JSONB       NOT NULL DEFAULT '{}'::jsonb,    -- strategy-specific signal context
    -- Claude oversight overlay (filled by /v1/polymarket/decide endpoint):
    claude_decision     TEXT        CHECK (claude_decision IN ('approve', 'veto', 'resize', NULL)),
    claude_size_mult    NUMERIC     CHECK (claude_size_mult IS NULL OR (claude_size_mult >= 0.5 AND claude_size_mult <= 1.5)),
    claude_decided_at   TIMESTAMPTZ,
    -- Linked outcome (FK to whatever execution-side trade table polymarket-bot creates in Phase 3):
    trade_id            BIGINT,                                      -- no FK constraint until execution side exists
    UNIQUE (market_id, ts, signal_type)
);

CREATE INDEX IF NOT EXISTS idx_signals_ts ON polymarket.signals (ts DESC);
CREATE INDEX IF NOT EXISTS idx_signals_market_decision ON polymarket.signals (market_id, claude_decision);
CREATE INDEX IF NOT EXISTS idx_signals_pending ON polymarket.signals (ts) WHERE claude_decision IS NULL;

-- ---------------------------------------------------------------------------
-- 3. polymarket.brain_journal — Claude reasoning audit log (append-only,
--    Iron Law 5)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS polymarket.brain_journal (
    id                      BIGSERIAL PRIMARY KEY,
    ts                      TIMESTAMPTZ NOT NULL DEFAULT now(),
    signal_id               BIGINT      REFERENCES polymarket.signals(id) ON DELETE SET NULL,
    regime                  TEXT        NOT NULL,                    -- e.g. 'pre-resolution-stable', 'news-shock', 'oracle-dispute-active'
    decision                TEXT        NOT NULL CHECK (decision IN ('approve', 'veto', 'resize', 'halt', 'no_action')),
    reasoning               TEXT        NOT NULL,
    confidence              SMALLINT    CHECK (confidence BETWEEN 1 AND 10),
    expected_outcome        TEXT,
    actual_outcome          TEXT,
    actual_pnl_pct          NUMERIC,
    outcome_recorded_at     TIMESTAMPTZ,
    -- Full-text search on reasoning (mirrors brain.brain_journal pattern):
    reasoning_tsv           TSVECTOR    GENERATED ALWAYS AS (to_tsvector('english', reasoning)) STORED
);

CREATE INDEX IF NOT EXISTS idx_pm_journal_ts ON polymarket.brain_journal (ts DESC);
CREATE INDEX IF NOT EXISTS idx_pm_journal_regime ON polymarket.brain_journal (regime);
CREATE INDEX IF NOT EXISTS idx_pm_journal_decision ON polymarket.brain_journal (decision);
CREATE INDEX IF NOT EXISTS idx_pm_journal_signal ON polymarket.brain_journal (signal_id);
CREATE INDEX IF NOT EXISTS idx_pm_journal_reasoning_fts ON polymarket.brain_journal USING GIN (reasoning_tsv);

-- ---------------------------------------------------------------------------
-- 3b. Iron Law 5 enforcement on polymarket.brain_journal.
--
-- Trigger function lives IN polymarket schema and references
-- polymarket.brain_journal explicitly — NOT a copy of brain.reject_journal_mutation()
-- that would silently allow mutation on the polymarket side.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION polymarket.reject_journal_mutation()
    RETURNS TRIGGER
    LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION 'polymarket.brain_journal is append-only (Iron Law 5). % rejected.',
        TG_OP
    USING ERRCODE = '42501';
END;
$$;

DROP TRIGGER IF EXISTS tg_pm_journal_no_update ON polymarket.brain_journal;
CREATE TRIGGER tg_pm_journal_no_update
    BEFORE UPDATE ON polymarket.brain_journal
    FOR EACH ROW EXECUTE FUNCTION polymarket.reject_journal_mutation();

DROP TRIGGER IF EXISTS tg_pm_journal_no_delete ON polymarket.brain_journal;
CREATE TRIGGER tg_pm_journal_no_delete
    BEFORE DELETE ON polymarket.brain_journal
    FOR EACH ROW EXECUTE FUNCTION polymarket.reject_journal_mutation();

-- ---------------------------------------------------------------------------
-- 4. polymarket.equity_curve — equity snapshots
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS polymarket.equity_curve (
    ts                  TIMESTAMPTZ NOT NULL,
    equity_usd          NUMERIC     NOT NULL,
    realized_pnl        NUMERIC     NOT NULL DEFAULT 0,
    unrealized_pnl      NUMERIC     NOT NULL DEFAULT 0,
    open_positions      INT         NOT NULL DEFAULT 0,              -- count of unresolved markets with active positions
    drawdown_pct        NUMERIC     NOT NULL DEFAULT 0,
    PRIMARY KEY (ts)
);

CREATE INDEX IF NOT EXISTS idx_pm_equity_ts ON polymarket.equity_curve (ts DESC);

-- ---------------------------------------------------------------------------
-- 5. polymarket.backtest_runs — walk-forward results, Polymarket-specific gates
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS polymarket.backtest_runs (
    id                  BIGSERIAL PRIMARY KEY,
    started_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at        TIMESTAMPTZ,
    strategy_version    TEXT        NOT NULL,
    fold_index          INT         NOT NULL,
    train_start         TIMESTAMPTZ NOT NULL,
    train_end           TIMESTAMPTZ NOT NULL,
    test_start          TIMESTAMPTZ NOT NULL,
    test_end            TIMESTAMPTZ NOT NULL,
    parameters          JSONB       NOT NULL,
    -- metrics shape for polymarket (NOT brain.*) — Brier score, calibration ECE,
    -- sample size per market type, oracle-dispute loss count.
    -- Example: {"brier_score": 0.18, "calibration_ece": 0.04,
    --           "sample_size_per_market_type": {"sports": 142, "election": 88, ...},
    --           "oracle_dispute_loss_count": 0,
    --           "total_resolved_markets": 312, "win_rate": 0.61, "pnl_pct": 14.3}
    metrics             JSONB       NOT NULL,
    equity_curve        JSONB,
    trades              JSONB,
    gate_passed         BOOLEAN     NOT NULL DEFAULT FALSE,
    notes               TEXT
);

CREATE INDEX IF NOT EXISTS idx_pm_backtest_strategy ON polymarket.backtest_runs (strategy_version, fold_index);
CREATE INDEX IF NOT EXISTS idx_pm_backtest_started ON polymarket.backtest_runs (started_at DESC);

-- ---------------------------------------------------------------------------
-- 6. polymarket.iteration_runs — Phase 9.5 iteration loop tracking
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS polymarket.iteration_runs (
    id              BIGSERIAL PRIMARY KEY,
    started_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at    TIMESTAMPTZ,
    run_type        TEXT        NOT NULL CHECK (run_type IN ('iteration', 'post_mortem', 'health_check')),
    cycle_n         INT         CHECK (cycle_n BETWEEN 1 AND 3),
    failure_mode    TEXT,
    hypothesis      TEXT,
    adr_ref         TEXT,
    metrics_before  JSONB,
    metrics_after   JSONB,
    outcome         TEXT        CHECK (outcome IN ('PASS', 'FAIL_RETRY', 'FAIL_ESCALATE', 'IN_PROGRESS')),
    summary         TEXT
);

CREATE INDEX IF NOT EXISTS idx_pm_iteration_started ON polymarket.iteration_runs (started_at DESC);
CREATE INDEX IF NOT EXISTS idx_pm_iteration_type ON polymarket.iteration_runs (run_type);

COMMIT;
