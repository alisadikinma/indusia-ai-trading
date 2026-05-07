# Trading Discipline (Iron Rules)

Per Iron Law 4 (`CLAUDE.md`), this file is read-only by convention. The
runtime brain (Claude oversight) MUST NOT auto-edit it. Operator-only edits,
with ADR. The Iron Rules below override every other skill's APPROVE
outcome -- they are the last gate before `/v1/decide` POST.

## Iron Rules

1. **Never override risk rails.** Position-size cap (25% equity), max 3
   concurrent, daily-loss circuit breaker (-5%), per-trade 2x ATR(14)
   trailing stop, max-drawdown kill switch (-20% from peak) are owned by
   Freqtrade IProtection in a separate process. Permitted oversight actions:
   POST `decision='veto'` or `decision='resize'` with `size_mult` in
   [0.5, 1.5]. Forbidden actions: any attempt to disable, extend, or reset
   a rail. If a rail conflict is detected, POST `decision='veto'` with
   reasoning citing the rail.
2. **Never revenge-trade.** Count consecutive losing trades from
   `brain.brain_journal` where `actual_outcome='loss'` ordered by `ts DESC`
   without an intervening win. If count >= 2, POST `decision='veto'` for
   every entry signal for the next 4 hours (regardless of regime or
   checklist). Reasoning must contain the literal token
   "revenge-cooldown".
3. **Never chase missed entries.** If the pending signal's `ts` is older
   than 1 closed 15m candle (i.e. now - signal.ts > 15 minutes), do not
   POST any decision for it. Markets that already moved are not the
   markets we modelled.
4. **Max one resize per signal.** A signal row in `brain.signals` carries a
   single `claude_size_mult`. Once `claude_decision` is non-NULL the row is
   idempotent (the decide endpoint returns 409 on re-POST). Never plan to
   upsize on re-evaluation -- this rule is also enforced by the API.
5. **Always journal reasoning.** Every `/v1/decide` POST requires
   `reasoning` of length >= 10 characters (enforced by DecideRequest in
   `pulse-bridge/pulse_bridge/v1_routes/decide.py`). No silent decisions.
   Reasoning must cite the regime, the failing/passing checklist items, or
   the Iron Rule that fired.

## Failure modes

Patterns observed in similar bots; the Iron Rules above were authored
specifically against these:

- **Revenge trading after stop-out** -- trader (or brain) doubles size
  after a loss to "make it back". Rule 2 imposes a hard 4h cooldown after
  the second consecutive loss.
- **FOMO chasing late entries** -- price has already moved 1+ candle past
  the EMA-cross trigger. Rule 3 forbids POSTing on stale signals.
- **Sizing-up after a winning streak** -- post-win confidence overrides
  baseline sizing. Rule 4 + the 1.5x cap in DecideRequest both enforce a
  ceiling; this rule forbids re-decide.
- **Regime misclassification on Sunday low-liquidity** -- wide spreads and
  thin volume on Sunday UTC 00:00-04:00 inflate ATR and ADX. Rule 1's
  delegation to risk rails plus `regime-detection.md` `volatile` branch
  contain it; if the brain still classifies trending_up here, RESIZE 0.5x
  is the safer of the two valid actions.
- **Reasoning-as-rationalization** -- pasting "looks good" into the
  reasoning field. Rule 5 + the 10-char floor block this; reviewers should
  reject reasoning text without numeric or rule-citation content.
