# Regime Detection

Classify the BTC/USDT 15m market into exactly one of four regimes using
indicators that match `crypto-bot/freqtrade-config/strategies/ClaudeOversightStrategy.py`
(EMA20, EMA50, ADX(14), ATR(14)). The classification feeds the `regime` field
of every `/v1/decide` POST and gates which signals `signal-evaluation.md`
will approve.

## When to apply

Run this skill at the start of every oversight cycle, before evaluating any
pending signal. Re-run if `/v1/context_bundle` returns OHLCV with a newer
last-candle timestamp than the previous classification.

Inputs (all from `/v1/context_bundle.dynamic`):
- `ohlcv_last_4h` — 16 closed 15m candles. EMA20/EMA50/ADX(14)/ATR(14) are
  computed on this client-side or read from the latest dataframe.
- 30-day rolling ATR baseline — read from `brain.ohlcv` 30d window via the
  routine wrapper.
- Funding rate snapshot — `dynamic.funding_rate` (when present; absent =
  treat as 0.0).

## Decision rules

The four regimes are mutually exclusive. Evaluate top-to-bottom; first match
wins. Confidence is an integer 1-10 reported back in `reasoning`.

1. **volatile** — ATR(14) > 2.0 x rolling-30d-mean-ATR, OR absolute funding
   rate > 0.10%. Action: HALT new entries this cycle. Existing positions:
   tighten trailing stop to 1.5x ATR(14) by passing `decision='resize'` with
   `size_mult=0.5` on any pending exit-side signal. Confidence floor 7/10.
2. **trending_up** — ADX(14) > 25 AND EMA20 > EMA50 on each of the last 3
   closed candles AND last close > EMA20. Action: trust trend-following long
   entries downstream. Confidence floor 7/10.
3. **trending_down** — ADX(14) > 25 AND EMA20 < EMA50 on each of the last 3
   closed candles. Action: defer (Phase 5 has no shorts; emit
   `decision='no_action'` for any long entry signal). Confidence floor 7/10.
4. **ranging** — ADX(14) < 20 AND last 12 closes contained within
   [EMA20 - 2x ATR(14), EMA20 + 2x ATR(14)]. Action: VETO trend-following
   long entries (current strategy is trend-only). Confidence floor 6/10.

If none of the four criteria fire (e.g. ADX between 20 and 25, or mixed
EMA cross within 3 candles), classify as the closest match by ADX bucket
(<22.5 -> ranging; >=22.5 -> trending_up if EMA20>EMA50 else trending_down)
and report confidence 4/10. Low-confidence regime classification feeds
`signal-evaluation.md` checklist item 1.

## Output format

The cycle's regime classification MUST appear verbatim in the `regime` field
of every subsequent `/v1/decide` POST during the cycle. Allowed values:

```
trending_up | trending_down | ranging | volatile
```

The `reasoning` field of each `/v1/decide` POST MUST include a single
sentence summarising the trigger, e.g.
"Regime=trending_up (conf 8/10): ADX14=31.4 > 25, EMA20>EMA50 last 4 candles."

See also: `signal-evaluation.md` (consumes regime), `known-traps.md`
(per-regime veto patterns), `trading-discipline.md` (Iron Rules that
override any regime-driven approval).
