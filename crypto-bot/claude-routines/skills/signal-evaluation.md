# Signal Evaluation

Run this checklist on every pending signal returned by
`/v1/context_bundle.dynamic.pending_signals` (rows in `brain.signals` with
`claude_decision IS NULL`). Output a single decision per signal: approve,
veto, resize, or no_action. The decision is POSTed to `/v1/decide` per the
schema in `pulse-bridge/pulse_bridge/v1_routes/decide.py` (DecideRequest).

## When to apply

Once per cycle, immediately after `regime-detection.md` produces a regime
classification. Skip the signal entirely (no POST) if its `ts` is older than
1 closed candle (15 minutes on 15m timeframe) per `trading-discipline.md`
Iron Rule 3.

## Pre-approval checklist

Each item is a strict Yes/No. Compute every item before deciding.

1. Regime confidence >= 7/10 from `regime-detection.md`?
2. Signal direction matches regime?
   - `enter_long` + `trending_up` -> Yes.
   - `enter_long` + `ranging` -> No.
   - `enter_long` + `trending_down` -> No.
   - `enter_long` + `volatile` -> No.
3. Funding rate within +/- 0.05% (absolute)?
   Read `dynamic.funding_rate` from context_bundle; treat missing as 0.0.
4. Volatility percentile < 90?
   ATR(14) of current candle vs the 30-day distribution; reject right tail.
5. Current drawdown < 10%?
   `dynamic.drawdown_pct` < 10. Above 10% means the kill switch (-20%) is
   approaching; tighten approvals defensively.
6. Pattern NOT present in `known-traps.md`?
   Cross-reference the (regime, funding_bucket, vol_bucket, signal_type)
   tuple against current entries.
7. Daily approve count < 8?
   Count `decision='approve'` rows in `brain.brain_journal` since 00:00 UTC
   today; rate-limits over-eagerness.

## Decision rules

Apply rules in order; first match wins.

- **VETO** (POST `decision='veto'`, omit `size_mult`) if ANY of items
  2, 5, 6 = No. These are non-negotiable: regime mismatch, drawdown rail,
  known trap. Confidence 8-10.
- **APPROVE** (POST `decision='approve'`, omit `size_mult`) if ALL 7 items
  = Yes. Confidence 7-10.
- **RESIZE** (POST `decision='resize'`, `size_mult=0.7`) if exactly 5 of 7
  items = Yes AND items 2, 5, 6 are all Yes. Confidence 5-7. Iron Rule 4
  forbids upsizing on re-evaluation.
- **NO_ACTION** otherwise (POST `decision='no_action'` is NOT a valid
  decide value per DecideRequest -- instead, do not POST and let the rule-
  based default fire downstream). Logged in cycle output.

`reasoning` field MUST list the failing checklist items by number, e.g.
"Vetoed: items 2 (long in ranging), 6 (matches known-trap funding-flip)."
Minimum 10 chars enforced by the API.

## Cross-references

- `regime-detection.md` -- consumed by item 1, 2.
- `known-traps.md` -- consumed by item 6.
- `trading-discipline.md` -- Iron Rules override any APPROVE outcome here
  (e.g. revenge-trade cooldown vetoes regardless of checklist score).
- `post-mortem-protocol.md` -- documents how losing approvals from this
  skill feed `known-traps.md` over time.
