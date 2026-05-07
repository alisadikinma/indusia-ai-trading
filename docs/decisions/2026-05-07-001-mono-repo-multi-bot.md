# ADR-001 — Mono-repo Multi-Bot Architecture

## Status

Accepted — 2026-05-07. Authored by Ali Sadikin during plan
`docs/plans/2026-05-07-multi-bot-references-restructure.md` Phase A.

## Context

The AI-Trading project began as a single-bot system: a 24/7 autonomous crypto
trading agent (Binance + Blofin via CCXT through a forked Freqtrade body, with
Claude Code CLI as oversight brain). Phases 0–2 of the original plan
(`docs/plans/2026-05-06-ai-trading-247.md`) shipped against this assumption —
single `claude-routines/` folder at root, Postgres `brain.*` schema, single
`freqtrade-fork/` submodule, single dashboard cockpit.

On 2026-05-07 the operator scoped a second trading bot for **Polymarket**
prediction markets. Polymarket is a fundamentally different asset class:

- **Continuous price + OHLCV** vs **binary settlement + event resolution**.
- **CCXT/Freqtrade** vs **py-clob-client + UMA optimistic oracle**.
- **Sharpe / MaxDD / profit factor** as backtest gates vs **Brier score /
  calibration ECE / sample size per market type**.
- **Liquidity-cliff and funding-rate failure modes** vs **oracle-dispute and
  MEV-on-Polygon failure modes**.

Despite these execution-layer differences, both bots share substantial
infrastructure:

- The Claude oversight pattern (5-min cron, JSON-over-Unix-socket signal
  envelope, append-only journal).
- Postgres host + Telegram bot + Tailscale-only dashboard + systemd service
  conventions.
- The dashboard cockpit shell (Next.js App Router + TradingView Lightweight
  Charts) — only the per-bot views differ.
- Iron Laws (especially #1 hard-coded risk rails outside Claude's reach, #3
  no-placeholder-data, #5 append-only journal).

The repo structure must accommodate two bots without coupling implementation
details, while letting them share infra at runtime (one Postgres host, one
Telegram bot, one dashboard, one VPS).

## Decision

Adopt a **mono-repo with bot-as-folder structure**:

```
AI-Trading/
├── crypto-bot/                         (NEW name; was root scaffold)
│   ├── claude-routines/                (skills/memory/routines for crypto)
│   ├── freqtrade-config/               (config.json + strategies/)
│   └── README.md                       (boundary doc)
├── polymarket-bot/                     (NEW)
│   ├── claude-routines/                (skills/memory/routines for polymarket)
│   ├── clob-client/                    (py-clob-client wrapper)
│   ├── strategies/                     (polymarket strategy modules)
│   └── README.md
├── freqtrade-fork/                     (git submodule, STAYS at root — see below)
├── pulse-bridge/                       (shared FastAPI shim, multi-router)
├── dashboard-ui/                       (shared Next.js cockpit, bot switcher)
├── infra/                              (shared: postgres, systemd, scripts)
├── references/                         (shared knowledge layer — see ADR-002)
├── tests/                              (shared test suite + integration)
└── docs/{plans,decisions,research}/    (cross-cutting)
```

**Postgres schema isolation:** Schema-level separation, not database-level.

- `brain.*` — kept as the crypto bot's schema. Name preserved despite being
  bot-specific because Phase 2 just shipped against it
  (`infra/migrations/000_bootstrap_schemas.sql`,
  `infra/migrations/001_ohlcv_hypertable.sql`,
  `infra/migrations/002_pg_notify_triggers.sql`), the dashboard pg_notify
  triggers reference `brain.signals` / `brain.brain_journal` /
  `brain.equity_curve` channels by name, and the append-only Iron Law 5
  triggers are wired against `brain.brain_journal`. Renaming `brain` →
  `crypto` would force re-deploy of all three migrations + a pulse-bridge
  code refactor + dashboard channel-name updates, with measurable risk for
  zero functional benefit.
- `polymarket.*` — new schema for the Polymarket bot. Same shape (signals,
  brain_journal, equity_curve, backtest_runs, iteration_runs) plus a
  Polymarket-specific `polymarket.markets` table for market metadata
  (slug, outcomes, resolution_source, resolves_at, resolution_outcome).

**Submodule path:** `freqtrade-fork/` (git submodule pointing at
github.com/freqtrade/freqtrade) **stays at repo root**, not under
`crypto-bot/freqtrade-fork/`. Justification: moving a submodule path requires
rewriting `.gitmodules`, then every existing clone (including the production
VPS clone, if any in-flight) must `git submodule deinit && rm -rf
.git/modules/freqtrade-fork && git submodule update --init`. The disruption
cost outweighs the cosmetic benefit. Logically the submodule is "owned" by
crypto-bot — `crypto-bot/README.md` documents this and treats the root-level
submodule as an extended limb of the crypto bot.

**Naming asymmetry:** `brain.*` (crypto, legacy) + `polymarket.*` (canonical
forward). Documented in `CLAUDE.md` §Multi-Bot Boundaries. Future bots use
their own bot-named schema (`<bot>.*`), not `brain.*`. The asymmetry is
worth ≤ 60 seconds of new-engineer onboarding confusion against the cost of
the rename.

## Consequences

**Positive:**

- Single Postgres instance, single Telegram bot, single dashboard, single VPS
  → one infra surface to monitor and harden.
- Cross-cutting ADRs and references (`docs/decisions/`, `references/shared/`)
  apply to both bots automatically — Iron Laws stay singular and authoritative.
- Dashboard cockpit can route between bots via top-nav switcher; the 5
  views (Live, Strategy Lab, Brain Journal, FreqAI Insights, Iteration
  History) clone naturally per asset class.
- New-bot onboarding cost is folder-creation + schema migration, not repo
  bootstrap.

**Negative:**

- Blast radius of a misbehaving CI/build step is broader (touches both bots).
  Mitigated by per-bot test markers and per-bot deploy targets (systemd unit
  per bot, not per repo).
- Schema-naming asymmetry (`brain` vs `polymarket`) creates onboarding
  friction. Mitigated by explicit CLAUDE.md note + ADR-001 reference.
- Refactor disruption to Phase-2-just-shipped state: `git mv` of
  `claude-routines/` (empty) and `freqtrade-config/` (small, contained), plus
  pulse-bridge path-reference updates. Risk graded "low-medium" — kept
  scoped to path-only changes, no logic edits.
- Submodule-at-root violates the "everything-crypto-under-crypto-bot/"
  purity. Treated as a documented exception, not a precedent for new code.

## Alternatives Considered

**1. Separate repo `AI-Polymarket/` (rejected).**

Cleanest blast-radius isolation: Polymarket bug literally cannot break crypto
deploy. But forces duplication of: docker-compose, systemd unit conventions,
migration tooling, Telegram bot config, pulse-bridge skeleton, dashboard
shell. Worse, the dashboard would either become two URLs (operator UX
penalty) or require a federation layer (engineering cost). Operator is a
single human running both bots from one VPS — repo split optimizes for
multi-team scale that does not exist.

**2. Component-as-folder, namespace-by-prefix (rejected).**

Layout would be `claude-routines/{crypto,polymarket}/`,
`strategies/{crypto,polymarket}/`, `tests/{crypto,polymarket}/` — no
`crypto-bot/` and `polymarket-bot/` top-level folders. Argument for: maps to
how some monorepos organize by concern-not-product. Argument against:
violates the operator's stated mental model ("polymarket-bot di repo yg
sama saja hanya beda menu" — same repo, just a different menu). The
bot-as-folder model lines up with the dashboard's bot-switcher mental model
and with how systemd will deploy the bots (one unit per bot).

**3. Plugin abstraction `trading-bot-skill` (rejected as premature).**

Extract the brain-pattern (oversight-cron + journal + skills + memory) into a
reusable plugin, similar to the existing `gaspol-dev`, `linkedin-post-writer`,
`article-content-writer` plugins. Rejected because: the existing plugins are
all *workflow* plugins (they help authoring content), whereas the trading
brain is a *runtime* system that runs against capital. Mixing those
paradigms in a plugin abstraction would conflate skill content with
deployment scaffolding. Revisit only after both bots have completed paper-trade
phase (>= 4 weeks each) and the *actual* shared pattern surface has emerged
empirically. Premature abstraction risk > duplication risk at current N=2.

**4. Rename `brain.*` schema → `crypto.*` (rejected).**

Considered for naming symmetry. Rejected because the rename forces three
migration changes (the schema rename itself + trigger function bodies +
pg_notify channel names), one pulse-bridge code refactor (channel names
hard-coded in `ws_pg_listener.py`), and one dashboard refactor (subscription
channel names in the UI WS client). Risk-vs-benefit math: high churn for
zero functional gain at a moment when Phase 2 just stabilized. The naming
asymmetry is documented and tolerable.

## References

- Original crypto plan: `docs/plans/2026-05-06-ai-trading-247.md`
- This restructure plan: `docs/plans/2026-05-07-multi-bot-references-restructure.md`
- Companion ADR: `docs/decisions/2026-05-07-002-references-rag-layer.md`
- NotebookLM crypto research: notebook `14c3a70f-c265-456e-a937-9281af14cae1`
  (alias `ai-trading-research`, 84 sources)
- NotebookLM polymarket research: notebook `d3fe46b9-a3c2-4915-87c3-72c708835749`
  (alias `polymarket`, 121 sources)
- Polymarket raw research report:
  `docs/research/2026-05-07-polymarket-ai-bot-deep-research-raw.md`
- Existing migrations referenced for schema-rename rationale:
  `infra/migrations/000_bootstrap_schemas.sql`,
  `infra/migrations/001_ohlcv_hypertable.sql`,
  `infra/migrations/002_pg_notify_triggers.sql`
- Dashboard pg_notify consumer:
  `pulse-bridge/pulse_bridge/ws_pg_listener.py`
