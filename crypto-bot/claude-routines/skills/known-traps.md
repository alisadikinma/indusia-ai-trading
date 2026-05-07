# Known Traps

A catalogue of recurring losing-trade signatures observed by THIS portfolio.
Every entry pairs a concrete signature `(regime, funding_bucket, vol_bucket,
signal_type)` with a concrete VETO rule that `signal-evaluation.md`
checklist item 6 cross-references each cycle.

## How this file grows

This file is grown by the Phase 6 post-mortem cron, NOT by the runtime
oversight loop. The mechanism is documented in `post-mortem-protocol.md`
and operationalised in `infra/scripts/post_mortem_cron.py` (Phase 6).

Append rule (executed weekly by the cron, never by the runtime brain):

1. Cron groups closed losing trades from `brain.brain_journal` by signature
   `(regime, funding_bucket, vol_bucket, signal_type)`.
   - `funding_bucket`: <-0.05%, [-0.05%, 0.05%], >0.05%.
   - `vol_bucket`: ATR(14) percentile <50, [50, 90), >=90.
2. When 3+ losses share a single signature within a rolling 30-day window,
   the cron appends a new entry to the `## Current entries` section below
   with this exact format:

   ```
   ### TRAP-NNN (added YYYY-MM-DD)
   - signature: regime=<r>, funding_bucket=<b>, vol_bucket=<v>, signal_type=<s>
   - sample_count: <n>
   - mean_loss_pct: <m>
   - veto_rule: VETO entries when <signature criteria>
   - first_seen_journal_id: <id>
   ```

3. Iron Law 4 applies: the cron is the only writer; the runtime brain READS
   this file every cycle but MUST NOT modify it. Operator may prune entries
   via ADR.

## Current entries

No entries yet. The Phase 6 post-mortem cron populates this section as
patterns emerge from live + paper-trade journal data. Expected cadence:
zero entries during the first week of paper trading; first entries appear
once enough losing trades have accumulated to satisfy the 3-within-30-days
threshold.

When `signal-evaluation.md` checklist item 6 runs against an empty list,
it always returns Yes (no trap matched). This is intentional -- the file's
empty state is its initial valid state, not a missing-data condition.

Cross-references:
- `signal-evaluation.md` checklist item 6 reads this file every cycle.
- `post-mortem-protocol.md` defines the append procedure.
- `regime-detection.md` defines the `regime` token used in signatures.
