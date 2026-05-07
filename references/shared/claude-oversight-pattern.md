# Claude Oversight Pattern

> Source attribution: distilled from the in-repo plan
> [Source: docs/plans/2026-05-06-ai-trading-247.md §Phase 4–6] plus
> [Source: docs/decisions/2026-05-07-001-mono-repo-multi-bot.md §Decision]
> and [Source: docs/decisions/2026-05-07-002-references-rag-layer.md §Precedence Order, §Token-budget math].
> Last refreshed: 2026-05-07. Per ADR-002 references RAG layer.

This file is meta-documentation about THIS project's brain pattern. It is the
runtime-injected reference both bots (crypto + Polymarket) read every cron
cycle so they share a single mental model of how the brain talks to the body,
where its authority ends, and how the kill-switch is wired.

## Topic 1 — Cron cycle anatomy (Routines + 5-min cadence)

The brain is a **stateless 5-minute Routine**, not a long-running daemon. Each
cycle is a fresh `claude` CLI invocation that loads its full knowledge surface
from disk + Postgres + the just-fetched market context, makes ONE decision per
open signal, writes that decision to the journal, and exits. There is no
in-memory state between cycles — durability is Postgres, period.

Per the original plan, Phase 5 specifies the entry-point routine
`claude-routines/routines/oversight-loop.md` whose loop is
[Source: docs/plans/2026-05-06-ai-trading-247.md §Phase 5 step 8]:

1. Cron fires (5-min cadence; faster 1-min cadence reserved for mean-reversion
   strategies — see plan §12 open-question 4).
2. Routine fetches `GET /v1/context_bundle` from pulse-bridge — returns OHLCV
   last 4h + open positions + last journal entry, formatted as a
   cache-friendly prefix [Source: docs/plans/2026-05-06-ai-trading-247.md
   §Phase 4 step 3].
3. Brain reads the four operator-curated knowledge surfaces (skills, memory,
   recent journal SELECT, ML priors) plus the fifth surface added in
   ADR-002 (compiled references — this file lives there).
4. For each pending signal in the bundle, brain emits exactly one decision:
   `approve`, `veto`, or `resize` (with `size_mult ∈ [0, 1]`).
5. Brain `POST /v1/decide` to pulse-bridge with the JSON envelope (Topic 2).
6. Brain `POST /v1/journal` with reasoning + expected outcome.
7. Process exits. Next cycle in 5 min.

The cadence is chosen to align with the **Anthropic prompt cache TTL = 5
minutes** [Source: docs/decisions/2026-05-07-002-references-rag-layer.md
§Token-budget math]. A 5-min cadence gives the operator a ≥ 95% cache-hit
rate on the static prefix (skills + memory + compiled refs), which collapses
the per-cycle billed input tokens from ~25K to ~3.6K and pins the runtime
cost to roughly $94/bot/month at Sonnet 4.6 input pricing.

**Actionable rule for the brain:** if the cron fires and `GET /v1/context_bundle`
returns 5xx or stale data (last bar > 90s old), abstain from all decisions
this cycle and emit a Telegram alert. A blind brain is a vetoing brain — never
guess on missing context.

## Topic 2 — Brain ↔ Body JSON contract (HMAC over Unix socket)

The brain talks to the body through **pulse-bridge** — a FastAPI shim listening
on `unix:/run/pulse.sock` (chmod 660, group `trader`). The contract is
deliberately tiny — five endpoints, all HMAC-signed with a shared secret in
`.env` separate from the Telegram secret
[Source: docs/plans/2026-05-06-ai-trading-247.md §Phase 4 step 3].

| Endpoint | Direction | Payload |
|---|---|---|
| `GET /v1/context_bundle` | bridge → brain | OHLCV + open positions + last journal entry |
| `GET /v1/pending_signals?since=ts` | bridge → brain | open signals awaiting decision |
| `POST /v1/decide` | brain → bridge | `{signal_id, regime, decision: "approve"\|"veto"\|"resize", size_mult}` |
| `POST /v1/journal` | brain → bridge | reasoning + expected_outcome (append-only) |
| `POST /v1/halt` | operator → bridge | HMAC kill-switch (Telegram-allowlisted) |

The decision envelope is **the entire surface area the brain is allowed to
write through**. There is no `disable_protection`, no `extend_size_cap`, no
`reset_kill_switch` field — these would violate Iron Law 1
[Source: docs/plans/2026-05-06-ai-trading-247.md §9 Risk rails]. The strategy's
`confirm_trade_entry` hook reads `signals.claude_decision` and:

- `veto` → abort the order
- `resize` → multiply `stake_amount` by `size_mult` (still capped by the
  hard-coded 25%-of-equity rail)
- `approve` → proceed at default `stake_amount`
- `null` and signal > 5 min old → fail-safe to default rule-based decision
  (do not block trades on a silent brain) [Source:
  docs/plans/2026-05-06-ai-trading-247.md §Phase 4 step 4]

**Multi-bot extension.** Per ADR-001, both crypto-bot and polymarket-bot share
this single pulse-bridge process via two FastAPI routers (`/v1/crypto/*` and
`/v1/polymarket/*` are anticipated future evolutions; today both bots share
one Unix socket and disambiguate by `bot_id` field on the decision envelope)
[Source: docs/decisions/2026-05-07-001-mono-repo-multi-bot.md §Decision lines
56–65].

**Actionable rule for the brain:** never construct a JSON field outside the
five documented endpoints. If you find yourself wanting a sixth endpoint to
"just temporarily" bypass a rail, STOP and emit a Telegram alert to the
operator. Iron Law 1 is enforced at the file-ownership boundary, not just by
convention.

## Topic 3 — Append-only journal + kill-switch + references precedence

**Journal is append-only by Postgres grant, not by convention.**
`brain.brain_journal` (and the parallel `polymarket.brain_journal`) has
`INSERT, SELECT` granted to the `trader` role; `UPDATE` and `DELETE` are
explicitly REVOKED at migration time
[Source: docs/plans/2026-05-06-ai-trading-247.md §Phase 6 step 3]. The brain
can never rewrite a past lesson, even by accident — Iron Law 5 is enforced in
the database, not in markdown. Memory files (`claude-routines/memory/*.md`)
are append-only by convention (Iron Law 4 — Claude must not modify its own
discipline files), but the journal is the tamper-evident audit log.

**Kill-switch is HMAC-authenticated at two layers.** `POST /v1/halt` requires
both an HMAC signature AND a Telegram user-ID in the allowlist
[Source: docs/plans/2026-05-06-ai-trading-247.md §12 question 5]. The brain
itself cannot call `/v1/halt` — only the operator via Telegram or the auto
circuit breakers (daily −5% halt 24h, drawdown −20% halt indefinitely). Per
Iron Law 1, Claude can VETO a trade and RESIZE within the cap, but cannot
DISABLE a circuit breaker, EXTEND a position size limit, or RESET a kill
switch. These actions require operator manual edit + restart.

**References precedence.** When the references RAG layer (this file's home)
conflicts with another knowledge surface, the brain follows
[Source: docs/decisions/2026-05-07-002-references-rag-layer.md §Precedence
Order]:

1. Iron Laws (CLAUDE.md, architecturally enforced) — top.
2. Skills (`<bot>/claude-routines/skills/*.md`) — operator-curated rules.
3. References (this layer) — external grounded knowledge. Cannot override
   skills or Iron Laws.
4. Memory (`<bot>/claude-routines/memory/*.md`) — additive, generally not
   contradictory; if memory contradicts references, references win (memory
   may have encoded a transient misobservation).
5. Training data — fallback only.

If a runtime conflict between references and skills/Iron Laws is detected,
the brain MUST: (a) abstain from the trade (default veto), (b) log the
conflict to `brain_journal` with `decision='halt'` and detailed reasoning,
and (c) emit a Telegram alert flagging the conflict for operator review.
Conflicts are **never** silently resolved.

**Actionable rule for the brain:** if you would write a journal entry whose
reasoning silently contradicts an Iron Law or a skill rule, STOP. Default to
`veto`, log the contradiction explicitly, and let the operator adjudicate at
the next post-mortem cron.

## Quick Decision Heuristics

- If `context_bundle` is stale (last bar > 90s) or returns 5xx, abstain from
  all decisions this cycle and Telegram-alert the operator.
- If the proposed decision would require a JSON field outside the five
  documented endpoints, STOP — Iron Law 1 violation, alert operator.
- If a signal has been pending > 5 min with no brain decision, the strategy
  fail-safes to its default rule-based path; do not block trades on a silent
  brain.
- If references and skills conflict at runtime, default-veto, log
  `decision='halt'` with reasoning, and Telegram-alert. Never silently
  reconcile.
- If memory contradicts references, references win — memory may have encoded
  a transient misobservation; references are externally citation-grounded.
- If you (the brain) detect an opportunity to "improve" CLAUDE.md, a skill
  file, `freqtrade-fork/user_data/config.json`, an `infra/migrations/*.sql`,
  or anything under `references/`, STOP — Iron Law 4 forbids autonomous edits
  to discipline files. Raise via Telegram, wait.
- If you cannot articulate the reasoning for an `approve` decision in ≤ 3
  sentences citing at least one skill or reference, default to `veto`. Vague
  conviction is not edge.
- If the cron fires within 60 seconds of a circuit breaker tripping (daily
  −5% or drawdown −20%), exit immediately without writing decisions — the
  body owns the halt state, the brain must not race it.
