# Routine Template — Polymarket Bot

> Copy this file to `<routine-name>.md` (e.g. `5min-oversight.md`,
> `oracle-dispute-watcher.md`) and adapt. The
> `--append-system-prompt-file` flag below MUST be preserved — it injects
> the references RAG layer per ADR-002.

## Cron spec

```cron
# Replace with your actual schedule. Examples:
# Every 5 minutes (core oversight loop, mirrors crypto cadence):
*/5 * * * *   /opt/ai-trading/polymarket-bot/claude-routines/routines/<routine-name>.invoke.sh
# Every 15 minutes during active dispute window (UMA optimistic oracle):
# */15 * * * * /opt/ai-trading/polymarket-bot/claude-routines/routines/oracle-dispute-watcher.invoke.sh
```

Cycle budget target: ≤ 30 seconds end-to-end. Hard timeout: 60 seconds.

## Invocation (the canonical form)

```bash
claude \
    --append-system-prompt-file references/polymarket/compiled/refs-polymarket-decision.md \
    --skill <routine-skill-name> \
    --input-from-stdin \
    --output-format json \
    [other args]
```

The `--append-system-prompt-file` flag is mandatory for any routine running
against capital. It loads the compiled Polymarket decision references (Iron
Laws + JSON contract + Quick Decision Heuristics from CLOB microstructure,
UMA oracle risk, edge sources, regulatory CFTC, failure modes, plus shared
walk-forward / Kelly / oversight pattern). Token budget ≤ 8K, hard-capped
by `infra/scripts/compile_refs.py`.

## Knowledge layers loaded per cycle

Five knowledge surfaces (per ADR-002), in precedence order on conflict:

1. **Iron Laws** — verbatim in compiled refs file.
2. **Skills** (`polymarket-bot/claude-routines/skills/*.md`) — Polymarket-
   tuned: `oracle-dispute-protocol.md`, `news-velocity-playbook.md`,
   `trading-discipline.md`, `signal-evaluation.md`, etc.
3. **References** — bot-specific compiled file (this `--append-system-prompt-file`).
4. **Memory** (`polymarket-bot/claude-routines/memory/*.md`).
5. **Journal recent N** — `SELECT FROM polymarket.brain_journal` ORDER BY ts DESC LIMIT 50.

If references contradict skills/Iron Laws at runtime: brain MUST abstain
(default veto), log conflict to `polymarket.brain_journal` with
`decision='halt'`, emit Telegram alert. Never silently resolve.

## Token budget

- Compiled refs: ≤ 8K tokens (hard cap).
- Skill body + memory + journal recent: ~5K-10K tokens.
- User prompt + tool results: ~5K tokens.
- **Cycle input total target: ≤ 25K tokens.**

## Precedence Order (per ADR-002)

```
Iron Laws > Skills > References > Memory > Training data
```

## Output contract

Routines POST structured JSON to `pulse-bridge` at `/v1/polymarket/decide`.
Envelope shape per `references/global-trading-config.md` §Brain↔Body JSON
Contract:

```jsonc
{
  "signal_id": <int>,
  "decision": "approve|veto|resize|halt|no_action",
  "size_mult": <float in [0.5, 1.5] or null>,
  "reasoning": "<verbatim free-text written to polymarket.brain_journal>",
  "confidence": <int 1-10>,
  "expected_outcome": "<free-text>",
  "regime": "pre-resolution-stable|news-shock|oracle-dispute-active|near-resolution",
  "ts": "<ISO-8601 UTC>"
}
```

The `regime` enum is Polymarket-specific; differs from crypto's
trending_up/down/ranging/volatile. Check
`references/polymarket/clob-microstructure.md` and
`references/polymarket/uma-oracle-risk.md` for regime classification rules.

HMAC headers (`X-PULSE-Timestamp`, `X-PULSE-Signature`) added by the cron
wrapper, NOT by the routine.

## Polymarket-specific failure modes the routine must handle

- `pulse-bridge` 401/422/500: same as crypto (see crypto template).
- **UMA dispute window detected (regime = `oracle-dispute-active`):**
  default to `decision='halt'` for all positions on the disputed market,
  alert operator. Do NOT exit positions blindly during dispute window —
  liquidity often crashes.
- **Resolution day liquidity crash:** if order book depth drops below
  N USDC at top-of-book, treat as halt-only regime.
- **MEV sandwich evidence in recent fills:** flag to operator, halt new
  entries on Polygon for 1 hour.

## Iron Law 4 reminder

This template + actual routine `.md` files are operator-curated. Claude
(runtime brain) MUST NOT auto-edit routine specs. Operator-only with ADR
for logic changes.
