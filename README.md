# AI Trading 24/7

> Autonomous AI crypto trading agent — **Claude Code CLI brain** over **forked Freqtrade body**, with PULSE Protocol bridge, 5-minute oversight Routines, multi-source knowledge layers, and a Bot Cockpit UI.

**Status:** Pre-implementation. Design + 16-phase implementation plan locked in [`docs/plans/2026-05-06-ai-trading-247.md`](docs/plans/2026-05-06-ai-trading-247.md). Phase 0 (this commit) is repo scaffold.

## Architecture at a glance

```
Claude Code CLI (oversight brain, 5-min Routines)
     │ PULSE protocol (FastAPI shim)
     ▼
Freqtrade fork (execution body) ── CCXT ── Binance + Blofin
     │
     ▼
Postgres 16 + TimescaleDB ── Bot Cockpit UI (Next.js + TradingView Lightweight Charts)
```

See full architecture, decision rationale, learning loops, and validation gates in the design doc.

## What lives where

| Path | Purpose |
|---|---|
| `claude-routines/` | Claude Code CLI brain — skills (`*.md` playbook), memory (`*.md` persistent), routines (cron specs) |
| `pulse-bridge/` | FastAPI shim translating Claude decisions into Freqtrade hooks; also hosts dashboard read-only API |
| `freqtrade-fork/` | Freqtrade as a git submodule with our custom strategy class (`user_data/strategies/ClaudeOversightStrategy.py`) and FreqAI model |
| `dashboard-ui/` | Next.js Bot Cockpit (5 views: Live Dashboard, Strategy Lab, Brain Journal, FreqAI Insights, Iteration History) |
| `infra/` | Docker compose, Postgres init + migrations, systemd units, data loaders, secrets templates, ops scripts |
| `tests/` | Pytest test suite (root-level structural + integration tests) |
| `docs/` | Design doc, implementation plan, research artifacts (NotebookLM report), ADRs |

## Validation philosophy

No live capital deployed without all three gates passing:

1. **Walk-forward backtest** — Sharpe > 1.5, MaxDD < 25%, profit factor > 1.4 across **all** 5 OOS folds
2. **Paper trade** — 3–4 weeks live data, fake money, drift vs backtest expectation < 30%
3. **Live $100** — 4 weeks observation, weekly drift gate, no risk-rail breaches

If any gate fails → **Phase 9.5 Iteration Loop** (max 3 cycles, then architectural rethink).

## Iron Laws

These are non-negotiable, hard-coded into the architecture:

1. **Claude cannot override risk rails.** Position size, stop-loss, daily loss circuit breaker, drawdown kill switch, API key rotation — all enforced in Freqtrade outside Claude's reach.
2. **No live trade without backtest + paper-trade sign-off.** Phase 9 and Phase 10 are HARD GATES.
3. **No placeholder data in production code paths.** Mocks allowed only in `tests/` and `playwright/fixtures/`.

See [`CLAUDE.md`](CLAUDE.md) for the full operational contract.

## License

See [`LICENSE`](LICENSE).
