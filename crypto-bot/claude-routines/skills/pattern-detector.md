# Pattern Detector

Decide whether a candidate cluster of losing trades is a **structural
pattern** worth promoting to `known-traps.md`, or random noise to log only
in `memory/lessons-learned.md`. Invoked exclusively by
`infra/scripts/post_mortem_cron.py` (Phase 6); the runtime oversight loop
NEVER calls this skill (Iron Law 4).

## When to apply

Fires once per `FailureGroup` returned by
`detect_recurring_losses(conn, since_days=7)` — a SQL grouping over
`brain.brain_journal` JOIN `brain.signals` that already enforces a minimum
3 occurrences and a single shared signature
`(regime, funding_bucket, vol_bucket, signal_type)`. The cron streams the
`FailureGroup` JSON into the prompt; this skill returns ONE JSON object.

## Decision rules

A cluster is **structural** (and merits a TRAP entry) iff ALL four are met:

1. **Min occurrences**: `count >= 3` (already enforced upstream; reassert
   to fail-safe).
2. **Same exact signature**: `(regime, funding_bucket, vol_bucket,
   signal_type)` matches for every trade in the group. The SQL `GROUP BY`
   guarantees this — verify the input rather than re-deriving.
3. **Combined PnL impact**: `count * abs(avg_pnl_pct) >= 1.5` (i.e. the
   cluster cost the portfolio at least 1.5% in aggregate). Smaller
   clusters are noise even at 3+ count.
4. **Time spread**: `time_spread_days >= 3.0`. Three losses inside a
   single 24-hour event window are likely the same macro shock, not a
   structural pattern. Reject.

If ANY rule fails: `is_structural=false`. Still write a lesson, but do
NOT append to `known-traps.md`.

If ALL pass: `is_structural=true`. Author the
`suggested_known_trap_entry` as a single-sentence VETO rule citing the
exact signature, e.g.
`VETO entries when regime=trending_up and funding_bucket=pos and vol_bucket=high and signal_type=enter_long`.

## Output format

Return ONE JSON object, no prose, no code fences. Schema:

```json
{
  "is_structural": true,
  "suggested_known_trap_entry": "VETO entries when regime=trending_up and funding_bucket=pos and vol_bucket=high and signal_type=enter_long",
  "lesson_summary": "Three trend-following longs in extreme positive funding wicked out before continuation; the 4h ATR was >2x rolling-30d mean each time. Approve trend-following longs only when funding_bucket != pos."
}
```

Field rules:

- `is_structural`: boolean. True only if all four Decision rules pass.
- `suggested_known_trap_entry`: string OR null. NON-null iff
  `is_structural=true`. Must start with `VETO entries when ` and cite the
  exact signature tokens.
- `lesson_summary`: 2-3 sentences max, written in declarative voice. Cite
  the concrete trigger (which indicator, what threshold) — no vague
  phrasing.

Cross-references:
- `known-traps.md` — destination of TRAP entries when `is_structural=true`.
- `post-mortem-protocol.md` — defines the failure-cause taxonomy (regime_misclass, funding_spike, volatility_spike, lookback_bias, overconfidence).
- `signal-evaluation.md` checklist item 6 reads the resulting traps.
