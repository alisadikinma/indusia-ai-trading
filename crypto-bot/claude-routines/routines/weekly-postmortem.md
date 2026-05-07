# Weekly Post-Mortem Routine

The Phase 6 cron that runs every Sunday at 00:00 UTC. Reads recent losing
trades from `brain.brain_journal`, groups by failure signature, invokes
Claude with the `pattern-detector.md` + `post-mortem-protocol.md` skills
appended to its system prompt, and writes structured lessons to the
crypto bot's memory layer + (when patterns are structural)
`known-traps.md`. Operationally implemented as
`infra/scripts/post_mortem_cron.py`; this file is the routine spec the
cron incarnates.

This routine is **NOT** the runtime oversight loop. It does NOT POST to
`/v1/decide`. It writes only to local files (memory + skills) and one
SQL row in `brain.iteration_runs`. Per Iron Law 4, this cron is the ONE
automation layer permitted to write to `crypto-bot/claude-routines/skills/known-traps.md`.

## Cadence

```cron
0 0 * * 0   /opt/ai-trading/.venv/bin/python -m infra.scripts.post_mortem_cron
```

Every Sunday 00:00 UTC. Cycle budget target: ≤ 5 minutes (one Claude CLI
invocation per detected failure group; typical week 0-3 groups). Hard
timeout: 30 minutes (handled by the systemd timer's `OnUnitActiveSec=` /
service `TimeoutStartSec=`). Persistent=true on the timer so missed runs
after a VPS reboot catch up at next boot.

## Procedure

1. **Load env + connect**. The cron asserts `POSTGRES_*` and
   `ANTHROPIC_API_KEY` are present (hard-fail on missing — Iron Law 1
   anti-placeholder). Opens one psycopg connection.
2. **Group recent losses**. Calls
   `detect_recurring_losses(conn, since_days=7)`: SQL groups
   `brain.brain_journal` JOIN `brain.signals` rows where
   `actual_pnl_pct < -1.0` and `ts >= now() - 7 days`, bucketed by
   `(regime, funding_bucket, vol_bucket, signal_type)`. Funding buckets:
   <-0.05% / [-0.05%, 0.05%] / >0.05%. Vol buckets driven by `atr_pct`
   carried in `signals.indicators`: <2% low / [2%,5%] mid / >5% high.
   `HAVING count(*) >= 3` filters singletons.
3. **Per group, invoke Claude**. The cron shells out:
   ```
   claude -p \
     --append-system-prompt-file crypto-bot/claude-routines/skills/pattern-detector.md \
     --append-system-prompt-file crypto-bot/claude-routines/skills/post-mortem-protocol.md \
     "<FailureGroup as JSON>"
   ```
   Claude returns the JSON shape documented in `pattern-detector.md`
   §Output format.
4. **Append lesson (always)**. The cron appends one entry to
   `crypto-bot/claude-routines/memory/lessons-learned.md` regardless of
   whether the group was structural.
5. **Append known-traps (conditional)**. IFF
   `claude_response.is_structural == true`, the cron appends a TRAP-NNN
   entry to `crypto-bot/claude-routines/skills/known-traps.md`. NNN is
   auto-incremented from the highest existing TRAP id in the file.
6. **Refresh strategy stats**. The cron runs
   `refresh_strategy_performance(conn)` — a 90-day per-regime aggregate
   that REPLACES the `<!-- BEGIN perf-table --> ... <!-- END perf-table -->`
   block in `memory/strategy-performance.md` and updates the
   `## Last refresh` ISO timestamp. Idempotent.
7. **Compact regime history**. The cron runs `compact_regime_history()`
   to drop entries dated > 30 days from
   `memory/recent-regime-history.md`. Lines that don't match the
   `- YYYY-MM-DD` prefix are preserved.
8. **Log the run**. INSERT one row into `brain.iteration_runs` with
   `run_type='post_mortem'`, `outcome='PASS'`, `summary` JSON capturing
   counts (groups detected, lessons appended, traps appended, regime
   rows dropped, perf rows).

## Failure handling

- **Postgres unreachable / 5xx**: cron logs to journalctl and exits 1.
  systemd Persistent=true catches up next boot. NO partial writes — the
  procedure is single-pass and the SQL queries are read-only until step
  8. Memory file writes happen per-group inside step 3-5; a mid-loop
  failure leaves earlier groups' lessons in place (acceptable, lessons
  are append-only) but no `iteration_runs` row.
- **Claude CLI not on PATH OR returncode != 0**: cron raises and exits
  1. Memory files unchanged for the failing group; earlier groups
  already written stay (append-only).
- **Claude returns malformed JSON**: cron raises with the raw stdout
  prefix in the error message; exits 1. Operator fixes Claude prompt
  drift via skill-file edit.
- **`ANTHROPIC_API_KEY` missing**: cron logs a warning during startup
  and only hard-fails when it actually has to invoke Claude (so an
  empty-state week with no losing groups still exits 0).

## API contract

This routine writes to local files + Postgres only. It does NOT call
`/v1/*` endpoints — those are runtime oversight surfaces. The systemd
unit MUST be configured `User=trader` with `EnvironmentFile=/opt/ai-trading/.env`
so `POSTGRES_*` and `ANTHROPIC_API_KEY` populate.

Files this routine writes (one each per cycle):

- `crypto-bot/claude-routines/memory/lessons-learned.md` — one entry per
  detected group (always).
- `crypto-bot/claude-routines/skills/known-traps.md` — one TRAP-NNN
  entry per `is_structural=true` group only.
- `crypto-bot/claude-routines/memory/strategy-performance.md` — block
  replacement inside `<!-- BEGIN/END perf-table -->` markers.
- `crypto-bot/claude-routines/memory/recent-regime-history.md` — drop
  entries older than 30d.

One SQL row per cycle:

- `brain.iteration_runs` (run_type='post_mortem').

The `--append-system-prompt-file` flag is mandatory in step 3 per
ADR-002. The compiled refs file
(`references/crypto/compiled/refs-crypto-decision.md`) is NOT injected
here — the post-mortem cron operates on historical data and explicit
skill rules; it does not need the runtime decision references.
