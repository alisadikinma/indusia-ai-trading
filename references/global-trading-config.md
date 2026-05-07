# global-trading-config.md — Cross-Bot Invariant Reference

This file is **always** included verbatim in every compiled per-bot decision
reference (`refs-<bot>-decision.md`). It encodes the non-negotiable invariants
that apply to BOTH `crypto-bot/` and `polymarket-bot/`. Per ADR-002, this
file ranks above bot-specific references in the brain's precedence order.

---

## Iron Laws Summary

The 5 Iron Laws from `CLAUDE.md` §Iron Laws, verbatim summary (no rewording —
Iron Laws are immutable per Iron Law 4):

1. **Iron Law 1 — Claude cannot override risk rails.** Risk parameters are
   hard-coded in per-bot config (crypto: `crypto-bot/freqtrade-config/config.json`
   + Freqtrade protections; polymarket: per-strategy capital-at-risk caps in
   `polymarket-bot/`) in a separate process from Claude. Claude may VETO or
   RESIZE within the cap. Claude MAY NOT disable a circuit breaker, extend a
   position size limit, or reset a kill switch. Operator manual edit + restart
   only. Crypto rail values: max 25% per trade, max 3 concurrent, daily loss
   −5% halts 24h, per-trade 2×ATR(14) trailing stop, max drawdown −20% from
   peak liquidates + halts indefinitely, API key rotation 30d.

2. **Iron Law 2 — No live trade without backtest + paper-trade sign-off.**
   Crypto gates: walk-forward Sharpe > 1.5, MaxDD < 25%, profit factor > 1.4,
   ≥ 100 trades, in ALL 5 OOS folds. Polymarket gates: Brier score < 0.20,
   calibration ECE < 5%, ≥ 100 resolved markets per OOS fold, oracle-dispute
   drill pass. Both: 3–4 weeks paper trade with PnL drift < 30% vs backtest,
   then live $100 for 4 weeks with weekly drift gate. Failure → Phase 9.5
   iteration loop, max 3 cycles, then architectural rethink ADR. No silent
   advance.

3. **Iron Law 3 — No placeholder data in production code paths.** Real
   Postgres, real CCXT / py-clob-client, real `os.environ[...]` (raises if
   missing — no silent default). Mocks only in `tests/`. A fake data path
   running against real money is the textbook bot failure mode.

4. **Iron Law 4 — Claude must not modify its own discipline files.** Read-
   only by convention: `<bot>/claude-routines/skills/trading-discipline.md`,
   per-bot risk config, `infra/migrations/*.sql`, `CLAUDE.md`, and (per
   ADR-002 extension) the `references/` layer. If Claude detects an
   opportunity to "improve" any of these autonomously — STOP, raise to
   operator via Telegram, wait.

5. **Iron Law 5 — Memory grows append-only.** `<schema>.brain_journal`
   Postgres table has UPDATE/DELETE rejected via trigger raising SQLSTATE
   42501 (verified in `tests/integration/test_schemas_bootstrap.py` and
   `tests/integration/test_polymarket_schema.py`). `<bot>/claude-routines/memory/*.md`
   files are append-only by convention; Claude may add new entries but must
   not rewrite or delete past lessons. Audit log is tamper-evident.

---

## Brain ↔ Body JSON Contract

The contract enforced at the `pulse-bridge/v1/<bot>/decide` endpoint
(implementation: `pulse-bridge/pulse_bridge/v1_routes/auth.py` HMAC + decide
route).

### Request envelope (Claude oversight → pulse-bridge)

```jsonc
{
  "signal_id": 12345,                    // FK to <schema>.signals.id
  "decision": "approve",                 // enum: approve | veto | resize | halt | no_action
  "size_mult": 1.0,                      // float in [0.5, 1.5], NULL if not resize
  "reasoning": "...",                    // free-text, written verbatim to brain_journal
  "confidence": 7,                       // smallint 1-10
  "expected_outcome": "...",             // free-text qualitative
  "regime": "trending_up",               // crypto: trending_up/down|ranging|volatile
                                         // polymarket: pre-resolution-stable|news-shock|oracle-dispute-active
  "ts": "2026-05-07T08:00:00Z"           // ISO 8601 UTC
}
```

### HMAC headers (replay protection + integrity)

```
X-PULSE-Timestamp: <int unix_seconds>
X-PULSE-Signature: <hex HMAC-SHA256(secret, f"{method}\n{path}\n{ts}\n{body}")>
```

- Replay protection: timestamp drift > 60s → 401 Unauthorized.
- Constant-time compare: `hmac.compare_digest`.
- Hard-fails on missing `PULSE_HMAC_SECRET` env (Iron Law 3 — no silent
  default).

### Response (pulse-bridge → Claude oversight)

```jsonc
{
  "ack": true,
  "signal_id": 12345,
  "journal_id": 67890,                   // brain_journal row created
  "applied_at": "2026-05-07T08:00:00.123Z"
}
```

### Failure semantics

- HTTP 401: HMAC failure or timestamp drift.
- HTTP 422: payload validation failure (signal_id not found, decision not in
  enum, size_mult out of range).
- HTTP 500: Postgres unreachable / write failed. Brain MUST retry on next
  cron cycle — never silently log and proceed.

---

## Precedence Order

When sources conflict at runtime, the brain uses this precedence (highest
authority first):

1. **Iron Laws** — non-negotiable, architecturally enforced. Cannot be
   overridden by ANY other source.
2. **Skills** (`<bot>/claude-routines/skills/*.md`) — operator-curated rules
   for THIS portfolio. Override training data and references.
3. **References** (`references/`, this layer) — external grounded knowledge.
   Override training data and memory. CANNOT override skills or Iron Laws.
4. **Memory** (`<bot>/claude-routines/memory/*.md`) — accumulated learnings
   from live trading.
5. **Training data** — fallback only. Always subordinated to operator-supplied
   surfaces.

Conflicts are not silently resolved. If references contradict skills/Iron Laws
at runtime, the brain must (a) abstain from the trade (default veto), (b)
log the conflict to `<schema>.brain_journal` with `decision='halt'`, (c)
emit a Telegram alert flagging operator review.

---

## Cross-bot invariants

These rules apply to BOTH `crypto-bot/` and `polymarket-bot/`:

- **Append-only journal.** `<schema>.brain_journal` UPDATE/DELETE → SQLSTATE
  42501. Reject any code/skill suggestion that requires mutating past
  journal entries. New facts go in NEW rows.
- **Telegram kill-switch HMAC.** Operator-issued kill commands carry the same
  HMAC scheme as the brain↔body contract. Brain MUST honor `halt` directive
  on next cycle, no exceptions.
- **Max concurrent positions counted ACROSS bots, not per-bot.** For risk
  budgeting at portfolio level, the daily loss circuit breaker (−5% equity)
  and max drawdown kill switch (−20% from peak) apply to total equity ACROSS
  both bots. Per-bot concurrent cap is additional, not substitute. Phase 12
  observation rule: live capital is split between bots only AFTER both have
  passed paper trade independently.
- **API key rotation 30 days, automated.** Applies to Binance, Blofin (crypto
  bot) AND Polymarket / py-clob-client API keys. `infra/scripts/api_key_rotation.sh`
  handles both.
- **No silent fallback values for env.** `os.environ["X"]` not
  `os.getenv("X", "default")`. Applies to every secret/config in either bot.
- **Same brain JSON contract.** Different endpoints (`/v1/crypto/decide`,
  `/v1/polymarket/decide`) but identical envelope schema. Future bots adopt
  the same contract.
- **Same precedence order.** Skills > references > memory in BOTH bots. The
  reference layer's compiled file structure is identical (Quick Decision
  Heuristics + first paragraph per topic).

---

## Quick Decision Heuristics (cross-bot)

For fast brain access during cron crunch:

- **Conflict detected →** abstain + log + alert. Never silently resolve.
- **Confidence < 5 →** prefer `veto` over `resize` over `approve`.
- **Risk-rail proximity →** within 80% of daily-loss circuit breaker, treat
  ALL new signals as `veto` regardless of edge.
- **Kill-switch alert →** halt immediately, no in-flight overrides.
- **Reference vs memory disagreement →** reference wins (memory may have
  encoded a transient observation).
- **Skills vs reference disagreement →** skills win, log mismatch for
  operator review.
- **Reference older than 6 months without re-validation →** treat as
  hint-only, not authoritative; flag to staleness check.
