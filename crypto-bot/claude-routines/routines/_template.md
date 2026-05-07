# Routine Template — Crypto Bot

> Copy this file to `<routine-name>.md` (e.g. `5min-oversight.md`,
> `weekly-postmortem.md`) and adapt. The `--append-system-prompt-file` flag
> below MUST be preserved — it injects the references RAG layer per ADR-002.

## Cron spec

```cron
# Replace with your actual schedule. Examples:
# Every 5 minutes (oversight cron, the core loop):
*/5 * * * *   /opt/ai-trading/crypto-bot/claude-routines/routines/<routine-name>.invoke.sh
# Every Sunday 03:00 UTC (weekly post-mortem):
# 0 3 * * 0   /opt/ai-trading/crypto-bot/claude-routines/routines/weekly-postmortem.invoke.sh
```

Cycle budget target: ≤ 30 seconds end-to-end (data fetch + brain reasoning +
journal write). Hard timeout: 60 seconds (kill cycle, log to journal as
`decision='halt'`, retry next cycle).

## Invocation (the canonical form)

```bash
claude \
    --append-system-prompt-file references/crypto/compiled/refs-crypto-decision.md \
    --skill <routine-skill-name> \
    --input-from-stdin \
    --output-format json \
    [other args]
```

The `--append-system-prompt-file` flag is mandatory for any routine running
against capital. It loads the compiled crypto decision references (Iron Laws
+ JSON contract + Quick Decision Heuristics from microstructure / failure
modes / regime taxonomy / walk-forward / Kelly / oversight pattern). Token
budget ≤ 8K, hard-capped by `infra/scripts/compile_refs.py`.

## Knowledge layers loaded per cycle

The brain consults FIVE knowledge surfaces (per ADR-002), in this precedence
order when sources conflict:

1. **Iron Laws** — verbatim in compiled refs file (loaded via
   `--append-system-prompt-file` above).
2. **Skills** (`crypto-bot/claude-routines/skills/*.md`) — loaded by the
   skill harness when `--skill` resolves the routine's skill name.
3. **References** — same compiled file as layer 1; bot-specific Quick
   Decision Heuristics + first-paragraph topic context.
4. **Memory** (`crypto-bot/claude-routines/memory/*.md`) — loaded by the
   skill harness; per-bot accumulated wisdom.
5. **Journal recent N** — fetched at runtime via SELECT against
   `brain.brain_journal` (most recent ~50 entries by default; tune per
   routine).

If references contradict skills/Iron Laws at runtime: brain MUST abstain
(default veto), log conflict to `brain.brain_journal` with
`decision='halt'`, emit Telegram alert. Never silently resolve.

## Token budget

- Compiled refs: ≤ 8K tokens (hard cap).
- Skill body + memory + journal recent ~50 rows: ~5K-10K tokens (grows
  with memory; review per routine).
- User prompt + tool results: ~5K tokens (varies with cycle).
- **Cycle input total target: ≤ 25K tokens** (well under Sonnet 4.6 200K
  context). Prompt cache (5-min TTL) absorbs most cycles since cron cadence
  matches.

## Precedence Order (per ADR-002)

```
Iron Laws > Skills > References > Memory > Training data
```

References cannot override skills or Iron Laws. Skills cannot override Iron
Laws.

## Output contract

Routines write structured JSON output that the cron wrapper POSTs to
`pulse-bridge` at `/v1/crypto/decide`. Envelope shape per
`references/global-trading-config.md` §Brain↔Body JSON Contract:

```jsonc
{
  "signal_id": <int>,
  "decision": "approve|veto|resize|halt|no_action",
  "size_mult": <float in [0.5, 1.5] or null>,
  "reasoning": "<verbatim free-text written to brain.brain_journal>",
  "confidence": <int 1-10>,
  "expected_outcome": "<free-text>",
  "regime": "trending_up|trending_down|ranging|volatile",
  "ts": "<ISO-8601 UTC>"
}
```

HMAC headers (`X-PULSE-Timestamp`, `X-PULSE-Signature`) added by the cron
wrapper, NOT by the routine itself.

## Failure modes the routine must handle

- `pulse-bridge` 401: HMAC mismatch — log + halt, alert operator.
- `pulse-bridge` 422: payload validation — bug in routine output, halt + alert.
- `pulse-bridge` 500: Postgres unreachable — log + retry next cycle.
- Cycle timeout: log `decision='halt'` + alert.
- Reference vs skill conflict detected: same as cycle timeout.

## Iron Law 4 reminder

This template + the actual routine `.md` files in this folder are
operator-curated. Claude (the runtime brain) MUST NOT auto-edit routine
specs. Operator-only edits, with ADR for material logic changes.
