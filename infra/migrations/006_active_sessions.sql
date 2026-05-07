-- Phase 1.5.I: Session revocation via JTI (JWT ID) claim + active_sessions table.
-- This enables per-device logout without key rotation and defense-in-depth session
-- verification at page load time.

CREATE TABLE brain.active_sessions (
  jti UUID PRIMARY KEY,
  sub TEXT NOT NULL,
  issued_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  expires_at TIMESTAMPTZ NOT NULL,
  revoked_at TIMESTAMPTZ NULL
);

-- Index for efficient lookup during token verification.
CREATE INDEX idx_active_sessions_revoked_expires ON brain.active_sessions (revoked_at, expires_at);

-- Cleanup: remove expired + revoked sessions periodically (operator cron).
-- Use a CTE so DELETE...RETURNING is composable with the row-count probe.
--
-- WITH deleted AS (
--   DELETE FROM brain.active_sessions
--   WHERE expires_at < now() - interval '24 hours'
--      OR (revoked_at IS NOT NULL AND revoked_at < now() - interval '7 days')
--   RETURNING jti
-- )
-- SELECT count(*) AS deleted FROM deleted;
