# crypto-bot/

Autonomous Claude-overseen crypto trading agent — Binance (spot + futures) and
Blofin (perp) via CCXT through a forked Freqtrade body. This is one of two
bots that share the AI-Trading mono-repo per
[`docs/decisions/2026-05-07-001-mono-repo-multi-bot.md`](../docs/decisions/2026-05-07-001-mono-repo-multi-bot.md);
its sibling is [`polymarket-bot/`](../polymarket-bot/).

## What lives here

| Path | Purpose |
|---|---|
| `claude-routines/` | Brain artifacts for THIS bot — skills (`*.md` playbook), memory (`*.md` learned wisdom), routines (cron specs). Currently empty; populated in Phase 5+ of the original plan. |
| `freqtrade-config/` | Freqtrade `config.json` + custom strategies (`ClaudeOversightStrategy.py` and friends). Parent-tracked because Freqtrade upstream gitignores `user_data/`. |

## What lives ELSEWHERE (shared infra, mono-repo)

| Path | Why shared |
|---|---|
| [`../freqtrade-fork/`](../freqtrade-fork/) | Git submodule pointing at github.com/freqtrade/freqtrade. Logically owned by THIS bot but kept at repo root because rewriting `.gitmodules` to nest a submodule path requires every clone to re-init the submodule, with measurable risk for zero functional benefit. See ADR-001 for the rationale. |
| [`../pulse-bridge/`](../pulse-bridge/) | FastAPI shim that translates Claude oversight decisions → Freqtrade hooks. Will grow a multi-router (`/v1/crypto/*`, `/v1/polymarket/*`) once polymarket-bot lands. |
| [`../dashboard-ui/`](../dashboard-ui/) | Next.js cockpit. Will gain a top-nav switcher between bots. |
| [`../infra/`](../infra/) | Postgres, systemd units, Telegram, migrations, scripts. The crypto schema is `brain.*` (legacy name kept for stability per ADR-001); polymarket lives in `polymarket.*`. |
| [`../references/`](../references/) | Per-bot + shared knowledge layer injected into every cron cycle (ADR-002). Crypto-specific refs at `references/crypto/`. |
| [`../tests/`](../tests/) | Shared test suite. Crypto-specific tests live alongside generic ones — pytest markers and naming conventions distinguish where needed. |

## Phase status

This bot tracks the implementation plan at
[`../docs/plans/2026-05-06-ai-trading-247.md`](../docs/plans/2026-05-06-ai-trading-247.md).
At the time of writing (2026-05-07), Phases 0 (scaffold), 1 (Postgres bootstrap +
schema + dashboard scaffold), and 2 (Binance Vision bulk + live ws + gap
detector) are shipped. Phase 3 (Freqtrade strategy + Claude HMAC contract +
backtest harness) is in progress — the working tree has uncommitted
`ClaudeOversightStrategy.py` edits ahead of this README.

## Postgres schema

This bot reads/writes the `brain.*` schema:

- `brain.ohlcv` (TimescaleDB hypertable, populated by `infra/data_loader/`)
- `brain.signals` (Freqtrade strategy → Claude oversight decision)
- `brain.brain_journal` (Claude reasoning audit log, append-only per Iron Law 5)
- `brain.equity_curve`
- `brain.backtest_runs`
- `brain.iteration_runs`

The schema name `brain` is bot-specific despite its generic name — see ADR-001
for why it was kept rather than renamed to `crypto`. Future bots use a
bot-named schema (polymarket-bot uses `polymarket.*`).

## Iron Law 4 read-only files for this bot

The following files in or related to this bot must NOT be auto-edited by
Claude (Iron Law 4):

- `claude-routines/skills/trading-discipline.md` (when written in Phase 5+)
- `freqtrade-config/config.json` (risk rail values: max position, max
  concurrent, stop-loss, drawdown kill switch)
- `infra/migrations/*.sql` (schema constraints)
- The repo-root `CLAUDE.md`
- The `references/` layer (per ADR-002 extension of Iron Law 4)
