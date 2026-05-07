# polymarket-bot/

Autonomous Claude-overseen trading agent for **Polymarket** prediction
markets — the sibling of [`crypto-bot/`](../crypto-bot/) in this mono-repo
per [`docs/decisions/2026-05-07-001-mono-repo-multi-bot.md`](../docs/decisions/2026-05-07-001-mono-repo-multi-bot.md).

> **STATUS: SKELETON ONLY (2026-05-07).** Folders are scaffolded; no
> implementation. The phased rollout lives in a separate plan document
> (forthcoming at `docs/plans/2026-05-XX-polymarket-bot.md`) that mirrors
> the 16-phase crypto plan with Polymarket-specific gates.

## Why this bot is structurally different from `crypto-bot/`

Polymarket is **binary-settlement event markets**, not continuous-price
crypto. The brain pattern (5-min cron oversight, append-only journal,
HMAC-signed signal envelope) carries over verbatim, but the body and
backtest gates do not:

| Concern | crypto-bot | polymarket-bot |
|---|---|---|
| Execution body | Forked Freqtrade via CCXT | py-clob-client direct against Polymarket CLOB |
| Settlement | Continuous spot/perp PnL | Binary settlement on UMA optimistic oracle resolution |
| Time-series unit | OHLCV candle | Order book snapshot + market resolution event |
| Risk model | Position-size cap, ATR trailing stop | Capital-at-risk per market (binary), bond bond UMA dispute exposure |
| Backtest gates (Iron Law 2) | Sharpe > 1.5, MaxDD < 25%, PF > 1.4 in 5 OOS folds | **Brier score < 0.20**, **calibration ECE < 5%**, ≥ 100 resolved markets per OOS fold, oracle-dispute drill pass-rate |
| Edge sources | Trend, mean-rev, momentum, regime-switch | News-velocity arbitrage, sports model alpha, late-resolution scalping, long-tail mispricing, Kalshi×Polymarket arbitrage |
| Top failure modes | Liquidity cliff, funding flip, ws gap, exchange API outage | UMA oracle dispute disasters, MEV sandwich on Polygon, resolution-day liquidity crash, ambiguous question outcomes |

## Folder layout

| Path | Purpose | Status |
|---|---|---|
| `claude-routines/` | Brain artifacts: skills (`*.md` playbook), memory (`*.md` learned wisdom), routines (cron specs). | Empty (Phase 5+ analog) |
| `clob-client/` | Wrapper around `py-clob-client` (the official Polymarket Python SDK). Will encapsulate auth, order placement, websocket subscriptions, market metadata fetch. | Empty |
| `strategies/` | Strategy modules — news-velocity arbitrage, sports model alpha, late-resolution scalper, etc. Each strategy emits signals into `polymarket.signals` for Claude oversight. | Empty |

## Postgres schema

This bot reads/writes the `polymarket.*` schema (created in Phase E of
restructure plan, migration `infra/migrations/003_polymarket_schema.sql`):

- `polymarket.markets` — market metadata (slug, outcomes, resolution_source,
  resolves_at, resolution_outcome). Unique to this bot — no equivalent on
  the crypto side.
- `polymarket.signals` — strategy signals + Claude oversight decision
  (mirrors `brain.signals` shape, with binary-outcome price columns instead
  of OHLC indicators).
- `polymarket.brain_journal` — Claude reasoning audit log, append-only per
  Iron Law 5 (same trigger architecture as `brain.brain_journal`).
- `polymarket.equity_curve` — equity snapshots.
- `polymarket.backtest_runs` — Polymarket-specific metrics in `metrics
  JSONB`: `brier_score`, `calibration_ece`, `sample_size_per_market_type`,
  `oracle_dispute_loss_count`.
- `polymarket.iteration_runs` — Phase 9.5 iteration loop tracking.

## Iron Law 4 read-only files (when populated)

The following will be operator-only edits (mirror crypto-bot list):

- `claude-routines/skills/trading-discipline.md`
- Polymarket position-sizing config (TBD — likely `clob-client/config.json`)
- `infra/migrations/*.sql`
- The repo-root `CLAUDE.md`
- The `references/polymarket/` and `references/shared/` reference layer

## Phase plan (high-level mirror, Polymarket-adapted)

The detailed plan goes in a separate document. Short version follows:

| crypto Phase | polymarket equivalent | Polymarket-specific notes |
|---|---|---|
| 0–1 (scaffold + Postgres) | covered by current restructure (mono-repo, schema migration) | — |
| 2 (Binance Vision bulk + live ws) | py-clob-client market metadata bulk + order book websocket | bulk source: Polymarket data dump APIs + historical market resolutions |
| 3 (strategy + HMAC contract) | first strategy module + same HMAC contract reused | start with news-velocity arbitrage (highest expected edge per NotebookLM research) |
| 4 (Claude routine bridge) | reuse pulse-bridge with `/v1/polymarket/decide` route | identical envelope shape |
| 5 (skills + memory) | author crypto-skills equivalents, Polymarket-tuned | adds `oracle-dispute-protocol.md`, `news-velocity-playbook.md` |
| 9 (walk-forward backtest) | Polymarket gate: Brier + ECE + sample size + dispute drill | rejects Sharpe/MaxDD as inapplicable |
| 9.5 iteration loop | identical pattern; failure modes mapped to Polymarket | — |
| 10 (paper trade) | 3–4 weeks, $0 capital, brain decides on real markets | track Brier + ECE drift vs backtest |
| 12 (live capital) | start at $100 same as crypto, 4-week observation | watch tail-risk events (oracle disputes) extra carefully |

## References

- ADR-001: `../docs/decisions/2026-05-07-001-mono-repo-multi-bot.md`
- ADR-002 (references layer): `../docs/decisions/2026-05-07-002-references-rag-layer.md`
- Restructure plan: `../docs/plans/2026-05-07-multi-bot-references-restructure.md`
- NotebookLM polymarket: `d3fe46b9-a3c2-4915-87c3-72c708835749` (alias
  `polymarket`, 121 sources)
- Polymarket raw research dump:
  `../docs/research/2026-05-07-polymarket-ai-bot-deep-research-raw.md`
