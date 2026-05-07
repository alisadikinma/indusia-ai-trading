# INDUSIA AI Trading

> Multi-bot autonomous AI trading platform — **LLM oversight brain** over **dual deterministic execution bodies**: Freqtrade (crypto: Binance + Blofin) and py-clob-client (Polymarket prediction markets). 5-minute oversight cron, append-only audit journal, references RAG layer, dashboard cockpit.

> Built by **PT INDUSIA Kecerdasan Digital** — Indonesian AI product studio.
> Domain: [INDUSIA.ai](https://indusia.ai) · Repo: [github.com/alisadikinma/indusia-ai-trading](https://github.com/alisadikinma/indusia-ai-trading)

**Status:** Phase 2 shipped (data ingest). Mono-repo restructured 2026-05-07 to support second bot. Implementation plan at [`docs/plans/2026-05-06-ai-trading-247.md`](docs/plans/2026-05-06-ai-trading-247.md) (crypto, 16 phases). Multi-bot restructure plan at [`docs/plans/2026-05-07-multi-bot-references-restructure.md`](docs/plans/2026-05-07-multi-bot-references-restructure.md).

## Architecture at a glance

```
LLM oversight brain (Claude Code CLI / vendor-swappable)
     │ 5-min cron · HMAC-signed JSON · references/ RAG inject
     ▼
pulse-bridge (FastAPI, /v1/crypto/* + /v1/polymarket/* + /dashboard/*)
     │
     ├──► crypto-bot/      ──► Freqtrade body ──► CCXT ──► Binance + Blofin
     └──► polymarket-bot/  ──► py-clob-client body ──► Polymarket CLOB on Polygon
     │
     ▼
Postgres 16 + TimescaleDB
     · brain.*       (crypto bot, legacy schema name kept per ADR-001)
     · polymarket.*  (polymarket bot)
     │
     ▼
dashboard-ui/ (Next.js + TradingView Lightweight Charts, top-nav bot switcher)
     +
Telegram bot (alerts + HMAC kill-switch, shared)
```

See full architecture, decision rationale, learning loops, and validation gates in [`CLAUDE.md`](CLAUDE.md) and the linked design docs / ADRs.

## Repository layout

| Path | Purpose |
|---|---|
| [`crypto-bot/`](crypto-bot/) | Crypto bot artifacts: `claude-routines/` (skills + memory + routines per cron template), `freqtrade-config/` (config.json + strategies). Reads/writes `brain.*` Postgres schema. |
| [`polymarket-bot/`](polymarket-bot/) | Polymarket bot artifacts: `claude-routines/`, `clob-client/`, `strategies/`. Reads/writes `polymarket.*`. Currently SKELETON ONLY (Phase 5+ implementation in forthcoming plan). |
| [`pulse-bridge/`](pulse-bridge/) | Shared FastAPI shim. Multi-router for both bots' brain↔body bridge + dashboard read-only API. HMAC contract identical across bots. |
| [`freqtrade-fork/`](freqtrade-fork/) | Git submodule pointing at github.com/freqtrade/freqtrade. Logically owned by `crypto-bot/`; kept at repo root per ADR-001 (rewrite-cost > benefit). |
| [`dashboard-ui/`](dashboard-ui/) | Next.js 15 cockpit. TradingView Lightweight Charts v5. Tailscale-only access. Top-nav bot switcher routes between crypto and polymarket views. |
| [`infra/`](infra/) | Docker compose, Postgres init + migrations (000-003), systemd units, data loaders (`binance_vision.py`, `gap_detector.py`, `live_ws_ingest.py`), ops scripts (`compile_refs.py`, `walkforward_folds.py` planned). |
| [`references/`](references/) | RAG knowledge layer per ADR-002. Per-bot subfolders (`crypto/`, `polymarket/`) + `shared/` + `global-trading-config.md` (Iron Laws + JSON contract + precedence). Compiled `refs-<bot>-decision.md` (≤8K tokens) injected per cron cycle via `--append-system-prompt-file`. Operator-curated only. |
| [`tests/`](tests/) | Pytest. Real services in integration tests (mocks only here, never in production). |
| [`docs/`](docs/) | `plans/` (16-phase crypto + multi-bot restructure), `research/` (NotebookLM artifacts), `decisions/` (ADRs from `gaspol-adr`). |

## Validation philosophy

No live capital deployed without all three gates passing:

1. **Walk-forward backtest** — crypto: Sharpe > 1.5, MaxDD < 25%, profit factor > 1.4, ≥ 100 trades across **all 5 OOS folds**. Polymarket: Brier < 0.20, calibration ECE < 5%, ≥ 100 resolved markets per OOS fold, oracle-dispute drill pass-rate.
2. **Paper trade** — 3–4 weeks live data, fake money, drift vs backtest expectation < 30%.
3. **Live $100** — 4 weeks observation, weekly drift gate, no risk-rail breaches.

If any gate fails → **Phase 9.5 Iteration Loop** (max 3 cycles, then architectural rethink ADR).

## Iron Laws

These are non-negotiable, hard-coded into the architecture (full text in [`CLAUDE.md`](CLAUDE.md)):

1. **Brain cannot override risk rails.** Position size, stop-loss, daily loss circuit breaker, drawdown kill switch, API key rotation — enforced in body process, separate from oversight brain.
2. **No live trade without backtest + paper-trade sign-off.** Phase 9 + Phase 10 are HARD GATES.
3. **No placeholder data in production code paths.** Real Postgres, real CCXT/py-clob-client, real `os.environ[...]`. Mocks only in `tests/` and `playwright/fixtures/`.
4. **Brain must not modify its own discipline files.** `<bot>/claude-routines/skills/trading-discipline.md`, per-bot risk config, migrations, `references/`, `CLAUDE.md`, `docs/decisions/*` — operator-only edits, with ADR.
5. **Memory grows append-only.** Both `brain.brain_journal` and `polymarket.brain_journal` Postgres tables enforce UPDATE/DELETE rejection via trigger raising SQLSTATE 42501.

See [`CLAUDE.md`](CLAUDE.md) for the full operational contract loaded into every session.

## License

See [`LICENSE`](LICENSE).
