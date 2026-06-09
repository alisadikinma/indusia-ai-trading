# CLAUDE.md — AI Trading 24/7

> **Read this first, every session.** This is the operational contract for working on this codebase.

## 🕸️ graphify (code-structure brain — HOW)

This repo has a knowledge graph at `graphify-out/` (god nodes, community structure, cross-file relationships) — the **HOW (code structure)** half of the two-brain setup in `~/CLAUDE.md` (the Obsidian vault holds the WHY).

**Rules:**
- **Graph for structure, grep for literals — complementary, not either/or.** Use `graphify query "<question>"` for "where/how is X / what calls Y / which files relate" — it returns a scoped subgraph, far smaller than `GRAPH_REPORT.md` or raw output (local default `graphify-out/graph.json`). Keep grep/Read for literal strings AND code edited since the last `graphify update` (the graph is AST-indexed, not live).
- Cross-project / "don't know which repo" → federated graph: `graphify query "<question>" --graph ~/.graphify/global-graph.json`.
- Read `graphify-out/GRAPH_REPORT.md` only for broad architecture review when query doesn't surface enough.
- **After modifying code, run `graphify update .`** (AST-only, no API cost) so the graph doesn't go stale. Refresh the global brain: `graphify global add graphify-out/graph.json --as AI-Trading`.

This file is loaded automatically by Claude Code CLI at the start of every session. It encodes the architecture, conventions, anti-placeholder rules, and Iron Laws that govern this project. The full design + 16-phase implementation plan lives in [`docs/plans/2026-05-06-ai-trading-247.md`](docs/plans/2026-05-06-ai-trading-247.md) — read that for context on **why**; this file is **how**.

This is a **mono-repo for two trading bots** per [ADR-001](docs/decisions/2026-05-07-001-mono-repo-multi-bot.md): `crypto-bot/` (Binance + Blofin via Freqtrade body, schema `brain.*`) and `polymarket-bot/` (Polymarket via py-clob-client body, schema `polymarket.*`). The `references/` RAG layer per [ADR-002](docs/decisions/2026-05-07-002-references-rag-layer.md) is a fifth knowledge surface beyond skills/memory/journal/ML, injected per cycle via `--append-system-prompt-file`.

---

## 🧠 Vault Context Link

Pre-read via `obsidian` MCP `search-vault` saat butuh konteks lintas-sesi (e.g., "what did we decide about Blofin", "last regime classifier outcome").

Reference shared:
- `10-Identity/ali.md` — voice & risk tolerance (auto-loaded)
- `10-Identity/tech-preferences.md` — stack decisions
- `30-Knowledge/` — search topical: trading, backtest, ADR history

Belum ada vault folder `20-Projects/AI-Trading/`. Kalau ada decision atau insight penting (regime call, ADR change, postmortem), propose ke user buat README di sana via `obsidian` MCP `create-note`.

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
┌────────────────────────────────────────────────────────────────────────┐
│  VPS Hetzner CX22 — Frankfurt EU                                        │
│                                                                          │
│  Claude Code CLI (oversight brain) ──── 5-min Routines per bot           │
│         │                                                                │
│         │ HMAC-signed JSON over Unix socket  +  --append-system-prompt-  │
│         │ file references/<bot>/compiled/refs-<bot>-decision.md (RAG)    │
│         ▼                                                                │
│  pulse-bridge/ (FastAPI: /v1/crypto/*, /v1/polymarket/*, /dashboard/*)   │
│         │                                ▲                               │
│         ▼                                │ Tailscale + JWT                │
│  ┌──────────────────┐    ┌──────────────────┐   dashboard-ui/ (Next.js,  │
│  │ crypto-bot/       │    │ polymarket-bot/   │   bot switcher tab)       │
│  │ freqtrade-fork/   │    │ clob-client/      │                          │
│  │ CCXT → Binance    │    │ py-clob-client →  │                          │
│  │      + Blofin     │    │   Polymarket CLOB │                          │
│  └──────────────────┘    └──────────────────┘                            │
│         │                          │                                     │
│         ▼                          ▼                                     │
│  Postgres 16 + TimescaleDB (one host, schema-isolated):                  │
│    brain.*       ← crypto-bot (legacy schema name kept per ADR-001)      │
│    polymarket.*  ← polymarket-bot                                        │
│         │                                                                │
│         ▼                                                                │
│  Telegram bot (alerts + HMAC kill-switch, shared)                        │
└────────────────────────────────────────────────────────────────────────┘
```

**The brain knows 5 things** (Claude Code CLI knowledge anatomy, post-ADR-002):

1. **Skills** (`<bot>/claude-routines/skills/*.md`) — static rule playbook, read every cycle: `regime-detection.md`, `signal-evaluation.md`, `trading-discipline.md`, `known-traps.md`, `post-mortem-protocol.md`, `pattern-detector.md`, `backtest-diagnostics.md` (crypto). Polymarket adds `oracle-dispute-protocol.md`, `news-velocity-playbook.md`.
2. **Memory** (`<bot>/claude-routines/memory/*.md`) — accumulated wisdom from THIS bot's portfolio: `lessons-learned.md`, `strategy-performance.md`, `operator-preferences.md`, `recent-regime-history.md`. Grown by post-mortem cron weekly. Per-bot.
3. **Journal** (Postgres `<schema>.brain_journal` table, append-only — `brain.*` for crypto, `polymarket.*` for polymarket) — every past decision with reasoning + outcome. Iron Law 5 enforced via trigger raising SQLSTATE 42501 on UPDATE/DELETE.
4. **ML priors** — crypto: FreqAI XGBoost from 5–10y OHLCV, auto-retrains daily. Polymarket: TBD calibration-tuned probabilistic forecaster (Phase 9+ of forthcoming polymarket plan).
5. **References** (`references/`, RAG layer per ADR-002) — external grounded research distilled from NotebookLM. Compiled `refs-<bot>-decision.md` (≤8K tokens) injected into every cycle via `--append-system-prompt-file`. Operator-curated; Iron Law 4 read-only at runtime.

**The body** is per-bot: `freqtrade-fork/` (crypto) handles CCXT order placement + risk + backtest; `polymarket-bot/clob-client/` (polymarket) wraps py-clob-client. Claude **never** writes trading code autonomously — strategy logic changes require human design with Claude as analyst.

---

## Key Directories

| Path | Owner | Purpose |
|---|---|---|
| [`crypto-bot/`](crypto-bot/) | Crypto bot | Per-bot brain artifacts (`claude-routines/skills/`, `memory/`, `routines/`) + Freqtrade strategy/config (`freqtrade-config/`). Reads/writes Postgres `brain.*` schema. Body submodule lives at `../freqtrade-fork/` (root, per ADR-001). |
| [`polymarket-bot/`](polymarket-bot/) | Polymarket bot | Per-bot brain artifacts + py-clob-client wrapper (`clob-client/`) + strategies (`strategies/`). Reads/writes Postgres `polymarket.*` schema. Currently SKELETON ONLY (forthcoming separate plan). |
| [`freqtrade-fork/`](freqtrade-fork/) | Crypto body | Git submodule pointing at github.com/freqtrade/freqtrade. Logically owned by `crypto-bot/` but kept at repo root per ADR-001 (rewrite-cost > benefit). **Do not edit Freqtrade core**; only `user_data/`. |
| [`pulse-bridge/`](pulse-bridge/) | Bridge | Shared FastAPI shim. Routes: `/v1/crypto/*` and `/v1/polymarket/*` for brain↔body, `/dashboard/*` for UI. HMAC contract identical across bots. |
| [`dashboard-ui/`](dashboard-ui/) | UI | Next.js 15 App Router. TradingView Lightweight Charts v5. Tailscale-only access. Top-nav bot switcher routes between crypto and polymarket views. |
| [`infra/`](infra/) | Ops | `docker-compose.yml` (Postgres only), `migrations/*.sql` (brain + polymarket schemas), `systemd/*.service`, `data_loader/*.py` (Binance Vision + CoinDesk for crypto; polymarket source TBD), `scripts/*.py` (post-mortem cron, retrain, walk-forward, chaos test, `compile_refs.py` for the references layer). |
| [`references/`](references/) | RAG layer | The fifth brain knowledge surface per ADR-002. Per-bot subfolders (`crypto/`, `polymarket/`) + `shared/` (walk-forward, Kelly, oversight pattern) + `global-trading-config.md` (Iron Laws + JSON contract + precedence). Compiled `refs-<bot>-decision.md` (≤8K tokens) injected per cron cycle. **Operator-curated only** (Iron Law 4 extension). |
| [`tests/`](tests/) | All | Pytest. Real services in integration tests (mocks only here, not in production code). Markers: `@pytest.mark.integration` requires real Postgres + Telegram. |
| [`docs/`](docs/) | All | `plans/` (16-phase crypto plan; multi-bot restructure plan), `research/` (NotebookLM artifacts), `decisions/` (ADRs from `gaspol-adr`, including ADR-001 mono-repo and ADR-002 references layer). |

---

## Multi-Bot Boundaries

Per [ADR-001](docs/decisions/2026-05-07-001-mono-repo-multi-bot.md), this repo houses two bots side by side. Boundaries:

**Shared (cross-bot, root-level):**

- `pulse-bridge/` — single FastAPI app with multi-router (`/v1/crypto/*`, `/v1/polymarket/*`, `/dashboard/*`). Brain↔body HMAC contract identical across bots.
- `dashboard-ui/` — single Next.js cockpit with top-nav switcher between bots. The 5 views (Live, Strategy Lab, Brain Journal, FreqAI Insights, Iteration History) clone per asset class.
- `infra/` — one Postgres host, one Telegram bot, one VPS, one systemd unit family (`<bot>-freqtrade.service`, `<bot>-routine.timer`, etc.).
- `references/global-trading-config.md` and `references/shared/` — cross-bot invariants (Iron Laws, JSON contract, walk-forward methodology, Kelly criterion, oversight pattern).
- `freqtrade-fork/` submodule — at repo root despite being crypto-only, per ADR-001 (rewrite-cost > benefit).

**Per-bot (under `crypto-bot/` or `polymarket-bot/`):**

- `<bot>/claude-routines/{skills,memory,routines}/` — bot-specific decision rules and learned wisdom.
- `<bot>/freqtrade-config/` (crypto only) or `<bot>/clob-client/`, `<bot>/strategies/` (polymarket).
- `references/<bot>/` — bot-specific reference content (microstructure, regime taxonomy, failure modes).

**Postgres schema isolation (schema-level, NOT database-level):**

- `brain.*` — crypto bot. Legacy schema name kept per ADR-001 (renaming would force migration churn at zero functional benefit).
- `polymarket.*` — polymarket bot. Canonical bot-named forward.
- `public.*` — Freqtrade ORM (auto-creates `trades`, `pairlocks` at first run).
- Future bots use their own bot-named schema (`<bot>.*`), NOT `brain.*`. Naming asymmetry is documented and tolerated; do NOT rename `brain` retroactively.

**Risk budgeting across bots:**

- Daily loss circuit breaker (-5%) and max drawdown kill switch (-20%) apply to **total equity ACROSS bots**, not per-bot.
- Max concurrent positions cap is per-bot (3 each) AND additionally constrained by total-portfolio risk budget.
- Phase 12 live-capital decision: split between bots only AFTER each has independently passed paper trade.

---

## References Layer

Per [ADR-002](docs/decisions/2026-05-07-002-references-rag-layer.md), the brain has a fifth knowledge surface: external grounded research distilled from NotebookLM into `references/`.

**Precedence order (when sources conflict at runtime):**

1. **Iron Laws** — non-negotiable, architecturally enforced. Cannot be overridden by ANY other source.
2. **Skills** (`<bot>/claude-routines/skills/*.md`) — operator-curated rules for THIS portfolio.
3. **References** (`references/`) — external grounded knowledge. Override training data and memory. CANNOT override skills or Iron Laws.
4. **Memory** (`<bot>/claude-routines/memory/*.md`).
5. **Training data** — fallback only.

If references contradict skills/Iron Laws at runtime, brain MUST: (a) abstain (default veto), (b) log conflict to `<schema>.brain_journal` with `decision='halt'`, (c) Telegram alert for operator review. Never silently resolve.

**Inject mechanism:** every routine cron invocation appends the compiled per-bot decision file to the system prompt:

```
claude --append-system-prompt-file references/<bot>/compiled/refs-<bot>-decision.md \
       --skill <routine-skill-name> ...
```

The compiled file (`infra/scripts/compile_refs.py`) is built by deliberate selection — Quick Decision Heuristics + first paragraph per topic from each source reference. Hard cap 8K tokens; script fails loud if exceeded. Token cost ~$30/bot/month at Sonnet 4.6 with 5-min prompt cache.

**Update workflow:** NotebookLM research → `nlm notebook query` → operator hand-distills → commit source ref + recompiled decision file. Human-in-the-loop, NOT a cron job (Iron Law 4 extension — see below).

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

`<bot>/claude-routines/skills/trading-discipline.md` is **read-only by convention** (applies per-bot). Claude has the file-write tool but must never auto-edit this file. Operator-only edits, with ADR.

The same applies to:

- `crypto-bot/freqtrade-config/config.json` (crypto risk rail values)
- Polymarket position-sizing config (`polymarket-bot/clob-client/config.json` once written)
- `infra/migrations/*.sql` (schema constraints, including `003_polymarket_schema.sql`)
- `infra/postgres/init.sql` (schema bootstrap + grants)
- `references/` and all subfolders (per ADR-002 extension — references are operator-curated; auto-edits would defeat citation discipline)
- This file (`CLAUDE.md`)
- All `docs/decisions/*.md` (ADRs are immutable once accepted; supersede via new ADR, not edit)

If Claude detects an opportunity to "improve" any of these autonomously — STOP, raise to operator via Telegram, wait.

### Iron Law 5: Memory grows append-only

The `brain_journal` Postgres tables in BOTH `brain.*` and `polymarket.*` schemas have triggers that REJECT `UPDATE` and `DELETE` (raise SQLSTATE `42501` insufficient_privilege). Verified in `tests/integration/test_schemas_bootstrap.py` (crypto) and `tests/integration/test_polymarket_schema.py` (polymarket). The `<bot>/claude-routines/memory/*.md` files are append-only by convention; Claude may add new entries but must not rewrite or delete past lessons. This makes the audit log tamper-evident.

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

## Model Routing

Auto-switch Claude model based on task effort. Three tiers, concrete criteria — no "use judgement".

### Tier matrix

| Tier | Model ID | Best for | Cost ratio (vs Haiku) |
|---|---|---|---|
| **HEAVY** | `claude-opus-4-7` | Architectural reasoning, cross-domain debugging, capital-at-stake decisions | ~18× |
| **STANDARD** | `claude-sonnet-4-6` | Default phase work, code review, post-mortem analysis | ~4× |
| **LIGHT** | `claude-haiku-4-5-20251001` | Lookups, single-file edits, cron summaries, structured outputs | 1× |

### Decision rules — pick exactly one tier per task

Use **HEAVY (Opus 4.7)** when ANY of:
- Cross-file refactoring touching ≥3 files OR ≥300 LoC
- Architectural decision requiring an ADR
- Phase 9.5 iteration loop diagnosis (failed backtest postmortem)
- Capital-at-stake live trade decision (Phase 12+ emergency vetoes)
- Strategy v2+ redesign or feature engineering for new ML inputs
- Debugging a heisenbug that survived dry-run + backtest
- Cross-bot reasoning (crypto + polymarket interaction)

Use **STANDARD (Sonnet 4.6)** when (default tier):
- Single-phase implementation per gaspol-execute (one phase = one Sonnet subagent)
- Code review of a single phase's diff (`code-reviewer` agent)
- Weekly post-mortem cron (Phase 6 — deep regime analysis on losing trades)
- Standard 5-min oversight routine (reads context, judges regime, decides)
- Test writing (TDD step 1 → fail → step 3 implement)
- Schema migration authoring
- Skill or routine markdown authoring
- Plan-verifier audit

Use **LIGHT (Haiku 4.5)** when ALL of:
- Single file edit ≤50 LoC OR pure lookup
- No cross-domain reasoning needed
- Output is structured (JSON, table row, lint check, summary line)
- Latency or token cost dominates value

Specifically: daily retrain health check, log line summarization, commit-message generation from diff, gap-detector report formatting, shadcn primitive scaffolding from a known pattern, file-existence assertions in tests.

### Routine-specific routing

Per-cycle model is declared in the routine spec's frontmatter:

| Routine | Cadence | Model |
|---|---|---|
| `crypto-bot/claude-routines/routines/oversight-loop.md` | every 5 min | **STANDARD** |
| `crypto-bot/claude-routines/routines/weekly-postmortem.md` | Sunday 00:00 UTC | **STANDARD** |
| `infra/scripts/retrain_health_check.py` (Claude analysis on amber/red) | daily 06:00 UTC | **LIGHT** |
| Phase 9.5 iteration diagnosis (`backtest-diagnostics.md` skill invocation) | conditional on Phase 9 fail | **HEAVY** |
| Capital-at-stake live emergency review (Phase 12+) | on circuit-breaker trigger | **HEAVY** |

### How to invoke each tier

**Interactive Claude Code session** — operator switches mid-session:
```
/model opus     # → HEAVY
/model sonnet   # → STANDARD (default)
/model haiku    # → LIGHT
```

**Non-interactive cron / subprocess** — explicit `--model`:
```bash
# HEAVY
claude --model claude-opus-4-7 -p "<prompt>"
# STANDARD (default if --model omitted, but be explicit)
claude --model claude-sonnet-4-6 -p "<prompt>"
# LIGHT
claude --model claude-haiku-4-5-20251001 -p "<prompt>"
```

**Sub-agent dispatch via Agent tool** — declare in `model` parameter:
```
Agent({
  description: "...",
  subagent_type: "general-purpose",
  model: "opus",     // or "sonnet" or "haiku"
  prompt: "..."
})
```

If `model` is omitted, the parent agent's tier is inherited.

**gaspol-execute phase dispatch** — when dispatching implementer subagents:
- Default: Sonnet (per gaspol-parallel skill convention)
- Heavy phases (Phase 9.5 iteration, Phase 13 architectural rethink): explicitly request Opus
- Light phases (UI sub-blocks 1.5.H polish, 1.5.I auth hardening): consider Haiku if scope is mechanical

### Cost guardrail

Estimated monthly token spend at current architecture (24/7 ops):
- Oversight loop (Sonnet, 288 cycles/day × 4K tokens) ≈ $20/month
- Weekly postmortem (Sonnet, 4 runs × 30K tokens) ≈ $1/month
- Retrain health check (Haiku, 30 runs × 2K tokens) ≈ $0.10/month
- Phase 9.5 iteration (Opus, conditional, ~5 runs × 60K tokens) ≈ $5/iteration

Total expected: **~$25–35/month per bot** at full operation. Operator's Claude Code Max plan covers most interactive work.

If a single tier's budget exceeds 2× the projection, alert via Telegram (Phase 6 retrain-health pattern; expand the cron in Phase 8+ to include token telemetry).

### When in doubt

Default to **STANDARD (Sonnet)**. Then:
- If tests fail or output drifts → escalate to HEAVY (Opus) and re-run
- If output is repetitive/formulaic and Sonnet is overkill → drop to LIGHT (Haiku) on the next attempt

Never default to HEAVY for routine work — token cost compounds quickly at 24/7 cadence.

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
