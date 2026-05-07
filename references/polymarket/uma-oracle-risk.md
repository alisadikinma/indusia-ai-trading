# Uma-Oracle-Risk

> Distilled from NotebookLM notebook `d3fe46b9-a3c2-4915-87c3-72c708835749`
> (`polymarket`, 121 sources) + raw research report 2026-05-07.
> Last refreshed: 2026-05-07. Per ADR-002 references RAG layer.

UMA's Optimistic Oracle is the resolution backbone of every Polymarket market.
Resolution risk — not price risk — is the dominant tail-risk vector on
Polymarket. A trader can be 100% correct on the underlying question and still
lose if the oracle resolves against the on-the-ground reality. The brain must
treat UMA dispute exposure as a first-class risk factor, alongside liquidity
and MEV.

## Topic 1 — Optimistic Oracle Mechanics: Bond, Window, DVM Escalation

UMA's Optimistic Oracle V2 (OOv2) operates by a "truth by consensus" pattern.
A **proposer** asserts the resolution outcome along with a USDC bond. The
assertion enters a **liveness window** — historically two hours for Polymarket
markets — during which any party may **dispute** by posting a matching bond
(observed minimum around $750 USDC, sometimes higher for high-stakes markets).
If undisputed, the proposed outcome becomes final and the proposer is
refunded. If disputed, resolution escalates to UMA's **Data Verification
Mechanism (DVM)**, where UMA token holders stake and vote; the losing side
forfeits their bond.

DVM resolution adds **multi-day latency** (typically 48–96 hours from dispute
to final settlement). During this period, all positions in the disputed market
are frozen — collateral cannot be redeemed, and arbitrage legs cannot be
unwound. This makes oracle disputes a liquidity event as much as a resolution
event.

- Proposed outcome is final unless disputed within ~2-hour liveness window [Source: NotebookLM source #47 — Polymarket's Use of Polygon and UMA for Decentralized Resolution (MEXC)]
- Dispute requires matching bond (≈$750 USDC observed minimum on most markets) [Source: NotebookLM source #57 — Why Is Polymarket's UMA Controversial? (Webopedia)]
- Disputes escalate to UMA DVM where token holders vote to resolve [Source: NotebookLM source #34 — Can LLMs Help Decentralized Dispute Arbitration? A Case Study of UMA-Resolved Markets on Polymarket (arXiv 2604.15674)]
- Losing voters in DVM forfeit staked UMA — system rewards consensus alignment over objective truth [Source: NotebookLM source #17 — Polymarket suffers governance attack (ChainCatcher)]
- Live OOv2 settled-event explorer at `oracle.uma.xyz?project=Polymarket` [Source: NotebookLM source #85 — Optimistic Oracle V2 | Settled — UMA]

**Actionable rule for the brain:** If a market is within 6 hours of resolution
and a dispute could plausibly arise (ambiguous wording, geopolitical, celebrity
behaviour), cap exposure at 0.5% of equity regardless of perceived edge.

## Topic 2 — Case Study: The $7M "Ukraine Trump Mineral Deal" Manipulation (March 2025)

The most-cited resolution-risk case study is the **"Will Trump and Zelensky
sign a Ukraine mineral deal by March 2025?"** market on Polymarket. The market
had ~$7M in open interest and was resolved **YES** despite no formal mineral
deal being signed by the deadline — a clear factual mismatch that became the
canonical example of UMA governance attack.

**Timeline**:
1. Market deadline approached without a publicly reported signed deal.
2. A **whale UMA holder** (estimated 5M+ UMA tokens) staked the YES proposal,
   pointing to a preliminary framework discussion as sufficient.
3. The dispute was raised by minority holders; the case escalated to DVM vote.
4. The whale's voting power dominated the DVM and resolved YES.
5. Outcome: NO-side bettors lost $7M to YES-side bettors despite ground-truth
   reality. UMA voters who aligned with the whale earned rewards; dissenters
   lost staked tokens.

This case demonstrated the **economic bug** in optimistic oracles where
DVM voters can simultaneously hold positions in the disputed market: the
"consensus chasing" incentive trumps factual accuracy when bonds + position
P&L exceed the cost of buying voting weight. A second illustrative dispute
involved the **"Will Venezuela be invaded?"** market, where the definition of
"invasion" itself was ambiguous and triggered prolonged dispute discussion.

- "$7M Ukraine Mineral Deal" was resolved YES despite no signed deal — UMA whale governance attack [Source: NotebookLM source #23 — How a $7 Million Market Was Manipulated on Polymarket (BeInCrypto)]
- Same case, additional reporting: large players manipulated the oracle and won by losing the bet [Source: NotebookLM source #17 — Polymarket suffers governance attack (ChainCatcher)]
- Reddit post-mortem: voters were "verifiably scammed" by the rogue resolution [Source: NotebookLM source #58 — Polymarket voters just verifiably got scammed (r/CryptoCurrency)]
- Venezuela "invasion" market — dispute over ambiguous resolution wording [Source: NotebookLM source #55 — Polymarket Faces Prediction Disputes Over the Definition of Venezuela's "Invasion" (KuCoin)]
- Reddit forensic thread on the Mineral Deal — "negligence and manipulation" [Source: NotebookLM source #23 — The Polymarket Mineral Deal Controversy (r/CryptoCurrency)]

**Actionable rule for the brain:** For any market where the proposer or top
holder has > 5% of UMA voting weight AND a same-side position exceeding $500K,
flag as **conflict-of-interest oracle risk** and refuse new entry, regardless
of edge.

## Topic 3 — Resolution Failure Modes and Ambiguous Question Patterns

Beyond outright manipulation, the more common UMA risk is **ambiguous resolution
criteria**. Polymarket markets are written by a market creator; resolution
criteria can be vague, time-zone ambiguous, or rely on unspecified data sources.
The OOv2 falls back to "common sense" defined by UMA voters, who may interpret
edge cases differently than market participants assumed.

Documented pattern categories:

1. **Definitional ambiguity** — "Will X be invaded?", "Will Y resign?", "Will Z
   be confirmed?" — where the qualifying event has no canonical legal moment.
2. **Time-zone / deadline ambiguity** — "by end of March 2025" without
   specifying UTC vs local; rulings have flipped on this alone.
3. **Source ambiguity** — "Will the temperature exceed X?" without naming the
   weather station; UMA voters may pick a different station than bettors used.
4. **Compound event ambiguity** — multi-leg outcomes ("X AND Y both happen")
   where one leg is undisputed but the other is unclear.

Academic analysis of past disputes (arXiv 2604.15674) found LLMs can flag
~70% of ambiguous resolution criteria *before* trading begins — providing a
viable filter layer. UMA token-holder voting accuracy on objective questions
is high (>90%) but drops sharply on definitional disputes.

- Ambiguous resolution categories documented in academic case study [Source: NotebookLM source #34 — Can LLMs Help Decentralized Dispute Arbitration? A Case Study of UMA-Resolved Markets on Polymarket (arXiv 2604.15674)]
- DVM resolution latency typically days, freezing collateral redemption [Source: NotebookLM source #46 — Latest UMA News (CoinMarketCap)]
- Webopedia controversy explainer documents systemic incentive misalignment [Source: NotebookLM source #57 — Why Is Polymarket's UMA Controversial? (Webopedia)]

**Actionable rule for the brain:** Before opening any position > 1% of equity,
parse the resolution criteria with an LLM check: "List every term in this
resolution clause that could be disputed in court." If list length ≥ 2, halve
position size. If ≥ 4, refuse the trade.

## Quick Decision Heuristics

- If market is within 2 hours of resolution and unsettled, do not enter new positions — dispute window risk.
- If proposer wallet holds > 5% of UMA AND a same-side bet > $500K, treat as conflict-of-interest, refuse trade.
- If resolution criteria contain ≥ 4 disputable terms (per LLM parse), refuse trade entirely.
- If a market is in active DVM dispute, mark all related positions illiquid for 96 hours; do not include in P&L mark-to-market.
- If similar markets in the past 90 days have had disputes, apply 30% probability discount to perceived edge.
- If the resolution source is "common sense" rather than a named data feed (NOAA, Bloomberg, ESPN), cap exposure at 0.5% equity.
- If a competing CFTC-regulated venue (Kalshi) lists the same event, use it as a reality-check on resolution interpretation.
- If UMA token price drops > 20% in a week, dispute defense weakens (cheaper to attack); reduce all open Polymarket exposure 50%.
