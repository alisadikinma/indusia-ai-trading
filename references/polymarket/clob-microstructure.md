# Clob-Microstructure

> Distilled from NotebookLM notebook `d3fe46b9-a3c2-4915-87c3-72c708835749`
> (`polymarket`, 121 sources) + raw research report 2026-05-07.
> Last refreshed: 2026-05-07. Per ADR-002 references RAG layer.

Polymarket is a hybrid-decentralized exchange: an off-chain Central Limit Order
Book (CLOB) matches intent, while on-chain Polygon settlement transfers
ERC-1155 conditional tokens. Anything algorithmic must respect both halves of
the architecture — the off-chain layer dictates latency budget and rate limits,
the on-chain layer dictates settlement finality, gas economics, and MEV
exposure.

## Topic 1 — CLOB Matching Engine and API Layer Architecture

The matching engine is an off-chain order-driven CLOB (operated by Polymarket
infrastructure, not on Polygon directly). Order submission, cancellation, and
matching all happen off-chain in sub-100ms; only settlement of the matched fill
hits Polygon. This is the core reason high-frequency strategies are viable —
quote updates do not pay gas. The exchange exposes three logical layers:
**Gamma API** (market discovery, metadata, resolution criteria), **CLOB API**
(REST + WebSocket for trading), and the **Polygon settlement contract** (UMA
CTF Exchange + Conditional Token Framework).

Authentication is two-tier: (L1) an EIP-712 wallet signature derives long-lived
API credentials without paying gas; (L2) HMAC-SHA256 signs every subsequent
REST/WebSocket request with the derived credentials for low-latency calls. The
WebSocket endpoint `wss://ws-subscriptions-clob.polymarket.com/ws/` streams
order book deltas and trade ticks — bots must maintain an in-memory book from
deltas because REST snapshots are rate-limited.

- Matching engine is off-chain hybrid CLOB; sub-100ms matching latency [Source: NotebookLM source #10 — Polymarket API Architecture, Endpoints, Use Cases (Medium / Jung-Hua Liu)]
- Token standard is ERC-1155 Conditional Token Framework with atomic YES/NO pair management [Source: NotebookLM source #6 — Polymarket API for Developers (dev.to / Chainstack)]
- Tick size ranges $0.001 to $0.01 across markets — precision in probability pricing [Source: NotebookLM source #3 — Polymarket API for Developers (dev.to)]
- WebSocket feed `wss://ws-subscriptions-clob.polymarket.com/ws/` is the primary real-time data conduit [Source: NotebookLM source #10 — Polymarket API Architecture]
- Auth is dual: EIP-712 wallet signature + HMAC-SHA256 derived credentials [Source: NotebookLM source #20 — Polymarket CLOB API Order Placement Guide (Scribd)]
- Official SDKs: `py-clob-client-v2` (Python), `@polymarket/clob-client` (TS), `rs-clob-client` (Rust) [Source: NotebookLM source #41 — Polymarket/py-clob-client-v2 (GitHub)]

**Actionable rule for the brain:** If WebSocket delta stream lags > 500ms or
disconnects mid-session, refuse to place new orders until a fresh REST snapshot
is reconciled and delta cursor resumes — partial books cause phantom-fill MEV
exposure.

## Topic 2 — USDC Settlement on Polygon, pUSD, and Gas Optimization

Settlement migrated from bridged USDC.e to **native USDC** issued directly by
Circle on Polygon, plus the Polymarket-specific **pUSD** stablecoin (1:1
Circle-backed). This eliminates cross-chain bridge risk and reduces redemption
latency. Polygon uses the EIP-1559 fee model: a protocol-set base fee is
burned, and a user-set priority fee (tip) determines inclusion priority. For
prediction-market trading, gas spikes during high-event traffic (election
nights, Fed announcements, sports finals) can flip a thin-spread arb negative,
so dynamic gas estimation is mandatory.

Polymarket subsidizes gas on most user actions via **Account Abstraction /
meta-transactions**, meaning retail traders never hold native POL. Bots that
sign EIP-712 orders inherit this — the matching engine settles on-chain on the
trader's behalf. For makers placing thousands of quotes/day, this is decisive
economics: maker rebates can reach 50% on selected markets while gas is
abstracted away.

- Migration to native USDC + pUSD removed bridge risk for settlement [Source: NotebookLM source #33 — Circle and Polymarket Shift to Native USDC for Onchain Settlement (FinTech Weekly)]
- Polygon uses EIP-1559: base fee burned, priority fee user-set [Source: NotebookLM source #77 — EIP-1559 Explained: Fee Market Reform (Eco)]
- Account Abstraction / meta-transactions subsidize gas so traders need not hold POL [Source: NotebookLM source #43 — Polygon: Creating a Polymarket trading skill (Chainstack Docs)]
- Maker rebates up to 50% in finance-category markets [Source: NotebookLM source #18 — Polymarket Fees Explained 2026 (KuCoin)]
- Polygon raised gas limit to 100M, ~2380 TPS theoretical [Source: NotebookLM source #100 — Polygon Increases Gas Limit (Reddit /r/0xPolygon)]

**Actionable rule for the brain:** Before placing any taker order whose edge is
< 1.5%, fetch current Polygon priority-fee p90 from a public RPC and abort if
the round-trip gas exceeds 30% of expected edge. Maker quotes in the same regime
remain safe (rebate > gas).

## Topic 3 — MEV on Polygon Mempool, Reordering, and Private Mempool

Polygon's public mempool is observable and reorderable. Searchers run sandwich
attacks, frontrunning, and authorization-revocation reordering ("ghost
transactions") — practices originally pioneered on Ethereum but cheaper on
Polygon due to low base fees. For Polymarket bots placing market-impact orders,
the consequence is unfavourable fill prices and occasional phantom fills where
a position appears, vanishes, or settles at an unexpected midpoint.

Polygon launched **VeBloP** — a private mempool for one-line MEV protection —
which ships transactions to validators directly without broadcast. Combined
with backup RPC endpoints (Chainstack, Alchemy, QuickNode) and automatic
failover, this is the production-grade defense. Bots without private mempool
access should expect 5–25 bps of slippage per market-impact order, with
occasional 50+ bps tail events.

- MEV searchers run reordering and ghost-transaction attacks on Polygon [Source: NotebookLM source #62 — Polygon Launches Private Mempool / KuCoin]
- VeBloP private mempool is the recommended one-line MEV defense [Source: NotebookLM source #62 — KuCoin]
- Authorization-revocation reordering can trap automated systems with stale approvals [Source: NotebookLM source #38 — Polymarket Bot Battle Experiment (Binance Square)]
- Backup RPC endpoints + automatic failover are required for survival during chain congestion [Source: NotebookLM source #15 — Beyond Simple Arbitrage (Medium / illumination)]

**Actionable rule for the brain:** Never submit a single order > 5% of visible
top-of-book depth on a public-mempool RPC. Either route via private mempool /
VeBloP, or split across N child orders sized < 5% each, with random jitter
50–250ms between submissions.

## Quick Decision Heuristics

- If WebSocket delta latency > 500ms, halt new order placement and reconcile.
- If priority-fee p90 > 30% of expected per-trade edge, skip taker leg, hold maker quote.
- If a single taker order would consume > 5% of top-of-book depth, split into child orders or route via private mempool.
- If `py-clob-client-v2` returns 401 mid-session, rotate HMAC creds and re-derive — do not retry on stale keys.
- If REST snapshot and WebSocket book diverge by > 1 tick on midpoint, treat book as stale until next full refresh.
- If pUSD/USDC redemption pathway is the only exit and gas > 1% of position, batch redemptions weekly rather than per-trade.
- If Polygon RPC primary fails, auto-failover to backup before next order; never queue orders to a failed RPC.
- If a market's tick size is $0.01 (vs $0.001), require ≥ 2-tick spread before quoting maker — otherwise rebate < adverse-selection cost.
