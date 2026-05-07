# Known-Failure-Modes

> Distilled from NotebookLM notebook `d3fe46b9-a3c2-4915-87c3-72c708835749`
> (`polymarket`, 121 sources) + raw research report 2026-05-07.
> Last refreshed: 2026-05-07. Per ADR-002 references RAG layer.

This file documents **Polymarket-specific** failure modes only. Generic crypto
market failures (exchange insolvency, 3AC/Alameda contagion, derivative
exchange outages, hot-wallet hacks) live in `references/crypto/known-failure-modes.md`
and are not repeated here. The Polymarket failure surface is governed by three
unique vectors: (1) UMA oracle resolution, (2) Polygon-MEV / on-chain
hazards, (3) prediction-market liquidity dynamics around resolution events.

## Topic 1 — Oracle Disputes, Governance Attacks, and Resolution-Day Crashes

The dominant tail risk on Polymarket is **resolution being incorrect** despite
ground truth. This is structurally different from a price-prediction error
because no amount of forecasting skill protects against it. Failure modes
observed:

1. **UMA whale governance attack** — A token holder with > 5% of UMA voting
   weight stakes a self-interested resolution. Smaller dispute participants
   lose bonds; the market resolves contrary to fact. Canonical case: the
   "$7M Ukraine Mineral Deal" market in March 2025 resolved YES with no
   underlying signed deal.
2. **Definitional dispute** — Resolution criteria contain ambiguous terms; the
   community votes a "common-sense" interpretation that bettors did not
   anticipate. Example: the Venezuela "invasion" market.
3. **Resolution-day liquidity crash** — As resolution approaches, market
   makers withdraw quotes (no edge in providing liquidity once the outcome is
   visually settled). Spreads widen from 1¢ to 5–10¢ in the final hour;
   anyone needing to exit before settlement pays a steep tax.
4. **Multi-day DVM freeze** — A disputed market freezes all collateral for
   48–96 hours during DVM voting. Any cross-platform arb leg dependent on
   Polymarket settlement cannot be unwound until DVM finalises.

- $7M Ukraine Mineral Deal manipulation case — UMA governance attack canonical example [Source: NotebookLM source #23 — How a $7 Million Market Was Manipulated on Polymarket (BeInCrypto)]
- Polymarket voters "verifiably scammed" — community reaction to UMA going rogue [Source: NotebookLM source #58 — Polymarket voters just verifiably got scammed (r/CryptoCurrency)]
- Definitional dispute pattern: Venezuela "invasion" market [Source: NotebookLM source #55 — Polymarket Faces Prediction Disputes Over the Definition of Venezuela's "Invasion" (KuCoin)]
- Webopedia controversy explainer: incentive misalignment at the heart of UMA disputes [Source: NotebookLM source #57 — Why Is Polymarket's UMA Controversial? (Webopedia)]
- Resolution latency = days during DVM dispute, freezes collateral [Source: NotebookLM source #46 — Latest UMA News (CoinMarketCap)]

**Actionable rule for the brain:** Never hold > 1% of equity in a single market
across resolution. Exit at $0.93–$0.95 before DVM-window risk if criteria are
non-objective; let only objective-source markets (NOAA temp, ESPN final score)
ride to settlement.

## Topic 2 — MEV Sandwich Attacks, Ghost Transactions, and Polygon On-Chain Hazards

Polygon's public mempool exposes Polymarket order flow to MEV searchers in
ways that traditional CEX traders never face. Documented failure patterns:

1. **Sandwich attacks on market-impact orders** — A searcher sees a pending
   large order, frontruns to push price unfavourably, lets the victim fill,
   then unwinds at the new midpoint. Damage is usually 5–25 bps but tail events
   reach 50+ bps.
2. **Ghost transactions on authorization revocations** — Reordering of
   `approve()` calls can leave a bot with stale token approvals or, worse, a
   half-revoked approval that fails subsequent fills. Bots see "successful" tx
   receipts that never actually transferred value.
3. **RPC failover gaps** — When a primary RPC endpoint (Chainstack / Alchemy /
   QuickNode) fails mid-order, naive retry logic submits the same nonce twice;
   one fails, one fills, and the bot's internal state diverges from the chain.
4. **Polygon congestion during macro events** — Election nights, major Fed
   announcements, and sports finals spike priority fees 5–10×. Bots without
   dynamic gas estimation submit orders that sit pending until the event has
   resolved against them.

- Polygon launched VeBloP private mempool to mitigate MEV reordering [Source: NotebookLM source #62 — Polygon Launches Private Mempool for One-Line MEV Protection (KuCoin)]
- Bot Battle Experiment documents ghost-transaction trapping of automated systems [Source: NotebookLM source #38 — In-Depth Analysis of the Polymarket Bot Battle Experiment (Binance Square)]
- Beyond Simple Arbitrage: backup RPC endpoints + automatic failover required for survival [Source: NotebookLM source #15 — Beyond Simple Arbitrage (Medium / illumination)]
- MEV bot landscape and reordering economics on Polygon [Source: NotebookLM source #78 — MEV bot development company (BlockchainX)]
- Public-mempool reordering pioneered on Ethereum, replicated cheaply on Polygon [Source: NotebookLM source #93 — Top Ethereum Teams Join Forces To Return MEV Profits To Users (The Defiant)]

**Actionable rule for the brain:** Use private mempool / VeBloP routing for any
single order > 5% of top-of-book depth. For all orders, validate the on-chain
receipt event log (not just tx hash) before updating internal position state.

## Topic 3 — Position-Sizing Blowups, Liquidity Mirage, and Late-Resolution Mispricing Traps

The third Polymarket-specific failure family is **structural liquidity
mismatch**. Top-of-book on a Polymarket binary may show $50K depth, but the
total resolved-side liquidity at any usable price is often 5–10× smaller
across the full book. Bots sizing positions from displayed depth get crushed
when forced to exit.

Specific patterns:

1. **Longshot trap** — Markets priced ≤ $0.05 have a historical realisation
   rate of ~0.43%, which translates to taker mispricing of approximately −57%.
   Yet retail flow systematically buys $0.01–$0.03 contracts, and naive
   "expected-value" bots paying maker rebates to provide liquidity at $0.04
   absorb adverse selection from informed flow.
2. **Late-resolution scalping inversion** — A market sitting at $0.92 with
   "criteria functionally met" can flip to $0.40 in minutes if a single
   ambiguous statement reopens the resolution question. Scalpers without a
   stop-loss discipline get caught.
3. **Bot battle / "dumbest strategy survives"** — In adversarial bot-vs-bot
   markets, complex strategies with many parameters get arbitraged away
   faster than simple ones. The Bot Battle Experiment found "dumb" mean-reversion
   strategies outlasted sophisticated ML models because the latter overfit
   the recent regime.
4. **Insider-trading enforcement risk** — Trading a public-official market
   with non-public information now triggers DOJ/CFTC enforcement under the
   "Eddie Murphy Rule" extension (April 2026 actions).
5. **"Four Strategies, 562 Trades, Zero Edge"** — Forensic study showing that
   forecast accuracy already priced in by competing bots leaves naive weather
   strategies with no realised edge despite high theoretical accuracy.

- 92% of Polymarket traders lose money; only ~7.6% of wallets are consistently profitable [Source: NotebookLM source #2 — Why 92% of Polymarket Traders Lose Money (Medium / Technology Hits)]
- Longshot bias: 1¢ contracts realise ~0.43% of the time, taker mispricing −57% [Source: NotebookLM source #44 — Just Found the Math That Guarantees Profit on Polymarket (Dev Genius)]
- Bot Battle Experiment: "dumbest" mean-reversion strategies outlasted sophisticated ML [Source: NotebookLM source #38 — In-Depth Analysis of the Polymarket Bot Battle Experiment (Binance Square)]
- "Four Strategies, 562 Trades, Zero Edge" forensic autopsy of weather betting [Source: NotebookLM source #91 — Four Strategies, 562 Trades, Zero Edge (ResearchGate)]
- Insider-trading prosecutions under Eddie Murphy Rule extension, April 2026 [Source: NotebookLM source #25 — Bad bets: Recent enforcement actions (Herbert Smith Freehills Kramer, April 2026)]

**Actionable rule for the brain:** Cap any single Polymarket position at 25%
of full-book USDC liquidity (not top-of-book), with a hard equity cap at 5%.
If liquidity drops mid-trade so position exceeds 25% of remaining book, reduce
immediately rather than wait for resolution.

## Quick Decision Heuristics

- If a market has had a UMA dispute or DVM vote in the last 90 days, treat dispute risk as elevated; halve position size.
- If criteria contain "common sense" rather than a named source, refuse positions > 0.5% of equity.
- If price ≤ $0.05, never buy as taker; longshot bias makes EV negative net of fees.
- If top-of-book depth shrinks > 50% in 60s, exit immediately — resolution-day liquidity crash signature.
- If single order > 5% of top-of-book, route via VeBloP / private mempool.
- If on-chain receipt does not include the expected event log, freeze internal state and wait for next block.
- If priority-fee p90 > 5× baseline, halt new orders; macro-event congestion regime.
- If Polymarket / Kalshi cross-leg is open and Polymarket disputes, mark Kalshi leg illiquid for 96h.
- If a "complex" multi-parameter strategy underperforms a simple mean-reversion baseline for 30 days, retire it.
