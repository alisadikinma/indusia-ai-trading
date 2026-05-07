# Regulatory-Cftc

> Distilled from NotebookLM notebook `d3fe46b9-a3c2-4915-87c3-72c708835749`
> (`polymarket`, 121 sources) + raw research report 2026-05-07.
> Last refreshed: 2026-05-07. Per ADR-002 references RAG layer.

Polymarket's regulatory status changed materially across 2025 and Q1–Q2 2026.
What was previously a binary "geo-blocked from US" platform is now a
KYC-mandatory, CFTC-supervised venue for US retail, with parallel federal
legislation pending and active enforcement actions for insider trading. Any
trading bot operating in 2026 must treat regulatory risk as a first-class
operational concern, not an afterthought.

## Topic 1 — CFTC Supervision and Polymarket US Reentry (2025–2026)

Polymarket previously settled CFTC charges in 2022 and exited the US market.
In late 2025–early 2026, **Polymarket sought to end the CFTC trading ban**
through a structured reentry under CFTC supervision rather than as a
purely-decentralized venue. The result is an **intermediated model**: US users
access Polymarket US through registered Futures Commission Merchants (FCMs),
with KYC/AML mandatory at account opening. The global, direct-wallet model
remains for non-US users in supported jurisdictions.

The Trump administration in early 2026 explicitly moved to **preempt state
regulation** of prediction markets, attempting to centralise jurisdiction at
the CFTC level rather than allow per-state gambling-law treatment. This
followed the **CFTC and Kalshi enforcement actions** (FCTM bulletin) targeting
prediction-market participants, signalling that federal oversight would be
treated as the controlling authority. Holland & Knight characterised the
landscape as a "continued jurisdictional battle" (Feb 2026).

- Polymarket sought end to CFTC trading ban, pursuing intermediated US reentry [Source: NotebookLM source #52 — Polymarket Seeks End to CFTC Trading Ban (PYMNTS, 2026)]
- Trump administration moves to preempt state regulation of prediction markets (2026) [Source: NotebookLM source #54 — Trump Administration Seeks to Preempt State Regulation of Prediction Markets (Broadband Breakfast, 2026)]
- CFTC and Kalshi joint enforcement bulletin (FCTM) targeting prediction-market participants [Source: NotebookLM source #45 — CFTC and Kalshi Announce Enforcement Actions Targeting Prediction Markets / FCTM (Lowenstein, 2026)]
- "Prediction Markets at a Crossroads: The Continued Jurisdictional Battle" [Source: NotebookLM source #40 — Prediction Markets at a Crossroads (Holland & Knight, Feb 2026)]
- KYC mandatory for Polymarket US; supported-country list maintained [Source: NotebookLM source #19 — Polymarket Supported and Restricted Countries 2026 (Datawallet)]

**Actionable rule for the brain:** If operating from a US-IP wallet, refuse to
place orders on the global Polymarket endpoint — only Polymarket US (FCM-routed)
is permissible. Geo-fence before order submission, not after.

## Topic 2 — The Bipartisan Prediction Market Act of 2026

In 2026, US Senators introduced the **Bipartisan Prediction Market Act of
2026**, a comprehensive federal framework for event contracts. Key provisions
reported:

1. **Enhanced KYC/AML requirements** at FCM and venue level.
2. **Advertising standards** restricting how prediction markets can be marketed
   (alignment with derivatives advertising rather than gambling advertising).
3. **Conflict-of-interest rules for public officials** — restricting trading
   on event contracts where the official has non-public information or policy
   influence over the outcome.
4. **CFTC as primary regulator** — formalising the federal preemption already
   pursued by the executive branch.

The Act has not been signed into law as of 2026-05-07, but its introduction
materially shifted dealer expectations: institutional players (FCMs, market
makers) are now positioning for a CFTC-supervised future rather than a
DeFi-anonymous one. The **"Eddie Murphy Rule"** (commodities-anti-fraud, ~2010
post-Trading-Places) has been interpreted to cover **misappropriation of
non-public government information** — meaning federal employees trading on
policy intel they helped author face the same penalties as Wall Street insider
traders. Enforcement actions have already been brought against several
participants.

- "Bipartisan Prediction Market Act of 2026" filed in Congress [Source: NotebookLM source #53 — Bipartisan Prediction Market Act of 2026 Filed in Congress (Phemex News, 2026)]
- "Eddie Murphy Rule" extended to misappropriated government information [Source: NotebookLM source #25 — Bad bets: Recent enforcement actions against prediction market participants misusing insider information (Herbert Smith Freehills Kramer, April 2026)]
- DOJ + CFTC coordinated enforcement strategy on Polymarket insider-trading charges [Source: NotebookLM source #39 — Polymarket Insider Trading Charges Illustrate DOJ and CFTC Prediction Markets Enforcement Strategy (Debevoise & Plimpton, April 2026)]

**Actionable rule for the brain:** Before trading any market involving a
named public official's actions (votes, resignations, appointments), check the
last 14 days of CFTC/DOJ enforcement bulletins; if any case is open against a
counterparty in that market, halt trading.

## Topic 3 — Comparison with Kalshi and PredictIt; Settlement and KYC Requirements

The regulatory paths of the three major US-facing prediction venues diverge
sharply:

- **Kalshi**: CFTC-regulated as a Designated Contract Market (DCM) from
  inception. Full KYC/AML at signup. USD-only via ACH (1–3 day settlement).
  Operates legally in all 50 states (subject to ongoing state challenges).
- **Polymarket**: 2022 CFTC settlement led to US exit; 2025–2026 reentry via
  Polymarket US (FCM-intermediated, KYC-mandatory). Global platform retains
  USDC/Polygon model. Maker rebates and broader market catalogue than Kalshi.
- **PredictIt**: Legacy academic CFTC no-action letter; regulatory standing
  contested across 2022–2024, separate trajectory from the new prediction-market
  framework. Limited per-market caps ($850 historically).

For the bot architecture, the key consequences are:

1. **Capital lock-up asymmetry**: Kalshi 1–3 day ACH vs Polymarket instant USDC.
   This is decisive for cross-venue arb — the Kalshi leg is illiquid for 24–72h.
2. **KYC enforcement at API level**: Polymarket US requires KYC-bound API keys;
   the global API will reject US-IP signups going forward.
3. **Fee structure visibility**: Polymarket fees are dynamic taker (0.75%–1.80%
   per recent expansions); Kalshi tiered ~1.2%. Both must be modelled per-trade,
   not as a flat constant.

- Polymarket fees expanded across new market categories in 2026 [Source: NotebookLM source #51 — Polymarket Expands Fee Structure to New Markets (Phemex News, 2026)]
- Kalshi vs Polymarket settlement speed comparison: ACH 1–3 days vs USDC instant [Source: NotebookLM source #12 — Polymarket vs Kalshi Explained: Liquidity, Regulation, Trading Strategies (QuantVPS)]
- Polymarket KYC mandatory for US access via Polymarket US [Source: NotebookLM source #19 — Polymarket Supported and Restricted Countries 2026 (Datawallet)]
- Industry maturation toward "intermediation" replacing pure anonymous direct-wallet [Source: NotebookLM source #75 — On the rise of Polymarket and prediction markets (Medium / The Capital)]

**Actionable rule for the brain:** Maintain a regulatory-watch input that
flags (a) any new CFTC enforcement bulletin in the last 7 days, (b) any change
in supported-country list, (c) any KYC-bound API rejection rate > 1% — and on
any flag, halt new entries pending human review.

## Quick Decision Heuristics

- If account IP geolocates to US and route is global Polymarket, refuse all orders.
- If counterparty in a market is named in an open CFTC/DOJ enforcement bulletin, halt trading on that market.
- If cross-platform arb requires Kalshi leg, lock capital for 72h horizon — do not size as if liquid.
- If supported-country list changes mid-session, pause and re-verify KYC status before next order.
- If trading on a public-official-action market, require explicit operator approval (insider-trading risk).
- If fee schedule changes (per Polymarket dynamic-fee announcement), recompute all live edges before next order.
- If Polymarket US (FCM-routed) endpoint differs in book depth from global by > 5%, treat as separate venues.
- If Bipartisan Prediction Market Act passes / fails, full strategy review required within 24h — regulatory regime shift.
