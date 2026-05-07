# Recent Regime History

> Initialised 2026-05-07 as part of Phase 6 (Memory + Journal helpers +
> Continuous Learning Ops).

## Purpose

Rolling 30-day log of regime classifications written by the **oversight
loop routine** every 5 minutes. Used by the runtime brain to spot
**regime drift** — e.g. "ranging persisted for 5 consecutive days when
the prior 90d median dwell-time was 1-2 days; tighten approvals". The
routine appends one line per cycle; the Phase 6 post-mortem cron compacts
entries older than 30 days each Sunday via
`infra.scripts.post_mortem_cron.compact_regime_history`.

The runtime brain MAY append here (this is the one memory file that the
oversight loop writes — it is the *output* of regime-detection.md, not a
discipline file). The cron MAY drop lines older than 30 days. Operator
edits are tolerated (e.g. annotating a regime mis-classification) but not
automated by anything.

## Last 30 days

(Empty initially. Each oversight cycle appends one line:
`- YYYY-MM-DD HH:MM regime=<r> conf=<n>/10 source=oversight-loop`. The
cron drops lines whose date is older than the rolling window each
Sunday.)

## Format convention

```
- YYYY-MM-DD HH:MM regime=<trending_up|trending_down|ranging|volatile> conf=<1-10>/10 source=oversight-loop
```

Lines that don't match the leading `- YYYY-MM-DD` pattern are preserved
by the compactor (so prose annotations survive).
