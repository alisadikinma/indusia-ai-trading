# Strategy Performance

> Initialised 2026-05-07 as part of Phase 6 (Memory + Journal helpers +
> Continuous Learning Ops).

## Purpose

Per-regime cumulative trading performance for the crypto bot, refreshed
weekly by the Phase 6 post-mortem cron
(`infra/scripts/post_mortem_cron.py`). The cron recomputes the table below
from `brain.brain_journal` (90-day rolling window) and replaces the content
between the BEGIN-perf-table / END-perf-table HTML-comment markers
(literal markers visible only inside the table block — referenced here in
prose without the angle-bracket form so the in-place regex replacement
targets the table block only). The replacement is in place; never appended,
never partially edited.

The runtime brain (5-min oversight loop) reads this file every cycle. The
"approve" decision in `signal-evaluation.md` checklist item 5 references
the per-regime profit factor here: regimes with PF < 1.0 over 90d add 1 to
the required confidence floor.

This file is auto-managed by the cron. Operator may add prose around the
markers; do NOT edit content inside the markers (it is overwritten weekly).

## Per-regime metrics

<!-- BEGIN perf-table -->
| regime | count | win_rate | avg_pnl_pct | profit_factor | sharpe |
|---|---|---|---|---|---|
| (no data) | 0 | - | - | - | - |
<!-- END perf-table -->

## Last refresh

2026-05-07T05:07:54Z

## Notes

- `count` includes only journal rows where `actual_pnl_pct IS NOT NULL`
  (closed trades).
- `profit_factor` = sum(positive pnl) / abs(sum(negative pnl)). 0.0 if no
  losing trades yet (well-defined empty state, not infinity).
- `sharpe` is daily-equivalent — average pnl pct divided by sample stddev.
  Treat as directional, not precise; full Sharpe is computed in
  `brain.backtest_runs.metrics` during walk-forward.
