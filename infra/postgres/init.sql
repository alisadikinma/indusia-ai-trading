-- AI Trading 24/7 — Postgres bootstrap (runs once on container first start)
--
-- Order:
--   1. Enable timescaledb extension
--   2. Ensure 'trader' role (created by docker-entrypoint) has needed grants
--   3. Create separate schemas for clean ownership boundary
--   4. The actual table CREATE statements live in migrations/000_bootstrap_schemas.sql
--      which must be applied AFTER this init runs (run via psql, not docker entrypoint)

-- 1. TimescaleDB extension
CREATE EXTENSION IF NOT EXISTS timescaledb;

-- 2. Ensure timescaledb_toolkit (optional but useful for time-series ops)
CREATE EXTENSION IF NOT EXISTS pg_stat_statements;

-- 3. Schema separation (Iron Law: clean ownership boundary)
--    brain.*  -> tables owned by Claude oversight + our app code
--    public.* -> Freqtrade ORM creates its own tables here at first run
CREATE SCHEMA IF NOT EXISTS brain;

-- 4. Grant the trader role what it needs.
--    docker-entrypoint already created 'trader' as the POSTGRES_USER.
--    We make sure 'trader' owns the brain schema and can also CREATE in public.
GRANT ALL ON SCHEMA brain TO trader;
GRANT CREATE ON SCHEMA public TO trader;
GRANT USAGE ON SCHEMA public TO trader;

-- 5. Default privileges so future tables in brain.* are accessible to trader.
ALTER DEFAULT PRIVILEGES IN SCHEMA brain
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO trader;
ALTER DEFAULT PRIVILEGES IN SCHEMA brain
    GRANT USAGE, SELECT ON SEQUENCES TO trader;

-- 6. Comment / version stamp for ops.
COMMENT ON SCHEMA brain IS 'AI Trading 24/7 brain-owned tables (claude oversight). Created by init.sql at container first-start.';
