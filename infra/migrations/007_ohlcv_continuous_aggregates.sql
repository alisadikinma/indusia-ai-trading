-- 007_ohlcv_continuous_aggregates.sql — TimescaleDB continuous aggregates for OHLCV.
--
-- brain.ohlcv stores raw 1m bars. The cockpit Live Chart picker offers
-- 1m/5m/15m/1h/4h/1d. Building one materialized aggregate per timeframe
-- keeps each chart query small and lets the operator scrub years of history
-- without scanning the full 1m hypertable.
--
-- Each view aggregates the SAME columns the API returns (ts, open, high,
-- low, close, volume) using TimescaleDB's first()/last() over time, plus
-- pair (carried) and source (carried). The pair/source pair acts as the
-- segment-by key matching the source hypertable's compression layout.
--
-- Refresh policies use TimescaleDB defaults that are safe for 1m source
-- bars: window = 7 days back to 2x bucket forward; schedule = bucket size.
-- Backfill happens by an explicit CALL refresh_continuous_aggregate(...) at
-- the bottom (one-shot — re-running the migration is harmless: refresh
-- function is idempotent over already-materialized buckets).
--
-- Idempotency notes:
--   - CREATE MATERIALIZED VIEW IF NOT EXISTS — re-runs no-op.
--   - add_continuous_aggregate_policy may raise duplicate-object if a
--     policy already exists. We wrap each in a DO block to swallow that.
--   - refresh_continuous_aggregate(NULL, NULL) re-materializes all buckets
--     using only un-materialized data; cheap on second run.

BEGIN;

-- ---------------------------------------------------------------------------
-- 5m
-- ---------------------------------------------------------------------------
CREATE MATERIALIZED VIEW IF NOT EXISTS brain.ohlcv_5m
WITH (timescaledb.continuous) AS
SELECT
    time_bucket(INTERVAL '5 minutes', ts)            AS ts,
    pair,
    source,
    first(open, ts)                                  AS open,
    max(high)                                        AS high,
    min(low)                                         AS low,
    last(close, ts)                                  AS close,
    sum(volume)                                      AS volume
FROM brain.ohlcv
WHERE tf = '1m'
GROUP BY 1, pair, source
WITH NO DATA;

SELECT add_continuous_aggregate_policy(
    'brain.ohlcv_5m',
    start_offset      => INTERVAL '7 days',
    end_offset        => INTERVAL '10 minutes',
    schedule_interval => INTERVAL '5 minutes',
    if_not_exists     => TRUE
);

-- ---------------------------------------------------------------------------
-- 15m
-- ---------------------------------------------------------------------------
CREATE MATERIALIZED VIEW IF NOT EXISTS brain.ohlcv_15m
WITH (timescaledb.continuous) AS
SELECT
    time_bucket(INTERVAL '15 minutes', ts)           AS ts,
    pair,
    source,
    first(open, ts)                                  AS open,
    max(high)                                        AS high,
    min(low)                                         AS low,
    last(close, ts)                                  AS close,
    sum(volume)                                      AS volume
FROM brain.ohlcv
WHERE tf = '1m'
GROUP BY 1, pair, source
WITH NO DATA;

SELECT add_continuous_aggregate_policy(
    'brain.ohlcv_15m',
    start_offset      => INTERVAL '14 days',
    end_offset        => INTERVAL '30 minutes',
    schedule_interval => INTERVAL '15 minutes',
    if_not_exists     => TRUE
);

-- ---------------------------------------------------------------------------
-- 1h
-- ---------------------------------------------------------------------------
CREATE MATERIALIZED VIEW IF NOT EXISTS brain.ohlcv_1h
WITH (timescaledb.continuous) AS
SELECT
    time_bucket(INTERVAL '1 hour', ts)               AS ts,
    pair,
    source,
    first(open, ts)                                  AS open,
    max(high)                                        AS high,
    min(low)                                         AS low,
    last(close, ts)                                  AS close,
    sum(volume)                                      AS volume
FROM brain.ohlcv
WHERE tf = '1m'
GROUP BY 1, pair, source
WITH NO DATA;

SELECT add_continuous_aggregate_policy(
    'brain.ohlcv_1h',
    start_offset      => INTERVAL '30 days',
    end_offset        => INTERVAL '2 hours',
    schedule_interval => INTERVAL '1 hour',
    if_not_exists     => TRUE
);

-- ---------------------------------------------------------------------------
-- 4h
-- ---------------------------------------------------------------------------
CREATE MATERIALIZED VIEW IF NOT EXISTS brain.ohlcv_4h
WITH (timescaledb.continuous) AS
SELECT
    time_bucket(INTERVAL '4 hours', ts)              AS ts,
    pair,
    source,
    first(open, ts)                                  AS open,
    max(high)                                        AS high,
    min(low)                                         AS low,
    last(close, ts)                                  AS close,
    sum(volume)                                      AS volume
FROM brain.ohlcv
WHERE tf = '1m'
GROUP BY 1, pair, source
WITH NO DATA;

SELECT add_continuous_aggregate_policy(
    'brain.ohlcv_4h',
    start_offset      => INTERVAL '90 days',
    end_offset        => INTERVAL '8 hours',
    schedule_interval => INTERVAL '4 hours',
    if_not_exists     => TRUE
);

-- ---------------------------------------------------------------------------
-- 1d
-- ---------------------------------------------------------------------------
CREATE MATERIALIZED VIEW IF NOT EXISTS brain.ohlcv_1d
WITH (timescaledb.continuous) AS
SELECT
    time_bucket(INTERVAL '1 day', ts)                AS ts,
    pair,
    source,
    first(open, ts)                                  AS open,
    max(high)                                        AS high,
    min(low)                                         AS low,
    last(close, ts)                                  AS close,
    sum(volume)                                      AS volume
FROM brain.ohlcv
WHERE tf = '1m'
GROUP BY 1, pair, source
WITH NO DATA;

SELECT add_continuous_aggregate_policy(
    'brain.ohlcv_1d',
    start_offset      => INTERVAL '365 days',
    end_offset        => INTERVAL '2 days',
    schedule_interval => INTERVAL '1 day',
    if_not_exists     => TRUE
);

COMMIT;

-- ---------------------------------------------------------------------------
-- Backfill (outside transaction — refresh_continuous_aggregate cannot run
-- inside a tx block). Idempotent: re-running only materializes new buckets.
-- ---------------------------------------------------------------------------
CALL refresh_continuous_aggregate('brain.ohlcv_5m',  NULL, NULL);
CALL refresh_continuous_aggregate('brain.ohlcv_15m', NULL, NULL);
CALL refresh_continuous_aggregate('brain.ohlcv_1h',  NULL, NULL);
CALL refresh_continuous_aggregate('brain.ohlcv_4h',  NULL, NULL);
CALL refresh_continuous_aggregate('brain.ohlcv_1d',  NULL, NULL);
