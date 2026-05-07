# Crypto Market Regime Taxonomy

> Distilled from NotebookLM notebook `14c3a70f-c265-456e-a937-9281af14cae1`
> (`ai-trading-research`, 84 sources). Last refreshed: 2026-05-07.
> Per ADR-002 references RAG layer.
>
> **Source-coverage note:** the notebook covers regime-classification AI
> systems and BTC dominance regimes well. Asia/EU/US session patterns,
> high-volatility squeeze definitions, and altcoin-season indicators are
> NOT in the notebook source set — flagged below as supplementary
> external knowledge.

## Topic 1 — Risk-On / Risk-Off / Neutral macro regime

OpenClaw's `crypto-macro-regime` skill explicitly classifies the broader
market state into **Risk-On, Risk-Off, or Neutral** [Source: NotebookLM
source #1 — OpenClaw crypto-macro-regime skill listing]. Inputs combine:

- Fear & Greed Index
- Reddit sentiment
- BTC dominance trend

The `PreReason` API supplies pre-analyzed Bitcoin briefings with cross-
asset correlations (Treasury yields, Fed balance sheet, M2 money supply)
and returns trend direction + confidence + regime classification
[Source: NotebookLM source #2 — PreReason API regime returns].

For the brain's purposes, treat these three macro regimes as orthogonal
to micro regime (trending up / down / ranging on the pair). Risk-Off
macro + trending-up micro is a common bear-rally trap; veto continuation
trades unless edge is overwhelming.

**Actionable rule for the brain:** During a Risk-Off macro regime
(BTC dominance rising, F&G < 30, treasury yields spiking), reject all
new long-altcoin entries regardless of pair-level micro signal.

## Topic 2 — Volatility regime detection (CloddsBot, System R)

CloddsBot's unified risk engine runs **volatility regime detection** to
adjust Kelly sizing and circuit breakers dynamically
[Source: NotebookLM source #3 — CloddsBot volatility regime engine].
The Python library `System R` provides a pre-trade gate with regime
detection + drawdown analysis [Source: NotebookLM source #4 — System R
pre-trade gate].

When an agent detects a ranging/choppy environment, it switches to
**mean reversion** strategies rather than momentum breakouts
[Source: NotebookLM source #5 — CloddsBot mean-reversion mode].

**Actionable rule for the brain:** If realized 1h vol is in the top
quartile of trailing 30d AND price is at a Bollinger Band extreme, treat
as "high-vol mean reversion" regime — accept reversion signals at
confidence ≥ 6, veto breakout signals at confidence ≤ 7.

## Topic 3 — Event-driven regimes (FOMC + macro catalysts)

The `Market News Analyst` skill auto-fetches and ranks market-moving
news with explicit focus on **FOMC decisions and central bank policy**,
letting the AI adjust strategic posture pre-event
[Source: NotebookLM source #6 — Market News Analyst FOMC focus].

Practical implication for the brain: 2 hours before scheduled FOMC and 4
hours after are high-volatility windows where backtest assumptions
typically break.

**External (treat as hint):** Post-FOMC mean-reversion is a known
pattern — the initial 30-min reaction often retraces 30–60% within 4
hours as positioning resets. Quoting external sources here would require
re-grounding via fresh research.

**Actionable rule for the brain:** Within ±2h of any FOMC decision or
ECB rate announcement, halve `size_mult` for all approved entries; veto
new continuation signals (mean-reversion-trap risk).

## Topic 4 — Regime-mismatch as an explicit failure mode

`Edge Strategy Reviewer` is a quality gate during backtesting that
penalizes strategies suffering extreme **regime dependency**
[Source: NotebookLM source #7 — Edge Strategy Reviewer regime gate].

`Signal Postmortem` skill logs post-trade outcomes and tags losses
caused by shifting conditions under a `REGIME_MISMATCH` label
[Source: NotebookLM source #8 — Signal Postmortem REGIME_MISMATCH tag].

This means the system can distinguish "strategy is broken" from
"strategy is misaligned to current regime" — important for the brain's
Phase 9.5 iteration loop logic (failure_mode='regime_specific' is a
known enum in `brain.iteration_runs`).

**Actionable rule for the brain:** When journal-recent shows ≥ 3
consecutive losses tagged `REGIME_MISMATCH` for the same strategy,
recommend strategy halt for that pair (not strategy disable globally) +
escalate to operator. Don't auto-disable — Iron Law 4.

## Topic 5 — Session-based patterns (HINT, validate)

**External (not in notebook):**
- **Asian session** (00:00–08:00 UTC): historically lower volume,
  range-bound; mean-reversion strategies often outperform.
- **EU/US overlap** (13:00–17:00 UTC): peak liquidity, news catalysts,
  trend initiation. Momentum-breakouts perform better here.
- **Weekend windows**: thinner books, wider spreads, higher slippage on
  taker orders.

**Actionable rule for the brain:** During Asian-session hours OR
weekends, prefer mean-reversion-tagged signals over breakout-tagged
signals. During EU/US overlap, opposite. If signal type contradicts
session pattern, downgrade confidence by 1 point.

## Topic 6 — High-volatility squeeze + altcoin season (HINT, validate)

**External (not in notebook):**
- **High-vol squeeze**: market consolidates into abnormally tight range
  (Bollinger Bands contracting), latent liquidity builds, resolution
  is typically explosive directional breakout.
- **Altcoin season**: capital rotates BTC → smaller caps. Confirmed when
  ≥ 75% of top-50 altcoins outperform BTC over 90-day rolling window,
  usually after structural break in BTC dominance.

**Actionable rule for the brain:** If BTC dominance breaks below its
30-day moving average AND ≥ 50% of top-20 altcoins are positive on the
day, treat as alt-season-precursor regime — accept altcoin breakout
signals at lower confidence floor (≥ 5 instead of ≥ 6).

## Topic 7 — Spot BTC ETF approval = structurally significant break (2024-01)

A 2024 study using the **Chow Test** (p-value 0.004) confirmed a
statistically significant structural break in Bitcoin's microstructure
upon Spot BTC ETF approval [Source: Coinmonks Medium 2024 — "A Deep Dive
into BTC ETF Microstructure" via NotebookLM backtest-data-sources
citation 15]. The Information Coefficient (IC) — a measure of a signal's
predictive power — shifted from near-zero to **consistently negative**
post-approval, indicating the market transitioned from momentum-driven
to a sustained mean-reversion regime.

Practical consequence: a strategy backtested entirely on pre-2024 data
that shows positive momentum IC will mechanically lose money post-2024
unless the brain recognizes the regime flip. Walk-forward folds whose
OOS windows all live pre-ETF (2018-01 → 2023-12) cannot validate
post-ETF survival — at least one OOS fold must straddle 2024-01.

**Actionable rule for the brain:** If the strategy's most recent
backtest run has all OOS folds ending before 2024-01-11 (ETF approval
date), demand a re-run with at least one fold whose test window
spans 2024-01 → 2024-12 before clearing Iron Law 2 gate. A strategy
whose 5-fold pass excludes the post-ETF regime is curve-fit to an
extinct market structure.

## Quick Decision Heuristics

- Risk-Off macro (F&G < 30, BTC dom rising, yields spiking) → reject new
  long-altcoin entries regardless of pair signal.
- Strategy backtest OOS folds all end pre-2024-01-11 → reject Iron Law
  2 clearance; demand re-run including post-ETF window (Chow Test
  p=0.004 confirms regime break).
- Realized 1h vol top-quartile + Bollinger extreme → "high-vol
  reversion" regime; favor reversion, veto breakout (confidence ≤ 7).
- ±2h around FOMC/ECB → halve size_mult, veto continuation.
- ≥ 3 consecutive REGIME_MISMATCH losses on a strategy/pair → halt for
  THAT pair, not strategy globally; alert operator.
- Asian session OR weekend → prefer mean-reversion signals; downgrade
  breakout-signal confidence by 1.
- BTC dom break-below 30d MA + ≥ 50% top-20 alts green → alt-season
  precursor; accept alt breakouts at confidence ≥ 5 floor.
- Strategy with extreme regime dependency (Edge Strategy Reviewer flag)
  → confidence cap 5/10 even on perfect-fit signals.
