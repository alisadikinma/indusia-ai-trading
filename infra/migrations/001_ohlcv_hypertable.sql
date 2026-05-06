-- 001_ohlcv_hypertable.sql — Phase 2 hypertable conversion + compression policy.
--
-- Converts brain.ohlcv (created in 000_bootstrap_schemas.sql) into a TimescaleDB
-- hypertable partitioned monthly, enables segmented compression on chunks
-- older than 90 days, and leaves an explicit retention policy commented out
-- (operator-enables once we are confident in the historical depth — plan §11
-- targets 11 years).
--
-- Apply via:
--   docker exec -i ai-trading-postgres psql -U trader -d trading \
--       -v ON_ERROR_STOP=1 < infra/migrations/001_ohlcv_hypertable.sql
-- Verify via:
--   SELECT * FROM timescaledb_information.hypertables
--    WHERE hypertable_name = 'ohlcv';

BEGIN;

-- 1. Convert to a hypertable. Idempotent via if_not_exists; the migrate_data
--    flag is unnecessary here because Phase 1 leaves the table empty.
SELECT create_hypertable(
    'brain.ohlcv',
    'ts',
    chunk_time_interval => INTERVAL '1 month',
    if_not_exists       => TRUE
);

-- 2. Enable compression. Group by (pair, tf) so a chunk's segments compress
--    well — same pair/tf rows live contiguously inside each segment.
ALTER TABLE brain.ohlcv SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'pair, tf'
);

-- 3. Compress chunks older than 90 days automatically.
SELECT add_compression_policy('brain.ohlcv', INTERVAL '90 days', if_not_exists => TRUE);

-- 4. Retention policy: 11 years (plan §11). Comment-only — operator enables
--    explicitly once historical depth is locked in.
-- SELECT add_retention_policy('brain.ohlcv', INTERVAL '11 years');

COMMIT;
