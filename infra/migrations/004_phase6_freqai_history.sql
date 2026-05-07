-- 004_phase6_freqai_history.sql — Phase 6 schema for FreqAI retrain history.
--
-- Phase 7 will populate this table from the FreqAI retrain hook; Phase 6
-- needs the table to exist so `infra/scripts/retrain_health_check.py` (the
-- daily 06:00 UTC health-check cron) can query it without erroring on a
-- missing relation.
--
-- The empty-state path in retrain_health_check.py is handled by the script
-- itself (returns status='no_data', exit 0, no Telegram alert), so this
-- migration is safe to apply now even though no rows will land until
-- Phase 7.
--
-- Per Iron Law 4: this migration is operator-curated. Once applied, do NOT
-- auto-edit the constraints below.

BEGIN;

CREATE TABLE IF NOT EXISTS brain.freqai_history (
    id                 BIGSERIAL PRIMARY KEY,
    retrained_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    pair               TEXT        NOT NULL,
    tf                 TEXT        NOT NULL,
    train_window_days  INT         NOT NULL,
    train_rows         BIGINT      NOT NULL,
    auc                NUMERIC     NOT NULL CHECK (auc >= 0 AND auc <= 1),
    feature_importance JSONB       NOT NULL DEFAULT '{}'::jsonb,
    model_path         TEXT        NOT NULL,
    notes              TEXT
);

CREATE INDEX IF NOT EXISTS idx_freqai_history_retrained
    ON brain.freqai_history (retrained_at DESC);
CREATE INDEX IF NOT EXISTS idx_freqai_history_pair_tf
    ON brain.freqai_history (pair, tf, retrained_at DESC);

COMMIT;
