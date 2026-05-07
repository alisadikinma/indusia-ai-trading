# 2026-05-07 — Multi-Bot Restructure + References RAG Layer

> **For Claude:** REQUIRED SKILL: Use `gaspol-execute` to implement this plan.
> **CRITICAL:** This plan specifies real integrations (NotebookLM-sourced reference
> distillation, real Postgres migration, real ADR documents). During execution,
> NEVER substitute placeholders for the reference content — if a NotebookLM source
> is unreachable or content is inadequate, STOP and ask. The references layer is
> capital-protection infrastructure (Iron Law 3 territory): a fake reference file
> shipped into cron context becomes hallucinated trading reasoning, which on a
> $100→scale account is a 100% loss vector.

## Goal

Restructure the AI-Trading repo from single-bot (crypto-only) into a **mono-repo
multi-bot architecture** that supports both `crypto-bot` (existing, Binance +
Blofin via Freqtrade fork) and `polymarket-bot` (new, prediction-market trading
via py-clob-client). Add a **`references/` RAG layer** — the missing fifth
knowledge surface — that injects distilled NotebookLM research into every
oversight-brain cycle via `--append-system-prompt-file`, enabling
citation-traceable, grounded reasoning instead of training-data drift.

This plan does **not** implement the polymarket-bot itself (separate plan
forthcoming, mirroring the 16-phase crypto plan with Polymarket-specific gates:
Brier score, calibration ECE, oracle-dispute drills). This plan scopes only the
*structural* groundwork that lets two bots co-exist + the *knowledge layer*
that grounds both.

## Architecture Context

**Pulled from `CLAUDE.md` + repo audit (2026-05-07):**

- **Postgres schema:** `brain.*` exists with 6 tables (ohlcv, signals,
  brain_journal, equity_curve, backtest_runs, iteration_runs). Append-only
  triggers on `brain.brain_journal` enforce Iron Law 5 (`infra/migrations/000_bootstrap_schemas.sql:137-156`).
  pg_notify triggers wire `brain.signals` / `brain.brain_journal` /
  `brain.equity_curve` to dashboard WS via `pulse-bridge/pulse_bridge/ws_pg_listener.py`
  (see `infra/migrations/002_pg_notify_triggers.sql`).
- **Existing folders:** `claude-routines/` (empty — skills not yet written, that's
  Phase 5+ of the original plan), `freqtrade-fork/` (git submodule), `freqtrade-config/`,
  `pulse-bridge/` (FastAPI shim, currently the brain↔body bridge), `dashboard-ui/`
  (Next.js cockpit, Phase 1.5.A done), `infra/{data_loader,migrations,scripts,...}`,
  `tests/test_repo_structure.py` (existing repo-baseline test).
- **Phase status:** Plan `docs/plans/2026-05-06-ai-trading-247.md` Phase 0–2 done
  (scaffold, infra, data ingest). Phase 3+ (strategy, paper-trade, etc.) not yet
  started.
- **NotebookLM research:** Two notebooks ready:
  - Crypto: `14c3a70f-c265-456e-a937-9281af14cae1` (84 sources) — alias
    `ai-trading-research`.
  - Polymarket: `d3fe46b9-a3c2-4915-87c3-72c708835749` (121 sources) — alias
    `polymarket`. Raw report saved at
    `docs/research/2026-05-07-polymarket-ai-bot-deep-research-raw.md` (59KB).

**Key reusable infra:**

- `nlm` CLI (NotebookLM) for source extraction. Auth already wired.
- `tests/test_repo_structure.py` for asserting folder/file existence —
  extend, don't duplicate.
- `infra/migrations/` for Postgres DDL — additive numbering convention `NNN_*.sql`.
- `gaspol-adr` skill for ADR authoring (auto-formats MADR sections).

**Key constraint:**

- `freqtrade-fork/` (submodule) **stays at repo root** despite being crypto-only.
  Reason: moving a submodule path requires `.gitmodules` rewrite + every clone
  re-init. Risk > benefit for Phase 2-just-shipped state. Document in ADR-001
  as conscious deviation from "all-crypto-files-under-crypto-bot/" purity.

## Tech Stack

- **ADRs:** MADR format (Markdown Architecture Decision Records), authored via
  `gaspol-adr` skill. Stored in `docs/decisions/YYYY-MM-DD-NNN-slug.md`.
- **References:** Plain markdown, ASCII-friendly headings, target token budget
  ≤ 8K per compiled `refs-*-decision.md`.
- **Distillation:** Manual curation from NotebookLM reports via `nlm download
  report <nb-id>` + per-topic `nlm research start --notebook-id <id>` followups.
  Distillation done in foreground with `Read` + `Write` (NOT subagent — tone +
  citation discipline matters more than parallelism for this content).
- **Postgres:** Additive migration `003_polymarket_schema.sql` — mirrors
  `brain.*` schema as `polymarket.*` schema (same tables, same constraints, same
  triggers, schema-level grants). Existing `brain.*` schema STAYS NAMED `brain`
  for backwards-compat — explicit ADR rationale.
- **Cron inject:** Shell wrapper `claude --append-system-prompt-file
  references/<bot>/compiled/refs-<bot>-decision.md` — added to routine spec
  template at `crypto-bot/claude-routines/routines/_template.md` (placeholder; routines
  themselves get written in Phase 5+ per original plan).

## Data Integration Map

| Feature | Data Source | Hook/API | Exists? | Action |
|---|---|---|---|---|
| ADR-001 (mono-repo decision) | hand-authored via `gaspol-adr` | n/a | No | Create (writes to `docs/decisions/2026-05-07-001-*.md`) |
| ADR-002 (references layer architecture) | hand-authored via `gaspol-adr` | n/a | No | Create |
| `crypto-bot/freqtrade-config/` | move of existing `freqtrade-config/` | filesystem | Yes (current path) | `git mv` to new path |
| `crypto-bot/claude-routines/` | move of existing empty `claude-routines/` | filesystem | Yes (empty) | `git mv` to new path |
| `polymarket-bot/{claude-routines,clob-client,strategies}/` | new skeleton folders | filesystem | No | Create empty + README placeholders |
| `polymarket.*` Postgres schema | new migration `003_polymarket_schema.sql` | psql via `infra/postgres` | No | Create migration (mirrors `brain.*` 6 tables + Iron Law 5 triggers) |
| `references/global-trading-config.md` | distill from CLAUDE.md Iron Laws + brain JSON contract from `docs/plans/2026-05-06-ai-trading-247.md` | `Read` source files, `Write` refs | No | Distill from existing in-repo content |
| `references/crypto/*.md` (4 files) | NotebookLM `14c3a70f-c265-456e-a937-9281af14cae1` (84 sources) | `nlm research status --full` + `nlm notebook query` for per-topic deep dive | Yes (notebook) | Query NotebookLM, distill to markdown |
| `references/polymarket/*.md` (5 files) | NotebookLM `d3fe46b9-a3c2-4915-87c3-72c708835749` (121 sources) + saved report `docs/research/2026-05-07-polymarket-ai-bot-deep-research-raw.md` | `Read` + `nlm notebook query` | Yes (notebook + raw report) | Distill from raw report + targeted queries |
| `references/shared/*.md` (3 files) | NotebookLM crypto + general training distillation | `nlm notebook query` for walk-forward, Kelly | Yes (notebook content) | Distill |
| `references/<bot>/compiled/refs-<bot>-decision.md` | concat curated subset of bot-specific + shared refs | local Python `infra/scripts/compile_refs.py` (NEW) | No | Create script + run |
| `crypto-bot/claude-routines/routines/_template.md` | new template with `--append-system-prompt-file` flag wired | hand-authored | No | Create |
| Updated `CLAUDE.md` (multi-bot contract + references precedence) | hand-edited extension | `Edit` | Yes (single-bot version) | Edit in place |
| Updated `tests/test_repo_structure.py` | add assertions for new paths | `Edit` | Yes | Edit in place |

**Real-integration verdict per row:**
- Existing data sources (NotebookLM notebooks, Postgres `brain.*`, in-repo files):
  use directly, no mocks.
- New artifacts: created as real, citation-traceable content. **No "TODO: fill
  in later" placeholders.** A reference file with thin/placeholder content is
  treated as a phase failure — re-query NotebookLM, re-distill, until the file
  meets the verification criteria.

## Anti-Placeholder Contract (project-specific addendum)

Per `CLAUDE.md` §Anti-Placeholder Rules, the following are forbidden in this
plan's deliverables:

1. Reference files with `[TODO: research this]` or `[Lorem ipsum]` content.
2. Compiled `refs-*-decision.md` that just concatenates without curation —
   compiled file MUST drop ≥ 30% of source character count via deliberate
   selection (signal vs noise).
3. ADR with empty `## Consequences` or `## Alternatives Considered` sections.
4. Migration `003_polymarket_schema.sql` that copies `brain.*` DDL via `\copy`
   metacommand without explicit re-typing — trigger functions reference schema
   names hard-coded; copy-paste-rename WILL silently break.
5. Polymarket-bot folder skeleton with empty `README.md` — README must state
   the planned phase rollout (mirroring crypto's 16-phase plan, Polymarket-adapted).

If any of the above occurs, STOP and surface to operator before continuing.

## Phase Overview

| Phase | Title | Estimated time | Parallelizable? |
|---|---|---|---|
| A | ADR-001 — Mono-repo multi-bot decision | 15 min | No |
| B | ADR-002 — References RAG layer architecture | 15 min | No |
| C | Refactor existing → `crypto-bot/` (path moves) | 10 min | No (foundation for D, E) |
| D | Polymarket-bot folder skeleton | 10 min | After C |
| E | Postgres `polymarket.*` schema migration | 20 min | After C |
| F | References folder scaffold + `global-trading-config.md` | 15 min | After C |
| G | Distill `references/crypto/*.md` (4 files) | 60 min | Sequential within phase |
| H | Distill `references/polymarket/*.md` (5 files) | 75 min | Sequential within phase, but H can run after F (parallel with G) |
| I | Distill `references/shared/*.md` (3 files) | 45 min | After F (parallel with G, H) |
| J | Compile `refs-<bot>-decision.md` (token budget ≤ 8K) | 20 min | After G + H + I |
| K | Update `CLAUDE.md` to multi-bot + references precedence | 20 min | After A–J |
| L | Wire `--append-system-prompt-file` into routine template | 15 min | After F + K |

**Total estimate: ~5 hours** (with G, H, I parallelizable in `gaspol-parallel`
mode if separate Claude sessions are used; sequential in single-session ≈ 5 h).

---

## Phase A — ADR-001: Mono-repo Multi-Bot Decision

**Estimated time:** 15 min

**Files:**
- Create: `docs/decisions/2026-05-07-001-mono-repo-multi-bot.md`
- Test: `tests/test_repo_structure.py` (extend with ADR file existence + section presence assertion)

**Steps:**
1. Write failing test: extend `tests/test_repo_structure.py` with
   `test_adr_001_exists_with_madr_sections()` — asserts file exists at
   `docs/decisions/2026-05-07-001-mono-repo-multi-bot.md` AND contains the 6
   MADR sections (`## Status`, `## Context`, `## Decision`, `## Consequences`,
   `## Alternatives Considered`, `## References`). **Expected error:**
   `FileNotFoundError` (file doesn't exist yet) → `AssertionError` once file
   created with missing sections.
2. Run `pytest tests/test_repo_structure.py::test_adr_001_exists_with_madr_sections -v`,
   confirm it fails with `FileNotFoundError`.
3. Author ADR file with content covering:
   - **Status:** Accepted, 2026-05-07
   - **Context:** Two distinct trading bots (crypto continuous-price vs Polymarket
     binary-settlement) need to share infrastructure (Postgres, Telegram, dashboard,
     Claude-oversight pattern) without coupling implementation details. CLAUDE.md
     previously assumed single-bot.
   - **Decision:** Mono-repo with bot-as-folder (`crypto-bot/`, `polymarket-bot/`)
     + shared infra at root (`pulse-bridge/`, `dashboard-ui/`, `infra/`). Postgres
     uses schema-level isolation: `brain.*` (kept for crypto, legacy name) and
     `polymarket.*` (new). `freqtrade-fork/` submodule stays at root (deviation
     justified by `.gitmodules` rewrite cost).
   - **Consequences:** (+) shared infra, dashboard cross-bot, ADRs cross-cutting;
     (−) blast radius slightly larger, refactor disruption to Phase-2-just-shipped
     state, naming asymmetry `brain` vs `polymarket`.
   - **Alternatives Considered:** (1) separate repo `AI-Polymarket/` —
     rejected (infra duplication + dashboard split); (2) component-as-folder
     `claude-routines/{crypto,polymarket}/` — rejected (mixes runtime
     boundaries); (3) plugin abstraction `trading-bot-skill` — rejected as
     premature (revisit after both bots paper-trade).
   - **References:** link to `docs/plans/2026-05-06-ai-trading-247.md`, this
     plan, NotebookLM IDs.
4. Run pytest, confirm pass.
5. Commit: `docs(adr): ADR-001 mono-repo multi-bot architecture`

**Verification:**
- [ ] `pytest tests/test_repo_structure.py::test_adr_001_exists_with_madr_sections -v` passes
- [ ] ADR file ≥ 1500 chars (substantive, not skeletal)
- [ ] All 6 MADR headings present
- [ ] No placeholder/`[TODO]` markers in ADR text
- [ ] Linked from CLAUDE.md (Phase K updates this — note the dependency)

---

## Phase B — ADR-002: References RAG Layer Architecture

**Estimated time:** 15 min

**Files:**
- Create: `docs/decisions/2026-05-07-002-references-rag-layer.md`
- Test: `tests/test_repo_structure.py` (add `test_adr_002_exists_with_madr_sections()`)

**Steps:**
1. Write failing test: same pattern as Phase A, asserting file existence +
   MADR sections + a specific section heading `## Precedence Order`.
   **Expected error:** `FileNotFoundError` initially.
2. Run pytest, confirm fail.
3. Author ADR file covering:
   - **Status:** Accepted, 2026-05-07
   - **Context:** Brain knowledge anatomy currently has 4 layers (skills,
     memory, journal, ML priors) but lacks an external RAG layer. Two NotebookLM
     notebooks (84 + 121 sources) hold capital-protection-relevant research that
     never reaches runtime context. Without grounding, brain reasoning leans on
     Claude training-data cutoff (Jan 2026), missing fresh microstructure +
     regulatory shifts.
   - **Decision:** Add `references/` folder with per-bot + shared subfolders.
     Compiled `refs-<bot>-decision.md` injected into every cron cycle via
     `claude --append-system-prompt-file`. Token budget ≤ 8K per compiled file.
     Update mechanism: NotebookLM research → distill → commit → recompile.
   - **Precedence Order** (Iron Law harmony): `Iron Laws > skills > references >
     memory > training data`. References cannot override skills or Iron Laws —
     if conflict detected at runtime, brain logs it to `brain_journal` and
     escalates to operator via Telegram.
   - **Token budget math:** 8K × 288 cycles/day × 30 days × Sonnet 4.6 with
     5-min prompt cache → effective ~$21/month per bot. Acceptable.
   - **Staleness mitigation:** quarterly cron (`infra/scripts/refs_staleness_check.py`,
     deferred to Phase 5+) re-validates against NotebookLM updated_at + flags
     drift via Telegram.
   - **Consequences:** (+) grounded reasoning, citation-traceable, lower
     hallucination; (−) extra token cost, distillation labor, staleness risk.
   - **Alternatives Considered:** (1) inline reference content in skills —
     rejected (skills are rules, references are facts; mixing loses precedence
     clarity); (2) live RAG via vector DB — rejected (latency + infra for marginal
     benefit at single-operator scale); (3) NotebookLM as runtime dep — rejected
     (network dep + non-deterministic, unsafe for capital protection).
   - **References:** ADR-001, NotebookLM IDs, `docs/research/2026-05-07-polymarket-ai-bot-deep-research-raw.md`.
4. Run pytest, confirm pass.
5. Commit: `docs(adr): ADR-002 references RAG layer architecture`

**Verification:**
- [ ] Test passes
- [ ] ADR ≥ 2000 chars
- [ ] `## Precedence Order` section explicitly states the 5-tier order
- [ ] Token budget math shown with assumptions (cycle frequency, cache TTL, model)
- [ ] No placeholder content

---

## Phase C — Refactor existing → `crypto-bot/`

**Estimated time:** 10 min

**Scope:** Path moves only, NO logic change. Submodule (`freqtrade-fork/`) stays
at root per ADR-001.

**Files:**
- Move: `claude-routines/` → `crypto-bot/claude-routines/` (currently empty,
  trivial git mv)
- Move: `freqtrade-config/` → `crypto-bot/freqtrade-config/` (config.json + strategies/)
- Create: `crypto-bot/README.md` (boundary doc)
- Modify: `tests/test_repo_structure.py` (update directory list)
- Modify: any pulse-bridge code referencing `freqtrade-config/` path (search &
  update — likely 0–2 spots)

**Steps:**
1. Write failing test: in `tests/test_repo_structure.py`, change the
   `test_required_directory_exists` parametrize list to include `crypto-bot/freqtrade-config`
   and `crypto-bot/claude-routines`, REMOVE the old `claude-routines` and
   `freqtrade-fork` from the parametrize (replace `freqtrade-fork` with a
   separate `test_freqtrade_submodule_at_root_per_adr_001` to assert submodule
   STAYS at root). **Expected error:** `AssertionError: crypto-bot/freqtrade-config/
   not found at repo root`.
2. Run pytest, confirm fail.
3. Execute:
   ```
   git mv claude-routines crypto-bot/claude-routines
   git mv freqtrade-config crypto-bot/freqtrade-config
   ```
   (Use Bash tool, not PowerShell — git mv path semantics are POSIX-cleaner.)
4. Search for `freqtrade-config/` references in `pulse-bridge/`, `infra/`,
   `tests/` (use Grep). Update each to `crypto-bot/freqtrade-config/`.
5. Author `crypto-bot/README.md` (≥ 800 chars): boundary statement, what lives
   here vs shared infra, link to original plan `docs/plans/2026-05-06-ai-trading-247.md`,
   submodule rationale link to ADR-001.
6. Run full test suite: `pytest tests/ -v`. Confirm all pass (no path-resolution
   regressions).
7. Commit: `refactor(repo): move crypto-specific to crypto-bot/ per ADR-001`

**Verification:**
- [ ] `pytest tests/test_repo_structure.py -v` all green
- [ ] Full suite `pytest tests/ -v` all green (no regression in Phase 2 tests)
- [ ] `git status` shows clean tree post-commit (no uncommitted reference path bugs)
- [ ] `crypto-bot/freqtrade-config/config.json` exists at new path
- [ ] `freqtrade-fork/` (submodule) STILL at repo root
- [ ] No file outside `tests/` imports from old `claude-routines/` or `freqtrade-config/`
  paths (Grep confirms zero stale refs)

---

## Phase D — Polymarket-bot Folder Skeleton

**Estimated time:** 10 min

**Files:**
- Create: `polymarket-bot/README.md`
- Create: `polymarket-bot/claude-routines/.gitkeep`
- Create: `polymarket-bot/clob-client/.gitkeep`
- Create: `polymarket-bot/strategies/.gitkeep`
- Modify: `tests/test_repo_structure.py` (add polymarket-bot directory assertions)

**Steps:**
1. Write failing test: parametrized assertions for
   `polymarket-bot/{README.md, claude-routines, clob-client, strategies}`.
   **Expected error:** `AssertionError: polymarket-bot/ not found`.
2. Run pytest, confirm fail.
3. Create directories + `.gitkeep` files.
4. Author `polymarket-bot/README.md` (≥ 1200 chars):
   - Boundary statement (this is body+brain for Polymarket prediction-market
     trading; mirrors crypto-bot architecture but uses py-clob-client instead
     of Freqtrade, binary-settlement gates instead of Sharpe/MaxDD).
   - Planned phases (high-level mirror of crypto's 16 phases, Polymarket-adapted
     gates: Brier score < 0.20, calibration ECE < 5%, oracle-dispute drill
     pass-rate, ≥ 100 resolved markets per OOS fold).
   - Status: SKELETON ONLY — full implementation in separate plan
     `docs/plans/2026-05-XX-polymarket-bot.md` (forthcoming).
   - Links: ADR-001, NotebookLM `d3fe46b9-...`, raw research report path.
5. Run pytest, confirm pass.
6. Commit: `feat(polymarket): scaffold polymarket-bot folder skeleton`

**Verification:**
- [ ] All directory assertions pass
- [ ] README ≥ 1200 chars, all sections present (boundary, phases, status, links)
- [ ] `.gitkeep` files committed (not gitignored)
- [ ] No placeholder content beyond explicit "SKELETON ONLY — see future plan" marker

---

## Phase E — Postgres `polymarket.*` Schema Migration

**Estimated time:** 20 min

**Files:**
- Create: `infra/migrations/003_polymarket_schema.sql`
- Create: `tests/integration/test_polymarket_schema.py`
- Modify: `tests/integration/__init__.py` if needed (just ensure pytest discovers)

**Steps:**
1. Write failing integration test (real Postgres per CLAUDE.md, marked
   `@pytest.mark.integration`): asserts `polymarket` schema exists with the
   following 5 tables (subset of brain — Polymarket doesn't have OHLCV-style
   data):
   - `polymarket.markets` (market_id, slug, question, outcomes, resolution_source, created_at, resolved_at, resolution_outcome)
   - `polymarket.signals` (mirrors `brain.signals` but with `outcome_yes_price`,
     `outcome_no_price` instead of OHLC indicators)
   - `polymarket.brain_journal` (same shape as `brain.brain_journal` + same
     append-only triggers — Iron Law 5)
   - `polymarket.equity_curve` (same as `brain.equity_curve`)
   - `polymarket.backtest_runs` (same as `brain.backtest_runs` but with
     Polymarket-relevant metrics in `metrics JSONB`: brier_score, calibration_ece,
     sample_size_per_market_type)
   - `polymarket.iteration_runs` (same as `brain.iteration_runs`)

   Test also asserts: append-only triggers on `polymarket.brain_journal` reject
   UPDATE/DELETE with SQLSTATE `42501`. **Expected error:** `psycopg2.errors.InvalidSchemaName:
   schema "polymarket" does not exist`.
2. Run `pytest tests/integration/test_polymarket_schema.py -v -m integration`,
   confirm fail.
3. Author `003_polymarket_schema.sql`:
   - `CREATE SCHEMA polymarket;`
   - All 6 tables hand-typed (NOT copy-pasted from `000_bootstrap_schemas.sql`
     — trigger function names hard-code schema, must be re-typed as
     `polymarket.reject_journal_mutation()`).
   - Indexes mirroring brain schema where applicable.
   - Append-only triggers on `polymarket.brain_journal`.
   - `polymarket.markets` is the new table type — design carefully:
     - `market_id TEXT PRIMARY KEY` (Polymarket's slug-or-condition-id)
     - `question TEXT NOT NULL`
     - `outcomes JSONB NOT NULL` (array of {name, token_id})
     - `resolution_source TEXT NOT NULL` (e.g. 'UMA optimistic oracle')
     - `created_at TIMESTAMPTZ NOT NULL DEFAULT now()`
     - `resolves_at TIMESTAMPTZ` (nullable — known resolution time if any)
     - `resolved_at TIMESTAMPTZ` (when actually resolved)
     - `resolution_outcome TEXT` (winning outcome name, NULL until resolved)
     - `metadata JSONB` (free-form for category, tags, liquidity_usd, etc.)
4. Apply migration to local Postgres: `psql -f infra/migrations/003_polymarket_schema.sql`.
5. Run integration test, confirm pass.
6. Update `CLAUDE.md` Architecture section to note dual-schema (deferred to
   Phase K — just note in this commit).
7. Commit: `feat(infra): add polymarket.* schema mirroring brain.* (ADR-001)`

**Verification:**
- [ ] Integration test passes against real Postgres
- [ ] `\dn` in psql shows both `brain` and `polymarket` schemas
- [ ] Append-only triggers test passes (UPDATE/DELETE on
  `polymarket.brain_journal` raises `42501`)
- [ ] `polymarket.markets` resolution_outcome NULL until resolved (sanity insert)
- [ ] Migration is reversible (write a `\set` rollback comment block at top:
  `DROP SCHEMA polymarket CASCADE;` for emergency recovery)
- [ ] No copy-paste-rename trigger bug (trigger function literally references
  `polymarket.brain_journal`, not `brain.brain_journal`)

---

## Phase F — References Folder Scaffold + `global-trading-config.md`

**Estimated time:** 15 min

**Files:**
- Create: `references/README.md`
- Create: `references/global-trading-config.md`
- Create: `references/{crypto,polymarket,shared}/.gitkeep`
- Create: `references/{crypto,polymarket}/compiled/.gitkeep`
- Modify: `tests/test_repo_structure.py` (assert references structure)

**Steps:**
1. Write failing test: parametrized assertions for `references/`,
   `references/global-trading-config.md`, `references/crypto/`,
   `references/polymarket/`, `references/shared/`,
   `references/crypto/compiled/`, `references/polymarket/compiled/`. Plus a
   content test on `global-trading-config.md` — must contain headings
   `## Iron Laws Summary`, `## Brain ↔ Body JSON Contract`, `## Precedence Order`.
   **Expected error:** `AssertionError: references/ not found`.
2. Run pytest, confirm fail.
3. Create directories + `.gitkeep`.
4. Author `references/README.md` (≥ 600 chars): explains the 5-tier knowledge
   layer per ADR-002, file naming convention, update workflow (NotebookLM
   research → distill → compile → commit), token budget per compiled file.
5. Author `references/global-trading-config.md` (≥ 1500 chars):
   - **Iron Laws Summary** — 5-line bullet list copy of the 5 Iron Laws (read
     from CLAUDE.md, distill verbatim).
   - **Brain ↔ Body JSON Contract** — distill from
     `docs/plans/2026-05-06-ai-trading-247.md` (search for HMAC/signal schema
     section). Include: signal envelope schema (signal_id, pair_or_market,
     direction, claude_decision, claude_size_mult, reasoning, confidence,
     timestamp, hmac_sig). Document that this is the contract enforced at
     `pulse-bridge/v1/decide` endpoint.
   - **Precedence Order** — copy verbatim from ADR-002.
   - **Cross-bot invariants** — anything that applies to BOTH crypto and
     polymarket bots: append-only journal, Telegram kill-switch HMAC, max
     concurrent positions counted ACROSS bots not per-bot, daily loss
     circuit-breaker GLOBAL.
6. Run pytest, confirm pass.
7. Commit: `feat(references): scaffold RAG layer + global-trading-config`

**Verification:**
- [ ] All folder/file assertions pass
- [ ] `global-trading-config.md` ≥ 1500 chars
- [ ] All 4 required headings present
- [ ] Iron Laws verbatim from CLAUDE.md (no rewording — Iron Laws are immutable
  per Iron Law 4)
- [ ] No placeholder content
- [ ] `.gitkeep` in compiled/ subfolders so git tracks empty dirs

---

## Phase G — Distill `references/crypto/*.md` (4 files)

**Estimated time:** 60 min (15 min per file × 4)

**Files (all NEW):**
- `references/crypto/exchange-microstructure.md`
- `references/crypto/freqtrade-walkforward.md`
- `references/crypto/known-failure-modes.md`
- `references/crypto/regime-taxonomy.md`

**Source:** NotebookLM `14c3a70f-c265-456e-a937-9281af14cae1` (alias
`ai-trading-research`, 84 sources).

**Per-file distillation method:**
1. Run `nlm notebook query 14c3a70f-c265-456e-a937-9281af14cae1 "<topic>"`
   for each topic-specific deep query (e.g., "Binance funding rate quirks +
   liquidation cascades + websocket gap recovery patterns" for
   exchange-microstructure).
2. Read the response. Cross-check by querying the same topic with a
   distinct angle to expose contradictions.
3. Distill to markdown with structure:
   - `## Topic 1` (e.g., Funding rate mechanics)
     - 3–5 bullet facts
     - Citations: `[Source: NotebookLM source #N — title]`
     - 1 actionable rule the brain should apply (e.g., "If funding flip > 50bp
       in 8h AND realized_vol > 1σ, treat as mean-reversion trap, not
       continuation signal")
   - Repeat per topic
   - `## Quick Decision Heuristics` — 5–8 single-line rules at the end for fast
     brain access during cron crunch

**Per-file size target:** 2500–4500 chars (rich enough to be useful, tight
enough to fit compiled budget).

**Topic specs (use these queries verbatim):**

1. **`exchange-microstructure.md`**
   Query: "Binance and Blofin microstructure for algorithmic crypto trading:
   funding rate mechanics, liquidation cascades, websocket gap recovery,
   maker-taker fee impact on PnL, partial fill handling, order book depth quirks"
2. **`freqtrade-walkforward.md`**
   Query: "Freqtrade walk-forward backtesting methodology, hyperopt overfitting
   pitfalls, FreqAI XGBoost feature engineering, ATR trailing stop calibration,
   protections (StoplossGuard, MaxDrawdown, CooldownPeriod) configuration
   patterns"
3. **`known-failure-modes.md`**
   Query: "Public crypto trading bot failure modes 2020-2026: 3AC and Alameda
   risk-management failures, retail bot blowups (martingale, grid in trending
   markets), exchange API outages and partial fills, oracle manipulation,
   flash crash liquidity cliffs"
4. **`regime-taxonomy.md`**
   Query: "Crypto market regime classification: trending up/down, ranging,
   high-volatility squeeze, post-FOMC mean-reversion, Asia/EU/US session
   patterns, BTC dominance regimes, altcoin season indicators"

**Steps (per file, repeated 4×):**
1. Write failing test: in `tests/test_repo_structure.py`, add
   `test_crypto_reference_files_exist_and_substantive()` — parametrized over
   the 4 file paths, asserts each file exists, ≥ 2500 chars, contains at
   least 3 `## ` headings, contains the string `[Source:` (citation marker).
   **Expected error:** `FileNotFoundError`.
2. Run pytest, confirm fail.
3. Run `nlm notebook query 14c3a70f-c265-456e-a937-9281af14cae1 "<topic query>"`
   via Bash. Read response.
4. (If response thin) Re-query with rephrasing OR `nlm notebook query <id>
   "deep dive on <subtopic>"` for richer content.
5. Author markdown file (Write tool) with distilled content + citations +
   Quick Decision Heuristics section.
6. After all 4 files done, run pytest, confirm pass.
7. Commit: `feat(references): distill crypto references from NotebookLM
   (4 files)`

**Verification:**
- [ ] All 4 files exist, each ≥ 2500 chars
- [ ] Each file has ≥ 3 `## ` topic sections + Quick Decision Heuristics
- [ ] Citations present (`[Source: NotebookLM ...]`) — minimum 3 per file
- [ ] No placeholder content (`[TODO]`, `Lorem`, etc. — grep with
  `Grep -r "TODO\|Lorem\|FIXME" references/crypto/` returns 0)
- [ ] Quick Decision Heuristics section present and actionable (rules, not
  observations)
- [ ] Tone: factual, citation-grounded — NOT marketing-speak

---

## Phase H — Distill `references/polymarket/*.md` (5 files)

**Estimated time:** 75 min (15 min per file × 5)

**Files (all NEW):**
- `references/polymarket/clob-microstructure.md`
- `references/polymarket/uma-oracle-risk.md`
- `references/polymarket/edge-sources.md`
- `references/polymarket/regulatory-cftc.md`
- `references/polymarket/known-failure-modes.md`

**Source:** NotebookLM `d3fe46b9-a3c2-4915-87c3-72c708835749` (alias
`polymarket`, 121 sources) + saved raw report
`docs/research/2026-05-07-polymarket-ai-bot-deep-research-raw.md`.

**Per-file distillation method:** same as Phase G, with the addition that
`Read docs/research/2026-05-07-polymarket-ai-bot-deep-research-raw.md` is the
first move per file (the raw report already covers all 5 topics; NotebookLM
queries are for deepening + citation specificity).

**Topic specs:**

1. **`clob-microstructure.md`**
   Query: "Polymarket CLOB matching engine architecture, USDC settlement on
   Polygon, gas optimization patterns, tick size and minimum order size, MEV
   on Polygon mempool reordering, py-clob-client websocket order book streaming"
2. **`uma-oracle-risk.md`**
   Query: "UMA optimistic oracle resolution mechanism for Polymarket markets:
   dispute window timing, bond economics, historical dispute case studies,
   resolution failure modes, ambiguous question outcomes"
3. **`edge-sources.md`**
   Query: "Profitable Polymarket trading strategies: news velocity arbitrage,
   sports model alpha (NFL, NBA), election prediction LLM ensembles, late-resolution
   scalping, long-tail mispricing, Kalshi vs Polymarket arbitrage spreads"
4. **`regulatory-cftc.md`**
   Query: "Polymarket CFTC regulation 2025-2026: US access status,
   settlement requirements, KYC implementation, prediction market federal
   oversight rulings, comparison Kalshi PredictIt regulatory paths"
5. **`known-failure-modes.md`**
   Query: "Polymarket trader and bot failure modes: liquidity crashes on
   resolution day, oracle dispute disasters, MEV sandwich attacks on Polygon,
   tail-risk events, position-sizing blowups, late-resolution mispricing traps"

**Steps (per file, repeated 5×):**
Same pattern as Phase G. TDD assertion:
`test_polymarket_reference_files_exist_and_substantive()` parametrized over 5
files. Same content thresholds (≥ 2500 chars, ≥ 3 `## ` headings, ≥ 3
citations, Quick Decision Heuristics).

**Verification:**
- [ ] All 5 files exist + meet content threshold
- [ ] `regulatory-cftc.md` cites at least 2 specific 2025–2026 ruling/news
  sources (regulatory state changes fast — must be fresh)
- [ ] `uma-oracle-risk.md` includes dispute case study (concrete event with
  timeline + outcome) — abstraction without case = placeholder failure
- [ ] No placeholder content (Grep clean)
- [ ] Citations distinct (5 files × 3 citations = ≥ 15 distinct sources from
  the 121-source notebook)

---

## Phase I — Distill `references/shared/*.md` (3 files)

**Estimated time:** 45 min

**Files (all NEW):**
- `references/shared/walk-forward-methodology.md`
- `references/shared/kelly-criterion.md`
- `references/shared/claude-oversight-pattern.md`

**Sources:**
- Walk-forward + Kelly: query crypto NotebookLM (general academic content) +
  general distillation.
- Claude-oversight pattern: distill from
  `docs/plans/2026-05-06-ai-trading-247.md` (Phase 4 sections about brain
  cron, JSON contract, HMAC signing) + this plan's ADR-002.

**Topic specs:**

1. **`walk-forward-methodology.md`**
   Query: "Walk-forward analysis for trading strategy backtesting: anchored
   vs rolling windows, OOS fold sizing, hyperparameter overfitting detection,
   Pardo methodology, statistical significance gates"
2. **`kelly-criterion.md`**
   Query: "Kelly criterion position sizing for trading: full Kelly vs
   fractional Kelly, risk-of-ruin calculation, drawdown tolerance, edge
   estimation uncertainty, geometric vs arithmetic returns"
3. **`claude-oversight-pattern.md`**
   Source: `Read docs/plans/2026-05-06-ai-trading-247.md` Phase 4–6 sections.
   Distill: cron cycle anatomy (5-min interval, 30s budget), brain ↔ body
   HMAC signal schema, journal append-only contract, kill-switch protocol,
   memory growth pattern (post-mortem cron weekly).

**Steps:**
1. Write failing test: parametrized over 3 file paths.
2. Run pytest, fail.
3. Distill each file (15 min each).
4. Run pytest, pass.
5. Commit: `feat(references): distill shared references (walkforward, kelly, oversight pattern)`

**Verification:**
- [ ] All 3 files exist + meet thresholds
- [ ] `claude-oversight-pattern.md` cites specific line ranges from
  `docs/plans/2026-05-06-ai-trading-247.md` (e.g., "see plan §Phase 4.3 lines X–Y")
- [ ] `kelly-criterion.md` includes the actual Kelly formula + a worked example
  with numbers (concrete > abstract)

---

## Phase J — Compile `refs-<bot>-decision.md`

**Estimated time:** 20 min

**Files:**
- Create: `infra/scripts/compile_refs.py` (build tool)
- Create: `references/crypto/compiled/refs-crypto-decision.md`
- Create: `references/polymarket/compiled/refs-polymarket-decision.md`
- Create: `tests/test_compile_refs.py`

**Compilation strategy:**
- Concatenation alone is the placeholder pitfall (per Anti-Placeholder Contract
  rule 2). The script MUST do **deliberate selection**:
  - Take only `## Quick Decision Heuristics` sections from each topic file
    (those are the brain's decision-relevant distillation).
  - Take only the first paragraph (≤ 400 chars) from each `## ` topic in detail
    files (one-paragraph context per topic).
  - Always include `references/global-trading-config.md` verbatim (Iron Laws +
    JSON contract are non-negotiable runtime context).
  - Always include relevant shared references (walk-forward + kelly +
    oversight-pattern) — same selection rule (Quick Heuristics + first para
    per topic).
- Output token count ≤ 8K (verified at compile time, fail loud if exceeded).
- Token estimation: use tiktoken (`tiktoken.encoding_for_model("gpt-4")`,
  good-enough proxy for Claude tokens, off by ≤ 10%).

**Steps:**
1. Write failing test: `tests/test_compile_refs.py`:
   - `test_compile_refs_script_exists()` — asserts script file present.
   - `test_compiled_crypto_decision_under_token_budget()` — runs the script,
     reads output, asserts tiktoken count ≤ 8000.
   - `test_compiled_crypto_decision_contains_iron_laws()` — asserts compiled
     file contains the 5-line Iron Laws summary verbatim.
   - `test_compiled_crypto_decision_contains_quick_heuristics()` — asserts
     each crypto reference's Quick Decision Heuristics section is present.
   - Same 4 tests for polymarket.
   **Expected error:** `FileNotFoundError: infra/scripts/compile_refs.py`
   initially.
2. Run pytest, confirm fail.
3. Author `infra/scripts/compile_refs.py`:
   - argparse: `--bot {crypto,polymarket}`
   - Reads files in order: global-trading-config.md, then bot-specific
     `*.md` (selecting Quick Heuristics + first paragraphs per rule above),
     then shared/*.md (same rule).
   - Writes to `references/<bot>/compiled/refs-<bot>-decision.md`.
   - Asserts token count ≤ 8000 (uses tiktoken). Hard-fails with exit code 1
     if exceeded — operator must trim.
   - Adds a `<!-- AUTOGENERATED by compile_refs.py at <timestamp>, do not
     edit by hand -->` header.
4. Add tiktoken to `pyproject.toml` deps (or test-only group).
5. Run script for both bots: `python infra/scripts/compile_refs.py --bot crypto`
   then `--bot polymarket`.
6. Run pytest, confirm pass.
7. Commit: `feat(references): compile_refs.py + compiled decision refs (≤8K each)`

**Verification:**
- [ ] Both compiled files exist
- [ ] Each ≤ 8000 tokens (assertion in test, also run `python -c "import tiktoken;
  enc=tiktoken.encoding_for_model('gpt-4'); ..."`)
- [ ] Each contains Iron Laws verbatim
- [ ] Each contains Quick Decision Heuristics from all bot-specific references
- [ ] Autogenerated header present (warns against manual edits)
- [ ] Script is idempotent (run twice → identical output, content-hash same
  modulo timestamp)
- [ ] Hard-fail behavior tested: temporarily oversize a source ref, run script,
  confirm exit code 1 + clear error message

---

## Phase K — Update `CLAUDE.md` to Multi-Bot + References Precedence

**Estimated time:** 20 min

**Files:**
- Modify: `CLAUDE.md` (root project memory)
- Modify: `tests/test_repo_structure.py` (extend
  `test_claude_md_has_mandatory_sections` with new section heading)

**Steps:**
1. Write failing test: extend mandatory sections list to include
   `## References Layer` and `## Multi-Bot Boundaries`.
   **Expected error:** `AssertionError: CLAUDE.md missing required sections:
   ['## References Layer', '## Multi-Bot Boundaries']`.
2. Run pytest, fail.
3. Edit `CLAUDE.md`:
   - **Update `## Architecture` ASCII diagram:** add second bot lane
     (`crypto-bot/` + `polymarket-bot/`) under the VPS box.
   - **Update `## Key Directories` table:** add `crypto-bot/`,
     `polymarket-bot/`, `references/`, `docs/decisions/` rows.
   - **NEW section `## Multi-Bot Boundaries`:** what's shared (pulse-bridge,
     dashboard-ui, infra, references/shared, references/global-trading-config),
     what's per-bot (claude-routines, strategies, postgres schema). Schema
     naming asymmetry note (`brain.*` for crypto = legacy, `polymarket.*` for
     polymarket = canonical naming forward).
   - **NEW section `## References Layer`:**
     - Brain knowledge anatomy: 5 layers now (skills, memory, journal, ML
       priors, references).
     - Precedence order verbatim from ADR-002.
     - Compiled file injection: cron `claude --append-system-prompt-file
       references/<bot>/compiled/refs-<bot>-decision.md ...`.
     - Update workflow: NotebookLM → distill → recompile.
     - Token budget: ≤ 8K per compiled file.
     - Link to ADR-002.
   - **Update `## Iron Laws` section:** Iron Law 4 reads-only list extends to
     `references/` (contents are operator-curated, not auto-edited by Claude
     — distillation is a deliberate human-in-the-loop step, not a routine
     cron job).
   - **Update `## Workflow` table:** add row for "Reference distillation"
     mapped to `gaspol-execute` + manual NotebookLM query.
4. Run pytest, confirm pass.
5. Run gaspol-sync-docs to verify CLAUDE.md still accurately reflects
   code (audit mode, not write mode).
6. Commit: `docs(claude-md): multi-bot + references layer per ADR-001/002`

**Verification:**
- [ ] All test_repo_structure.py tests pass including new section assertions
- [ ] `gaspol-sync-docs` audit mode reports no drift
- [ ] CLAUDE.md ≤ 600 lines (still loadable in cron context — important)
- [ ] Architecture diagram updated (multi-bot lanes visible)
- [ ] Iron Law 4 explicitly extended to `references/`
- [ ] No conflict between new sections and existing Iron Laws

---

## Phase L — Wire `--append-system-prompt-file` into Routine Template

**Estimated time:** 15 min

**Files:**
- Create: `crypto-bot/claude-routines/routines/_template.md`
- Create: `polymarket-bot/claude-routines/routines/_template.md`
- Create: `crypto-bot/claude-routines/routines/.gitkeep` (if not present)
- Create: `polymarket-bot/claude-routines/routines/.gitkeep`

**Note:** Routine specs themselves are written in Phase 5+ of the original
plan. This phase just establishes the **template** so future routines inherit
the references-inject convention by default.

**Steps:**
1. Write failing test: `tests/test_routines_template.py`:
   - Asserts both templates exist.
   - Asserts each contains the literal flag string `--append-system-prompt-file
     references/<bot>/compiled/refs-<bot>-decision.md` (parametrized so
     `<bot>` is `crypto` for crypto-bot, `polymarket` for polymarket-bot).
   - Asserts each template documents the 5 knowledge layers in the comment block.
   **Expected error:** `FileNotFoundError`.
2. Run pytest, fail.
3. Author crypto template (≥ 800 chars):
   ```markdown
   # Routine Template — Crypto Bot

   Replace this header with the actual routine name (e.g., "5min Oversight").

   ## Cron spec
   schedule: "*/5 * * * *"  # every 5 minutes
   timeout: 30s

   ## Invocation
   claude \
     --append-system-prompt-file references/crypto/compiled/refs-crypto-decision.md \
     --skill <routine-skill-name> \
     [other args]

   ## Knowledge layers loaded per cycle
   1. Iron Laws (verbatim, from refs-crypto-decision.md)
   2. Skills (from crypto-bot/claude-routines/skills/*.md, loaded by skill harness)
   3. Memory (from crypto-bot/claude-routines/memory/*.md)
   4. Journal recent N (from brain.brain_journal SELECT, in skill's
      tool-use phase)
   5. References — global + crypto-specific + shared (compiled file
      injected via --append-system-prompt-file flag above)

   ## Token budget
   - Compiled refs ≤ 8K
   - Skill body + memory + journal recent ≈ 5–10K
   - User prompt + tool results ≈ 5K
   - Total cycle target ≤ 25K input tokens (well within Sonnet 4.6 limits).

   ## Precedence (per ADR-002)
   Iron Laws > skills > references > memory > training data.
   ```
4. Mirror for polymarket template (same structure, different paths).
5. Run pytest, pass.
6. Commit: `feat(routines): inject references via --append-system-prompt-file
   in routine templates`

**Verification:**
- [ ] Both template files exist + content checks pass
- [ ] Templates are .md (not .yaml) — they describe the cron + invocation but
  actual cron specs live in systemd / OS crontab per Phase 5+
- [ ] Future skill writers can `cp _template.md <new-routine>.md` and adapt

---

## Final Verification (after all phases)

Run the full guard:

```bash
# 1. Full test suite green
pytest tests/ -v
pytest tests/integration/ -v -m integration  # requires real Postgres

# 2. Anti-placeholder grep
grep -r -E "TODO|FIXME|Lorem|XXX|HACK" references/ docs/decisions/ \
  crypto-bot/README.md polymarket-bot/README.md
# Expected: ZERO matches

# 3. Compiled token budget
python infra/scripts/compile_refs.py --bot crypto  # exit 0
python infra/scripts/compile_refs.py --bot polymarket  # exit 0

# 4. CLAUDE.md size sanity
wc -l CLAUDE.md  # ≤ 600 lines

# 5. Submodule still works
cd freqtrade-fork && git status  # clean, on main
cd ..

# 6. Postgres schemas both present
psql trading -c "\dn"  # lists brain, polymarket
```

All 6 must pass before declaring this plan done.

---

## Execution Handoff

**Option 1: Execute in this session**
> "Ready to start Phase A? I'll use `gaspol-execute` to implement with per-phase
> checkpoints. Phase A and B (ADRs) are pure-doc and fast — good warm-up."

**Option 2: Parallel execution**
> "Phases G + H + I (reference distillation) are independent — can run in
> parallel via `gaspol-parallel` mode plan-phases. Phases A→F→K are strictly
> sequential. Estimated wall-clock with parallelism: ~3.5 h instead of 5 h."

**Option 3: Separate session**
> "Save plan, kick off in a fresh session. This plan file at
> `docs/plans/2026-05-07-multi-bot-references-restructure.md` is fully
> self-contained — fresh executor reads CLAUDE.md + this plan + the linked
> ADRs (once written) and has everything needed."

---

## Cross-references

- Original plan (crypto-only, 16 phases): `docs/plans/2026-05-06-ai-trading-247.md`
- Polymarket research raw report (saved 2026-05-07):
  `docs/research/2026-05-07-polymarket-ai-bot-deep-research-raw.md`
- NotebookLM crypto: `14c3a70f-c265-456e-a937-9281af14cae1` (alias `ai-trading-research`, 84 sources)
- NotebookLM polymarket: `d3fe46b9-a3c2-4915-87c3-72c708835749` (alias `polymarket`, 121 sources)
- ADRs (to be written in Phases A, B): `docs/decisions/2026-05-07-001-mono-repo-multi-bot.md`,
  `docs/decisions/2026-05-07-002-references-rag-layer.md`
- Future plan (polymarket-bot phased implementation, NOT this plan):
  `docs/plans/2026-05-XX-polymarket-bot.md` (forthcoming)
