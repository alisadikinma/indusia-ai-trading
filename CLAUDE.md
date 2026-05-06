# CLAUDE.md — AI Trading 24/7

> **Read this first, every session.** This is the operational contract for working on this codebase.

This file is loaded automatically by Claude Code CLI at the start of every session. It encodes the architecture, conventions, anti-placeholder rules, and Iron Laws that govern this project. The full design + 16-phase implementation plan lives in [`docs/plans/2026-05-06-ai-trading-247.md`](docs/plans/2026-05-06-ai-trading-247.md) — read that for context on **why**; this file is **how**.

---

## Project Goal

Build a 24/7 autonomous AI crypto trading agent that:

1. Uses **Claude Code CLI as the oversight brain** — Routines fire every 5 minutes, brain reads market state + signal queue, judges regime, approves/vetoes/resizes signals, writes append-only journal.
2. Uses **forked Freqtrade as the deterministic execution body** — sub-100ms order placement, websocket fills, hard-coded risk rails outside Claude's reach.
3. Trades **Binance (spot + futures) and Blofin (perp)** via CCXT.
4. Runs from a **Hetzner CX22 VPS** (Frankfurt EU, €4.50/mo) with Postgres + TimescaleDB on the same host.
5. Validates against **walk-forward backtest** (Sharpe > 1.5, MaxDD < 25%, PF > 1.4 across all 5 OOS folds), then **3–4 weeks paper trade**, then **live $100** for 4 weeks before considering scale to $500.
6. **Continuously learns** through 3 nested loops: operational memory growth (every trade), adaptive ML retrain (daily), strategic iteration loop (on backtest failure, max 3 cycles before architectural rethink).

The brain is observed via a **Bot Cockpit UI** (Next.js + TradingView Lightweight Charts) on Tailscale-only access — 5 views: Live Dashboard, Strategy Lab, Brain Journal, FreqAI Insights, Iteration History.

---

## Architecture

```
┌──────────────────────────────────────────────────────────────────────┐
│  VPS Hetzner CX22 — Frankfurt EU                                      │
│                                                                        │
│  Claude Code CLI (oversight brain) ──── 5-min Routines                 │
│         │                                                              │
│         │ HMAC-signed JSON over Unix socket                            │
│         ▼                                                              │
│  pulse-bridge/ (FastAPI shim)  ◄────  dashboard-ui/ (Next.js, port 3000)│
│         │                                ▲                             │
│         ▼                                │ JWT + Tailscale-only access  │
│  freqtrade-fork/ ──── CCXT ──── Binance + Blofin                       │
│         │                                                              │
│         ▼                                                              │
│  Postgres 16 + TimescaleDB (port 127.0.0.1:5432, no public exposure)   │
│         │                                                              │
│         ▼                                                              │
│  Telegram bot (alerts + HMAC kill-switch)                              │
└──────────────────────────────────────────────────────────────────────┘
```

**The brain knows 4 things** (Claude Code CLI knowledge anatomy):

1. **Skills** (`claude-routines/skills/*.md`) — static rule playbook, read every cycle: `regime-detection.md`, `signal-evaluation.md`, `trading-discipline.md`, `known-traps.md`, `post-mortem-protocol.md`, `pattern-detector.md`, `backtest-diagnostics.md`.
2. **Memory** (`claude-routines/memory/*.md`) — accumulated wisdom from THIS portfolio: `lessons-learned.md`, `strategy-performance.md`, `operator-preferences.md`, `recent-regime-history.md`. Grown by post-mortem cron weekly.
3. **Journal** (Postgres `brain_journal` table, append-only) — every past decision with reasoning + outcome.
4. **ML priors** (FreqAI XGBoost model) — learned patterns from 5–10y OHLCV; auto-retrains daily.

**The body** (Freqtrade fork) handles execution, risk, and backtest. Claude **never** writes trading code autonomously — strategy logic changes require human design with Claude as analyst.

---

## Key Directories

| Path | Owner | Purpose |
|---|---|---|
| [`claude-routines/`](claude-routines/) | Brain | Skills, memory, routines (cron specs in `.md`) |
| [`pulse-bridge/`](pulse-bridge/) | Bridge | FastAPI shim translating Claude decisions → Freqtrade hooks. Also serves dashboard read-only API. Single FastAPI app, two routers (`/v1/*` for brain, `/dashboard/*` for UI). |
| [`freqtrade-fork/`](freqtrade-fork/) | Body | Git submodule pointing at github.com/freqtrade/freqtrade. Custom strategy lives at `freqtrade-fork/user_data/strategies/ClaudeOversightStrategy.py`. **Do not edit Freqtrade core**; only `user_data/`. |
| [`dashboard-ui/`](dashboard-ui/) | UI | Next.js 15 App Router. TradingView Lightweight Charts v5. Tailscale-only access. |
| [`infra/`](infra/) | Ops | `docker-compose.yml` (Postgres only), `migrations/*.sql`, `systemd/*.service`, `data_loader/*.py` (Binance Vision + CoinDesk), `scripts/*.py` (post-mortem cron, retrain health check, walk-forward, chaos test). |
| [`tests/`](tests/) | All | Pytest. Real services in integration tests (mocks only here, not in production code). |
| [`docs/`](docs/) | All | `plans/` (design + impl plan), `research/` (NotebookLM artifacts), `decisions/` (ADRs from `gaspol-adr`). |

---

## Anti-Placeholder Rules

This project's anti-placeholder rule is **stricter** than the default `gaspol-execute` rule because real capital is at risk.

### Hard rules

1. **No mock data in production code paths.** Mocks live only in:
   - `tests/` directories
   - `dashboard-ui/playwright/fixtures/`
   - `*.test.ts` / `*.test.tsx` files
2. **No empty arrays awaiting future API integration.** If the API isn't ready, STOP and report the blocker.
3. **No `// TODO: connect to API` comments.** Either connect now or open an ADR documenting the intentional defer with rollback plan.
4. **No hardcoded prices, sizes, or symbols** outside the `user_data/config.json`. All numerical thresholds live in config or are computed from real data.
5. **No silent fallback values.** `os.getenv("BINANCE_API_KEY", "demo-key")` is forbidden. Use `os.environ["BINANCE_API_KEY"]` and let it crash loud if missing.

### When in doubt

If you're about to write `const data = [...]` or `mock_response = {...}`:

1. **Check the plan** — does it specify a real integration?
2. **Trace the data source** — where SHOULD this come from?
3. **If real source exists** — use it, full stop.
4. **If real source doesn't exist yet** — STOP, raise the blocker, do not proceed silently.
5. **Never** choose "use placeholder with TODO" without explicit operator approval via `AskUserQuestion`.

### Data classification

| Source | Verdict |
|---|---|
| `useWorkspace()`, Postgres query via SQLAlchemy, CCXT call, env var via `os.environ[...]` | ✅ Real |
| `[]` empty array waiting for API | ❌ Placeholder |
| `{ id: 1, symbol: 'BTC' }` hardcoded sample | ❌ Placeholder |
| `os.getenv("X", "default-value")` with non-empty default | ❌ Placeholder (silent fallback) |
| `Math.random()` for fake data | ❌ Placeholder |
| Test fixture inside `tests/` | ✅ Real (test-only) |

---

## Debugging Checklist

Before claiming a bug is fixed, verify in this order:

1. **Reproduce locally** — confirm the bug actually happens with current code on your machine. If can't reproduce → not a bug, gather more info.
2. **Check logs** — `journalctl --unit=freqtrade.service`, `journalctl --unit=pulse-bridge.service`, `journalctl --unit=dashboard-api.service`. Most failures are loud in logs.
3. **Check Postgres state** — `psql trading -c "SELECT * FROM brain_journal ORDER BY ts DESC LIMIT 20"`. Reasoning + outcome usually reveal the cause.
4. **Check FreqUI / Bot Cockpit** — open positions, equity curve, recent trades. Visual inspection often spots regime issues fast.
5. **Check Telegram archive** — daily summaries reveal multi-day drift.
6. **Reproduce in backtest** — if possible, replay the failure window through `freqtrade backtesting --timerange <window>`. Bugs that survive backtest replay are deterministic; bugs that don't are likely live-only (slippage, partial fill, ws gap).
7. **Reproduce in dry-run** — switch to `dry_run: true` against live ws. Bugs that survive dry-run are pure logic; bugs that don't involve real exchange behavior.
8. **Check API key state** — has rotation expired? Permission revoked? IP-allowlist mismatch?
9. **Check Tailscale state** — `tailscale status`. UI access bugs often originate here.
10. **Don't fix until you understand** — reproducing reliably > fixing fast. A non-reproducing fix usually means you've masked the symptom.

### Common failure modes (so far — grow this list)

*(Empty initially — populated as we encounter and resolve real bugs in subsequent phases.)*

---

## Iron Laws

These are non-negotiable and architecturally enforced. **No code change, plan revision, or "just this once" rationalization overrides them.**

### Iron Law 1: Claude cannot override risk rails

The following are hard-coded in `freqtrade-fork/user_data/config.json` + protection classes, in a separate process from Claude:

- Max position size: 25% of equity per trade
- Max concurrent positions: 3
- Daily loss circuit breaker: −5% equity → halt 24h
- Per-trade stop-loss: 2× ATR(14) trailing
- Max drawdown kill switch: −20% from peak → liquidate all + halt indefinitely
- API key rotation: every 30 days, automated

Claude can VETO a trade. Claude can RESIZE within the cap. Claude **cannot** DISABLE a circuit breaker, EXTEND a position size limit, or RESET a kill switch. These actions require operator manual edit + restart.

### Iron Law 2: No live trade without backtest + paper-trade sign-off

- **Phase 9 (walk-forward backtest)** — all 4 gate criteria must pass in **all 5 OOS folds**: Sharpe > 1.5, MaxDD < 25%, profit factor > 1.4, ≥100 trades per fold.
- **Phase 10 (paper trade)** — 3–4 weeks live data, fake money. PnL drift vs backtest expectation < 30%, zero risk-rail breaches, slippage observed within 2× backtest assumption.
- **Phase 12 (live $100)** — 4 weeks observation with weekly drift gate.

If a phase fails → **Phase 9.5 Iteration Loop** (max 3 cycles). After 3 fails → architectural rethink ADR. **No silent advance.**

### Iron Law 3: No placeholder data in production code paths

See "Anti-Placeholder Rules" above. This is not a style preference; it is a capital-protection requirement. A fake data path that runs against real money is the textbook crypto bot failure mode.

### Iron Law 4: Claude must not modify its own discipline files

`claude-routines/skills/trading-discipline.md` is **read-only by convention**. Claude has the file-write tool but must never auto-edit this file. Operator-only edits, with ADR.

The same applies to:

- `freqtrade-fork/user_data/config.json` (risk rail values)
- `infra/migrations/*.sql` (schema constraints)
- This file (`CLAUDE.md`)

If Claude detects an opportunity to "improve" any of these autonomously — STOP, raise to operator via Telegram, wait.

### Iron Law 5: Memory grows append-only

The `brain_journal` Postgres table has `INSERT, SELECT` grants only — `UPDATE` and `DELETE` are explicitly REVOKED at migration time. The `claude-routines/memory/*.md` files are append-only by convention; Claude may add new entries but must not rewrite or delete past lessons. This makes the audit log tamper-evident.

---

## Conventions

### Naming

- Python modules: `snake_case` (e.g., `binance_vision.py`, `gap_detector.py`, `pattern_detector.py`)
- Python classes: `PascalCase` (e.g., `ClaudeOversightStrategy`, `DailyLossCircuitBreaker`)
- TS/TSX components: `PascalCase` files matching component name (e.g., `LiveChart.tsx` exports `LiveChart`)
- TS/TSX hooks: `useCamelCase.ts` (e.g., `useLiveOhlcv.ts`)
- SQL migrations: `NNN_short_description.sql` zero-padded 3-digit (e.g., `001_ohlcv_hypertable.sql`)
- ADR files: `YYYY-MM-DD-NNN-short-slug.md` under `docs/decisions/`
- Skills: `kebab-case.md` under `claude-routines/skills/`

### Commit messages

Conventional Commits style: `feat(scope): description` / `fix(scope): description` / `chore(scope): description` / `docs(scope): description`. Scope = component name (e.g., `feat(strategy):`, `feat(ui):`, `chore(infra):`).

Sign Co-Authored-By line at end of every Claude-assisted commit message.

### Test files

- Unit tests next to source where helpful, OR mirrored under `tests/` for cross-component tests
- Integration tests under `tests/integration/`, marked `@pytest.mark.integration`, require real Postgres + Telegram
- E2E (UI) under `dashboard-ui/playwright/`
- All tests use real services where the plan specifies real integration. Mocks only in test fixtures, never in production code paths.

### Secrets

- Stored in `.env` (root or per-component), never committed
- Loaded via `os.environ[...]` (raises if missing — preferred over silent fallback)
- systemd units use `LoadCredential=` not direct `EnvironmentFile=`
- API key rotation cron lives in `infra/scripts/api_key_rotation.sh`

---

## Workflow

| Step | Skill |
|---|---|
| Idea exploration | `gaspol-brainstorm` |
| Plan authoring | `gaspol-plan` |
| Implementation | `gaspol-execute` (you are reading this during execution) |
| Verification | `gaspol-verify`, `plan-verifier` agent |
| Doc sync | `gaspol-sync-docs` |
| Code review | `gaspol-review` (auto-dispatches `code-reviewer` agent for non-trivial phases) |
| Architectural decisions | `gaspol-adr` |
| Debugging | `gaspol-debug` |
| Completion | `gaspol-finish` |

---

## Quick reference

- **Plan:** [`docs/plans/2026-05-06-ai-trading-247.md`](docs/plans/2026-05-06-ai-trading-247.md)
- **NLM research report:** [`docs/research/2026-05-06-nlm-runtime-decision-report.md`](docs/research/2026-05-06-nlm-runtime-decision-report.md)
- **NotebookLM notebook:** alias `ai-trading-research` (84 sources)
- **Operator:** Ali Sadikin (`ali.sadikincom85@gmail.com`)
- **Deployment target:** Hetzner CX22 Frankfurt
- **First-live capital:** $100 (Phase 12)
