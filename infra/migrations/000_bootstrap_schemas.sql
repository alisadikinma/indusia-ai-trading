-- 000_bootstrap_schemas.sql — Phase 1 bootstrap.
--
-- Creates the 6 brain.* tables that the UI in Phase 1.5 will query.
-- Tables are created EMPTY here; later phases populate:
--   * brain.ohlcv          — bulk-loaded in Phase 2 (Binance Vision + CoinDesk)
--   * brain.signals        — populated by strategy in Phase 3
--   * brain.brain_journal  — populated by Claude routine in Phase 5+
--   * brain.equity_curve   — populated by Freqtrade hook in Phase 3+
--   * brain.backtest_runs  — populated by walk-forward orchestrator in Phase 9
--   * brain.iteration_runs — populated by Phase 6 cron + Phase 9.5 iteration loop
--
-- Hypertable conversion for brain.ohlcv happens in Phase 2 migration
-- (001_ohlcv_hypertable.sql) — keeping concerns separated.
--
-- Append-only constraints on brain.brain_journal happen in Phase 6 migration
-- (002_brain_journal_constraints.sql) — Iron Law 5.

BEGIN;

-- ---------------------------------------------------------------------------
-- 1. brain.ohlcv — OHLCV time-series (per pair + timeframe)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS brain.ohlcv (
    pair        TEXT        NOT NULL,
    tf          TEXT        NOT NULL,                  -- e.g. '1m', '15m', '1h'
    ts          TIMESTAMPTZ NOT NULL,
    open        NUMERIC     NOT NULL,
    high        NUMERIC     NOT NULL,
    low         NUMERIC     NOT NULL,
    close       NUMERIC     NOT NULL,
    volume      NUMERIC     NOT NULL,
    source      TEXT        NOT NULL DEFAULT 'binance_vision',
    PRIMARY KEY (pair, tf, ts)
);

-- ---------------------------------------------------------------------------
-- 2. brain.signals — strategy entry/exit signals + Claude's decision
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS brain.signals (
    id              BIGSERIAL PRIMARY KEY,
    ts              TIMESTAMPTZ NOT NULL DEFAULT now(),
    pair            TEXT        NOT NULL,
    tf              TEXT        NOT NULL,
    signal_type     TEXT        NOT NULL CHECK (signal_type IN ('enter_long', 'enter_short', 'exit_long', 'exit_short')),
    price_at_signal NUMERIC     NOT NULL,
    indicators      JSONB       NOT NULL DEFAULT '{}'::jsonb,
    -- Claude oversight overlay (filled by /v1/decide endpoint in Phase 4):
    claude_decision TEXT        CHECK (claude_decision IN ('approve', 'veto', 'resize', NULL)),
    claude_size_mult NUMERIC    CHECK (claude_size_mult IS NULL OR (claude_size_mult >= 0.5 AND claude_size_mult <= 1.5)),
    claude_decided_at TIMESTAMPTZ,
    -- Linked outcome:
    trade_id        BIGINT,                            -- FK to public.trades (Freqtrade-owned), no constraint until Phase 3
    UNIQUE (pair, tf, ts, signal_type)
);

CREATE INDEX IF NOT EXISTS idx_signals_ts ON brain.signals (ts DESC);
CREATE INDEX IF NOT EXISTS idx_signals_pair_decision ON brain.signals (pair, claude_decision);
CREATE INDEX IF NOT EXISTS idx_signals_pending ON brain.signals (ts) WHERE claude_decision IS NULL;

-- ---------------------------------------------------------------------------
-- 3. brain.brain_journal — Claude's reasoning audit log (append-only in Phase 6)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS brain.brain_journal (
    id                      BIGSERIAL PRIMARY KEY,
    ts                      TIMESTAMPTZ NOT NULL DEFAULT now(),
    signal_id               BIGINT      REFERENCES brain.signals(id) ON DELETE SET NULL,
    regime                  TEXT        NOT NULL,     -- 'trending_up', 'trending_down', 'ranging', 'volatile'
    decision                TEXT        NOT NULL CHECK (decision IN ('approve', 'veto', 'resize', 'halt', 'no_action')),
    reasoning               TEXT        NOT NULL,
    confidence              SMALLINT    CHECK (confidence BETWEEN 1 AND 10),
    expected_outcome        TEXT,                      -- free-text qualitative
    actual_outcome          TEXT,
    actual_pnl_pct          NUMERIC,
    outcome_recorded_at     TIMESTAMPTZ,
    -- For full-text search (Phase 1.5 UI Brain Journal view):
    reasoning_tsv           TSVECTOR    GENERATED ALWAYS AS (to_tsvector('english', reasoning)) STORED
);

CREATE INDEX IF NOT EXISTS idx_journal_ts ON brain.brain_journal (ts DESC);
CREATE INDEX IF NOT EXISTS idx_journal_regime ON brain.brain_journal (regime);
CREATE INDEX IF NOT EXISTS idx_journal_decision ON brain.brain_journal (decision);
CREATE INDEX IF NOT EXISTS idx_journal_signal ON brain.brain_journal (signal_id);
CREATE INDEX IF NOT EXISTS idx_journal_reasoning_fts ON brain.brain_journal USING GIN (reasoning_tsv);

-- ---------------------------------------------------------------------------
-- 4. brain.equity_curve — equity snapshots for fast time-series queries
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS brain.equity_curve (
    ts              TIMESTAMPTZ NOT NULL,
    equity_usd      NUMERIC     NOT NULL,
    realized_pnl    NUMERIC     NOT NULL DEFAULT 0,
    unrealized_pnl  NUMERIC     NOT NULL DEFAULT 0,
    open_positions  INT         NOT NULL DEFAULT 0,
    drawdown_pct    NUMERIC     NOT NULL DEFAULT 0,
    PRIMARY KEY (ts)
);

CREATE INDEX IF NOT EXISTS idx_equity_ts ON brain.equity_curve (ts DESC);

-- ---------------------------------------------------------------------------
-- 5. brain.backtest_runs — walk-forward results + hyperopt sweeps
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS brain.backtest_runs (
    id                  BIGSERIAL PRIMARY KEY,
    started_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at        TIMESTAMPTZ,
    strategy_version    TEXT        NOT NULL,        -- e.g. 'v1.0', 'v1.2-iter-1'
    fold_index          INT         NOT NULL,        -- 1..5 for walk-forward
    train_start         TIMESTAMPTZ NOT NULL,
    train_end           TIMESTAMPTZ NOT NULL,
    test_start          TIMESTAMPTZ NOT NULL,
    test_end            TIMESTAMPTZ NOT NULL,
    parameters          JSONB       NOT NULL,
    metrics             JSONB       NOT NULL,        -- {sharpe, sortino, max_dd, profit_factor, total_trades, win_rate, expectancy}
    equity_curve        JSONB,                        -- compact time-series for UI plot
    trades              JSONB,                        -- per-trade list for UI overlay
    gate_passed         BOOLEAN     NOT NULL DEFAULT FALSE,
    notes               TEXT
);

CREATE INDEX IF NOT EXISTS idx_backtest_strategy ON brain.backtest_runs (strategy_version, fold_index);
CREATE INDEX IF NOT EXISTS idx_backtest_started ON brain.backtest_runs (started_at DESC);

-- ---------------------------------------------------------------------------
-- 5b. Iron Law 5: brain.brain_journal is append-only.
--
-- Plan originally placed this in 002_brain_journal_constraints.sql (Phase 6),
-- but append-only-ness is fundamental (Iron Law 5) so it ships with the table
-- definition itself. UI in Phase 1.5 must be tested against this constraint.
--
-- Strategy: trigger-based enforcement. REVOKE doesn't work against the table
-- owner (trader, since trader created the table via this migration). Triggers
-- fire regardless of who issues the UPDATE/DELETE, including the owner.
-- We raise SQLSTATE 42501 (insufficient_privilege) so application code sees
-- the same error class as a permission denial.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION brain.reject_journal_mutation()
    RETURNS TRIGGER
    LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION 'brain.brain_journal is append-only (Iron Law 5). % rejected.',
        TG_OP
    USING ERRCODE = '42501';  -- insufficient_privilege
END;
$$;

DROP TRIGGER IF EXISTS tg_journal_no_update ON brain.brain_journal;
CREATE TRIGGER tg_journal_no_update
    BEFORE UPDATE ON brain.brain_journal
    FOR EACH ROW EXECUTE FUNCTION brain.reject_journal_mutation();

DROP TRIGGER IF EXISTS tg_journal_no_delete ON brain.brain_journal;
CREATE TRIGGER tg_journal_no_delete
    BEFORE DELETE ON brain.brain_journal
    FOR EACH ROW EXECUTE FUNCTION brain.reject_journal_mutation();

-- ---------------------------------------------------------------------------
-- 6. brain.iteration_runs — Phase 9.5 iteration loop tracking + continuous learning
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS brain.iteration_runs (
    id              BIGSERIAL PRIMARY KEY,
    started_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at    TIMESTAMPTZ,
    run_type        TEXT        NOT NULL CHECK (run_type IN ('iteration', 'post_mortem', 'health_check')),
    cycle_n         INT         CHECK (cycle_n BETWEEN 1 AND 3),  -- only for run_type='iteration'
    failure_mode    TEXT,                                          -- 'overfit', 'underfit', 'strategy_logic', 'regime_specific', 'hyperopt_unstable'
    hypothesis      TEXT,
    adr_ref         TEXT,                                          -- path to docs/decisions/...
    metrics_before  JSONB,
    metrics_after   JSONB,
    outcome         TEXT        CHECK (outcome IN ('PASS', 'FAIL_RETRY', 'FAIL_ESCALATE', 'IN_PROGRESS')),
    summary         TEXT
);

CREATE INDEX IF NOT EXISTS idx_iteration_started ON brain.iteration_runs (started_at DESC);
CREATE INDEX IF NOT EXISTS idx_iteration_type ON brain.iteration_runs (run_type);

COMMIT;
