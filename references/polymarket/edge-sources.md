# Edge-Sources

> Distilled from NotebookLM notebook `d3fe46b9-a3c2-4915-87c3-72c708835749`
> (`polymarket`, 121 sources) + raw research report 2026-05-07.
> Last refreshed: 2026-05-07. Per ADR-002 references RAG layer.

The 2025-2026 Polymarket profit landscape is brutally concentrated: an
"informed minority" of < 3.5% of accounts captures ~30% of total profit, and
~3.7% of wallets account for ~80% of profitable trade volume. Edge does not
come from "being right" in a forecaster sense — it comes from execution
advantage, structural mispricing, and disciplined exploitation of repeatable
patterns. Below are the edge sources with the strongest empirical support.

## Topic 1 — News Velocity Arbitrage and Late-Resolution Scalping

The single most replicable edge in 2026 is **news-to-execution latency
arbitrage**. When a catalyst hits the wires (Fed statement, election call,
court ruling, weather forecast update), the market price *trends* over
seconds-to-minutes rather than re-pricing instantly. Bots that subscribe to
official news wires + curated expert social feeds and execute within 100ms can
capture 5–15% spreads with high frequency before the broader market converges.

A complementary, lower-skill-ceiling pattern is **late-resolution scalping**.
As an event approaches its deadline and the outcome becomes effectively
certain, prices often sit at $0.85–$0.95 instead of converging to $1.00. This
gap arises because (a) early traders exit due to capital efficiency, (b)
retail does not understand the resolution rules well enough to be confident,
and (c) some markets have multi-day UMA settlement so late buyers are paid for
holding the resolution-latency risk. Scalpers buy YES at $0.92 when ground
truth is functionally settled, hold through resolution, and earn ~8% in days.

- News velocity bots capture 5–15% spreads in the first 100ms after a catalyst [Source: NotebookLM source #15 — Beyond Simple Arbitrage: 4 Polymarket Strategies Bots Profit From in 2026 (Medium)]
- Late-resolution scalping targets $0.85–$0.95 prices with effectively-settled outcomes [Source: NotebookLM source #15 — Datawallet Top 10 Polymarket Trading Strategies]
- "Informed minority" < 3.5% of accounts capture ~30% of profit; advantage is execution, not prediction [Source: NotebookLM source #22 — Study: A tiny elite sets Polymarket's prices (jpost.com)]
- Bots that enter within 100ms of catalyst beat retail entry by minutes [Source: NotebookLM source #44 — AI Agents in Prediction Markets (newyorkcityservers.com)]

**Actionable rule for the brain:** If a news catalyst (named entity in 1,200+
expert-feed list) hits and the market price moves < 30% of the implied repricing
within 60 seconds, take the leading side with size scaled by feed confidence.

## Topic 2 — Sports Model Alpha and Specialized Probability Models (Weather, NFL, NBA, MLB)

Sports markets and weather markets are favourable hunting grounds because
**resolution is objective** (NOAA temperature reading, league official score)
— eliminating UMA dispute risk almost entirely — and because retail flow is
biased ("optimism bias" for popular teams, hometown teams, narrative picks).

**Weather markets**: Bots compare ensemble forecast consensus (GFS + ECMWF +
HRRR) against market prices. The "Shenzhen weather" arbitrage and US-city
temperature markets reportedly produced $24K/month for a single retail-built
bot. Edge appears when the market lags a 48–72 hour forecast update by ~4
hours; bots reporting 85–90% accuracy on directional temperature outcomes.

**Sports**: The MLB-Polymarket exclusive partnership (2025) and NBA / NFL
discussions have increased official data flow. Player-prop and team-market
models with proper Elo / Bayesian adjustments find edge against fan-sentiment
overpricing, particularly in derivative markets ("will player X exceed N
yards"). NFL markets are explicitly the largest sports volume on the platform.

- Weather bot reportedly making $24K/month using NOAA + ensemble forecasts [Source: NotebookLM source #11 — Found The Weather Trading Bots Quietly Making $24,000 (Dev Genius)]
- Some weather bots report 85–90% directional accuracy on 48–72h temperature forecasts [Source: NotebookLM source #36 — The weather market edge is real and nobody is talking about it (Moltbook)]
- MLB-Polymarket exclusive prediction market partnership signed with CFTC integrity framework [Source: NotebookLM source #28 — MLB names Polymarket exclusive Prediction Market Exchange partner (mlb.com)]
- NFL markets are largest sports volume; NBA partnerships in negotiation [Source: NotebookLM source #29 — The NFL Doesn't Want You Trading This (Sports Illustrated)]
- Cautionary: "Four Strategies, 562 Trades, Zero Edge" — naive weather betting can fail when forecast accuracy already priced in [Source: NotebookLM source #91 — Four Strategies, 562 Trades, Zero Edge: A Forensic Autopsy of Algorithmic Weather Betting (ResearchGate)]

**Actionable rule for the brain:** For weather markets, only enter when
ensemble-model probability and market-implied probability differ by > 8
percentage points AND the position holds < 72 hours. Below 8pp the edge is
forecast noise, not market mispricing.

## Topic 3 — Cross-Platform Arbitrage (Kalshi vs Polymarket) and LLM Ensemble Forecasting

**Cross-platform arbitrage** is structural: Kalshi (CFTC-regulated, USD/ACH
settlement) and Polymarket (USDC/Polygon, global) list overlapping events
(Federal Reserve rate decisions, election outcomes, sports). Pricing diverges
because participant pools differ — US retail is concentrated on Kalshi,
crypto-native traders on Polymarket. A YES at $0.45 on Polymarket + NO at
$0.52 on Kalshi guarantees a ~$0.03 risk-free profit per share *if* resolution
criteria align exactly.

**Caveats**: (1) resolution wording must match perfectly — divergent rulings
have wiped out arb books; (2) capital is locked across two platforms with
different settlement speeds (Kalshi 1–3 day ACH vs Polymarket instant USDC);
(3) fees and slippage absorb most of the spread, so live edges are usually
1–5 cents per share, not the headline 5+ cents.

**LLM ensemble forecasting** is the alpha source for long-horizon, low-frequency
markets (election outcomes, geopolitics, AI capability questions). Ensembles of
50+ diverse LLM personas, aggregated via confidence-weighted Bayesian
combination, achieve Brier scores rivalling Metaculus crowd predictions
(0.081 for Claude 4 Opus probability-conditioned vs 0.084 for human crowd).
Used as a divergence detector against market price > 15% mispriced.

- Polymarket has 3.5x more resilient liquidity depth vs Kalshi on overlapping markets [Source: NotebookLM source #12 — Polymarket vs Kalshi Explained (QuantVPS)]
- Kalshi-Polymarket arb spreads observed at 5¢ on overnight-resolving markets [Source: NotebookLM source #38 — Found 5¢ arbitrage spreads in prediction markets expiring tomorrow (r/algotrading)]
- Open-source Kalshi-Polymarket arb bot (Reddit) demonstrates the pattern is replicable [Source: NotebookLM source #14 — I built a bot to automate 'risk-free' arbitrage between Kalshi and Polymarket (r/algotrading)]
- LLM ensemble (50+ personas, Bayesian aggregation) achieves Brier 0.081, beats Metaculus crowd 0.084 [Source: NotebookLM source #65 — Wisdom of the silicon crowd (PMC PMC11800985)]
- Maker-side excess return: +0.77% on YES, +1.25% on NO; takers lose at 80/99 price levels [Source: NotebookLM source #44 — Just Found the Math That Guarantees Profit on Polymarket (Dev Genius)]
- Logical / correlation arb across linked markets when violations exceed 3% [Source: NotebookLM source #15 — Beyond Simple Arbitrage (Medium)]

**Actionable rule for the brain:** For cross-platform arb, require (a)
resolution wording byte-equivalence after stripping whitespace/case, (b)
combined cost < $0.96 after fees on both legs, (c) max 5% of equity per
arb-pair to absorb settlement-divergence tail risk.

## Quick Decision Heuristics

- If catalyst hits and price moves < 30% of implied repricing in 60s, take leading side immediately.
- If late-resolution market trades at $0.85–$0.95 with criteria functionally met and < 24h to deadline, enter long.
- If weather-market mispricing < 8 percentage points vs ensemble forecast, skip — too noisy.
- If Kalshi-Polymarket combined-leg cost ≥ $0.96 net of fees, skip — no edge.
- If LLM-ensemble divergence from market < 15%, do not enter — within model noise.
- Always prefer maker quotes over taker fills; takers lose at 80% of price levels.
- If the market has < $50K depth at top-of-book, scale position to ≤ 1% equity regardless of perceived edge.
- If "longshot" priced ≤ $0.05, do not buy — historical realisation rate ~0.43%, taker mispricing ~−57%.
