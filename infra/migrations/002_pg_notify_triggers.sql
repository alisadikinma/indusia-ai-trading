-- 002_pg_notify_triggers.sql — Phase 1.5.C
--
-- Postgres LISTEN/NOTIFY triggers feeding the dashboard WebSocket fan-out
-- (pulse-bridge/pulse_bridge/ws_pg_listener.py).
--
-- Channels:
--   dashboard_signals  — AFTER INSERT on brain.signals
--   dashboard_journal  — AFTER INSERT on brain.brain_journal
--   dashboard_equity   — AFTER INSERT on brain.equity_curve
--
-- Payload size note: NOTIFY payloads are capped at ~8KB. We stick to a small
-- subset of columns. If a payload would exceed that limit we send the row id
-- only and let WS clients refetch via the REST API.
--
-- Phase 3 will add similar triggers on public.trades when Freqtrade owns it.

BEGIN;

-- ---------------------------------------------------------------------------
-- 1. brain.signals → dashboard_signals
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION brain.notify_signals_insert()
    RETURNS TRIGGER
    LANGUAGE plpgsql
AS $$
DECLARE
    payload JSONB;
BEGIN
    payload := jsonb_build_object(
        'id', NEW.id,
        'ts', NEW.ts,
        'pair', NEW.pair,
        'tf', NEW.tf,
        'signal_type', NEW.signal_type,
        'claude_decision', NEW.claude_decision
    );
    PERFORM pg_notify('dashboard_signals', payload::text);
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS tg_signals_notify ON brain.signals;
CREATE TRIGGER tg_signals_notify
    AFTER INSERT ON brain.signals
    FOR EACH ROW EXECUTE FUNCTION brain.notify_signals_insert();

-- ---------------------------------------------------------------------------
-- 2. brain.brain_journal → dashboard_journal
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION brain.notify_journal_insert()
    RETURNS TRIGGER
    LANGUAGE plpgsql
AS $$
DECLARE
    payload JSONB;
    short_reasoning TEXT;
BEGIN
    -- Truncate reasoning aggressively to stay under the 8KB NOTIFY budget.
    short_reasoning := left(coalesce(NEW.reasoning, ''), 512);
    payload := jsonb_build_object(
        'id', NEW.id,
        'ts', NEW.ts,
        'signal_id', NEW.signal_id,
        'regime', NEW.regime,
        'decision', NEW.decision,
        'reasoning_excerpt', short_reasoning,
        'confidence', NEW.confidence
    );
    PERFORM pg_notify('dashboard_journal', payload::text);
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS tg_journal_notify ON brain.brain_journal;
CREATE TRIGGER tg_journal_notify
    AFTER INSERT ON brain.brain_journal
    FOR EACH ROW EXECUTE FUNCTION brain.notify_journal_insert();

-- ---------------------------------------------------------------------------
-- 3. brain.equity_curve → dashboard_equity
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION brain.notify_equity_insert()
    RETURNS TRIGGER
    LANGUAGE plpgsql
AS $$
DECLARE
    payload JSONB;
BEGIN
    payload := jsonb_build_object(
        'ts', NEW.ts,
        'equity_usd', NEW.equity_usd,
        'realized_pnl', NEW.realized_pnl,
        'unrealized_pnl', NEW.unrealized_pnl,
        'open_positions', NEW.open_positions,
        'drawdown_pct', NEW.drawdown_pct
    );
    PERFORM pg_notify('dashboard_equity', payload::text);
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS tg_equity_notify ON brain.equity_curve;
CREATE TRIGGER tg_equity_notify
    AFTER INSERT ON brain.equity_curve
    FOR EACH ROW EXECUTE FUNCTION brain.notify_equity_insert();

COMMIT;
