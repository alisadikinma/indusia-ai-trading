-- 005_hyperopt_results.sql — Phase 8 hyperopt result persistence.
--
-- Creates brain.hyperopt_results: append-only-style record of every parameter
-- combination evaluated during a hyperopt sweep. Each row corresponds to one
-- (run_id, epoch) pair and stores the chosen parameters, the loss-function
-- value (lower is better, per IHyperOptLoss convention — Sharpe loss returns
-- -sharpe), and the standard backtest metrics for cross-checking.
--
-- Track A (Strategy Lab UI) reads this table to render the top-3 selector +
-- equity-curve overlay. The (run_id, loss) index supports
--     SELECT ... ORDER BY loss ASC LIMIT 3
-- per run cheaply.

BEGIN;

CREATE TABLE IF NOT EXISTS brain.hyperopt_results (
    id                 BIGSERIAL PRIMARY KEY,
    run_id             TEXT             NOT NULL,
    epoch              INT              NOT NULL,
    strategy_version   TEXT             NOT NULL,
    parameters         JSONB            NOT NULL,
    loss               DOUBLE PRECISION NOT NULL,
    sharpe             DOUBLE PRECISION,
    max_dd             DOUBLE PRECISION,
    profit_factor      DOUBLE PRECISION,
    total_trades       INT,
    win_rate           DOUBLE PRECISION,
    timerange_start    TIMESTAMPTZ      NOT NULL,
    timerange_end      TIMESTAMPTZ      NOT NULL,
    created_at         TIMESTAMPTZ      NOT NULL DEFAULT now(),
    UNIQUE (run_id, epoch)
);

CREATE INDEX IF NOT EXISTS idx_hyperopt_run ON brain.hyperopt_results (run_id, loss);
CREATE INDEX IF NOT EXISTS idx_hyperopt_created ON brain.hyperopt_results (created_at DESC);

COMMENT ON TABLE brain.hyperopt_results IS
    'Phase 8 — top-N parameter sets per hyperopt run. Track A (Strategy Lab UI) reads this for the top-3 selector. Loss column follows IHyperOptLoss convention (lower=better; SharpeHyperOptLoss stores -sharpe).';

COMMIT;
