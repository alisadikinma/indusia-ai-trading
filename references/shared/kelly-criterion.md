# Kelly Criterion

> Source attribution: distilled from NotebookLM notebook `ai-trading-research`
> (id `14c3a70f-c265-456e-a937-9281af14cae1`, 84 sources). Kelly's underlying
> mathematics (1956) is supplemental where the notebook flagged its source-set
> as silent on the formula details.
> Last refreshed: 2026-05-07. Per ADR-002 references RAG layer.

The Kelly criterion is the bankroll-fraction sizing rule that maximises the
**geometric mean** (long-run compounded growth rate) of an edge. For this
project both bots use sizing constrained by the Iron Law 1 hard cap (25%
of equity per trade) AND a Kelly-derived inner cap; the inner cap is
typically the binding constraint and exists precisely because the outer
cap is too generous for realistic edge estimates.

## Topic 1 — The Kelly formula + worked example

For a binary win/loss bet with win probability `p`, loss probability
`q = 1 - p`, and **payoff ratio** `b` (units won per unit risked on a win,
e.g. 1.0 = even-money, 2.0 = 2:1 reward:risk), the Kelly-optimal fraction
of bankroll to risk is:

```
f* = (p · b - q) / b
   = p / a - q / b      where a = 1 (loss multiplier) and b = win multiplier
```

**Worked example.** A trader has back-tested an entry rule and observes
edge:

- Win rate `p = 0.55`
- Payoff ratio `b = 1.1` (i.e. average win is 1.1× average loss)
- Loss rate `q = 1 - p = 0.45`

Full Kelly:

```
f* = (0.55 · 1.1 - 0.45) / 1.1
   = (0.605 - 0.45) / 1.1
   = 0.155 / 1.1
   ≈ 0.1409
   ≈ 14.1% of bankroll per trade
```

Half-Kelly (typical fractional Kelly for traders): `0.5 × 14.1% ≈ 7.0%`.
Quarter-Kelly: `≈ 3.5%`. Eighth-Kelly (the fraction explicitly taught for
solo crypto bots [Source: NotebookLM ai-trading-research citation 4, source
`80b886a5-8068-4a0a-ac38-63a6b7b4815f` *Solo Crypto Quant Starter Kit*]):
`≈ 1.76%`.

Note that when `b = 1` (even-money), the formula simplifies to `f* = 2p - 1`,
which is the classic "edge over odds" form. A trader with 55% win rate at
even money should risk 10% of bankroll per Full Kelly — already aggressive.

**Actionable rule for the brain:** never enter a position sized at Full
Kelly. The estimation error on `p` and `b` from finite backtest data is
asymmetric — overestimating edge causes negative compounding; underestimating
just slows growth. Default to ≤ Half-Kelly and pin the inner cap to
Quarter-Kelly when the backtest sample size per fold is < 200 trades.

## Topic 2 — Full vs fractional Kelly + drawdown mathematics

Full Kelly maximises long-run growth rate **assuming** `p` and `b` are
known exactly. Two structural problems with Full Kelly in trading:

1. **You don't know `p` and `b` exactly.** Backtested edge is a noisy,
   backward-looking estimate. If realized edge is 80% of estimated edge,
   Full Kelly on the estimate is 1.25× over-bet — and over-betting is
   asymmetrically punitive (negative compounding past the optimum).
2. **Full Kelly mathematically guarantees a 50% drawdown will eventually
   occur.** Most retail and institutional traders' psychological + capital
   tolerance is much lower. Half-Kelly cuts variance roughly in half while
   reducing growth rate by only ~25%, producing a far more sustainable
   equity curve.

Production-grade open-source frameworks reflect this. The `CloddsBot`
trading agent's unified risk engine integrates Kelly sizing alongside VaR,
CVaR, volatility regime detection, stress testing, daily-loss limits, and
a kill switch — Kelly is one input to a multi-rail risk stack, not a
standalone sizing rule [Source: NotebookLM ai-trading-research citations
1–2, source `5085c31e-3405-4217-bfba-6f66618c79b1`]. The `claude-trading-skills`
`position-sizer` skill explicitly offers Fixed Fractional, ATR-based, and
Kelly methods side-by-side and includes a "budget mode" that enforces
portfolio-level position-percentage caps on Kelly outputs
[Source: NotebookLM ai-trading-research citation 3, source
`a74e4525-cadb-45b3-b69e-722d50bbd7f3` `position-sizer`].

**Actionable rule for the brain:** if the candidate position size derived
from Kelly exceeds the Iron Law 1 hard cap (25% of equity), the binding
constraint is the hard cap — but ALSO log this to journal as a flag,
because Kelly suggesting > 25% usually means the edge estimate is
implausibly high and probably mis-estimated.

## Topic 3 — Risk of ruin, edge uncertainty, and geometric returns

**Risk of ruin under continuous Kelly is mathematically 0%** because bet
size scales down proportionally as bankroll drops. In practice, real
markets break the assumption: overnight gap-downs, slippage, partial fills,
and exchange outages introduce discrete losses that Full Kelly's continuous
scaling cannot absorb. The crypto market in particular features 20%+ gap
moves that bypass intra-bar Kelly recomputation entirely.

**Edge estimation uncertainty.** The Kelly formula is "GIGO": the better
your edge estimate, the closer Full Kelly is to optimal. In practice:

- Backtest sample of < 100 trades per fold → edge confidence interval is
  wider than the point estimate; use ≤ Quarter-Kelly.
- Backtest sample of 100–500 trades per fold → Half-Kelly is defensible.
- Backtest sample of > 500 trades per fold AND walk-forward stable →
  ⅔-Kelly is the realistic upper bound for capital-protected operations.

**Geometric vs arithmetic returns.** Kelly maximises geometric mean, not
arithmetic mean — i.e. compounded growth, not average per-trade return.
This matters because of **volatility drag**: a 50% loss requires a 100%
gain to break even, so a strategy with high arithmetic return but high
variance can have lower geometric return than a smoother strategy with
lower arithmetic return. Optimising for geometric return is what makes
Kelly the right framework for compounding capital — and what makes
fractional Kelly attractive even when you're confident in your edge.

**Actionable rule for the brain:** if a backtest reports high arithmetic
mean per-trade return but the geometric-mean equity curve is flat or
declining over the OOS period, the strategy has fatal volatility drag —
veto regardless of the headline expectancy number.

## Quick Decision Heuristics

- If sample size per OOS fold < 200 trades, cap sizing at Quarter-Kelly
  (or lower) — edge confidence interval is too wide for Half-Kelly.
- If Kelly-suggested fraction > Iron Law 1 hard cap (25%), the cap binds
  AND log the entry to journal as a "suspect over-confident edge" flag.
- If realized win rate over rolling 50-trade window deviates from
  backtested `p` by > 5 percentage points, halve the Kelly multiplier
  immediately and trigger a post-mortem.
- If geometric-mean equity curve is flat while arithmetic mean is positive,
  veto regardless of headline expectancy — volatility drag is destroying
  compounding.
- If the strategy involves crypto perp futures with potential overnight
  gap risk, never exceed Half-Kelly even with strong backtest evidence —
  continuous-rebalance assumption is broken by gap moves.
- If two simultaneous open positions are positively correlated (rho > 0.6),
  treat them as a single position for Kelly sizing — avoid double-counting
  edge.
- If the operator has explicitly set `kelly_multiplier` in config.json,
  that ceiling is binding regardless of computed Kelly — never override
  operator preference autonomously (Iron Law 4).
- If you (the brain) cannot articulate `p` and `b` for the current trade
  in concrete numbers grounded in backtest data, default to Fixed Fractional
  sizing (1% bankroll risk) instead of Kelly — vague Kelly is worse than
  honest fixed-fractional.
