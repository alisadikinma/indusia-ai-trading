# Post-Mortem Protocol

Procedure that classifies every closed losing trade and feeds the catalogue
in `known-traps.md` plus the lessons file under
`crypto-bot/claude-routines/memory/lessons-learned.md` (created in Phase 6).
Runs in two contexts: (a) the runtime oversight cycle when a trade has just
closed losing, (b) the Phase 6 weekly post-mortem cron.

## Trigger

Fires when a `brain.brain_journal` row records `actual_pnl_pct < -1.0`
(loss of more than 1.0% on the trade-level PnL).

The runtime brain detects the trigger by querying:

```sql
SELECT id, signal_id, regime, decision, reasoning, actual_pnl_pct
FROM brain.brain_journal
WHERE actual_pnl_pct < -1.0
  AND ts >= now() - interval '5 minutes'
```

at the start of each cycle. Any row hit fires the Procedure below.

## Procedure

1. **Classify failure cause.** Choose exactly one of the five labels
   (mutually exclusive, evaluated top-to-bottom):
   - `regime_misclass` -- regime at decide time differs from realised
     regime over the trade window.
   - `funding_spike` -- absolute funding rate rose above 0.10% during the
     trade.
   - `volatility_spike` -- ATR(14) crossed 2.0x rolling-30d-mean during
     the trade.
   - `lookback_bias` -- entry indicators relied on partial candle that has
     since revised; checked via re-computing EMA20/EMA50/ADX(14) on
     finalised candles.
   - `overconfidence` -- none of the above; default bucket.
2. **Pattern check.** Compute signature
   `(regime, funding_bucket, vol_bucket, signal_type)` per
   `known-traps.md` "How this file grows". Query the same signature across
   the 30-day window in `brain.brain_journal`. If sample_count >= 3,
   append a new TRAP entry to `known-traps.md` with the exact format
   documented there. Iron Law 4: only the post-mortem cron may write to
   `known-traps.md`; the runtime brain raises a flag and stops.
3. **Always-append lesson.** Append to
   `crypto-bot/claude-routines/memory/lessons-learned.md` (Phase 6 file)
   one entry per losing trade, regardless of pattern threshold. Format:
   `- YYYY-MM-DD signal_id=<id> cause=<label> lesson=<one sentence>`.
4. **Update strategy stats.** Increment the per-regime loss counter in
   `crypto-bot/claude-routines/memory/strategy-performance.md` (Phase 6
   file). One line per regime: total_trades, wins, losses, mean_pnl_pct.

## Output

Procedure step output is the structured JSON below; the cron reads stdout
and writes the files in steps 2-4. The runtime brain emits the same JSON to
stdout but does NOT write files (Iron Law 4 + integrity).

```json
{
  "journal_id": 1234,
  "signal_id": 5678,
  "actual_pnl_pct": -1.42,
  "cause": "regime_misclass | funding_spike | volatility_spike | lookback_bias | overconfidence",
  "signature": {
    "regime": "trending_up | trending_down | ranging | volatile",
    "funding_bucket": "neg | flat | pos",
    "vol_bucket": "low | mid | high",
    "signal_type": "enter_long | enter_short | exit_long | exit_short"
  },
  "matches_existing_trap": true,
  "trap_threshold_reached": false,
  "lesson": "<one-sentence lesson>"
}
```

Cross-references:
- `known-traps.md` -- step 2 appends here when threshold met.
- `regime-detection.md` -- step 1 `regime_misclass` re-runs this skill on
  finalised candles.
- `signal-evaluation.md` -- step 1 `overconfidence` cause indicates the
  pre-approval checklist passed but outcome was negative; tightens future
  approvals via lessons-learned.
