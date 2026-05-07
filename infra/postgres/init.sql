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

-- 3. Schema separation (Iron Law: clean ownership boundary, plus per-bot
--    isolation per ADR-001 mono-repo multi-bot architecture)
--    brain.*       -> crypto-bot tables (legacy name kept for stability per ADR-001)
--    polymarket.*  -> polymarket-bot tables
--    public.*      -> Freqtrade ORM creates its own tables here at first run
CREATE SCHEMA IF NOT EXISTS brain;
CREATE SCHEMA IF NOT EXISTS polymarket;

-- 4. Grant the trader role what it needs.
--    docker-entrypoint already created 'trader' as the POSTGRES_USER.
--    We make sure 'trader' owns the per-bot schemas and can also CREATE in public.
GRANT ALL ON SCHEMA brain TO trader;
GRANT ALL ON SCHEMA polymarket TO trader;
GRANT CREATE ON SCHEMA public TO trader;
GRANT USAGE ON SCHEMA public TO trader;

-- 5. Default privileges so future tables in per-bot schemas are accessible to trader.
ALTER DEFAULT PRIVILEGES IN SCHEMA brain
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO trader;
ALTER DEFAULT PRIVILEGES IN SCHEMA brain
    GRANT USAGE, SELECT ON SEQUENCES TO trader;
ALTER DEFAULT PRIVILEGES IN SCHEMA polymarket
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO trader;
ALTER DEFAULT PRIVILEGES IN SCHEMA polymarket
    GRANT USAGE, SELECT ON SEQUENCES TO trader;

-- 6. Comment / version stamp for ops.
COMMENT ON SCHEMA brain IS 'AI Trading 24/7 crypto-bot tables (Claude oversight + Freqtrade body). Created by init.sql at container first-start. Legacy schema name kept per ADR-001.';
COMMENT ON SCHEMA polymarket IS 'AI Trading 24/7 polymarket-bot tables (Claude oversight + py-clob-client body). Created by init.sql; tables added by 003_polymarket_schema.sql migration.';
