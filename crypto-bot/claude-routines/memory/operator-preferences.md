# Operator Preferences

> Initialised 2026-05-07 as part of Phase 6 (Memory + Journal helpers +
> Continuous Learning Ops).

## Purpose

This file captures **operator-curated** personal preferences that shape
Claude's runtime decisions but are not formal Iron Rules. Examples:

- "Conservative sizing on weekends — multiply size by 0.7 for any trade
  decided between Fri 18:00 UTC and Sun 18:00 UTC."
- "Halt all entries during macro events flagged in
  `references/crypto/news-velocity-playbook.md`."
- "Prefer BTC/USDT over altcoin pairs during low-confidence regime
  classifications (confidence < 6)."

The runtime brain reads this file every cycle (memory layer of ADR-002
precedence). Preferences here cannot override Iron Laws or Skills, but they
can tighten approvals beyond those baselines.

> **Iron Law 4 exception zone**: only the operator may edit this file. The
> post-mortem cron and the runtime brain MUST NOT auto-modify it. This is
> the one memory file that is purely human-curated. Auto-edits would defeat
> the purpose: these preferences encode the operator's risk personality and
> portfolio context, neither of which the brain has authority over.

## Current preferences

(Empty initially. The operator adds preferences here over time as live
trading reveals risk-personality friction with the default Iron-Rule +
Skill baseline.)

## Format convention

Each preference is a short imperative sentence with a numeric or boolean
trigger. Avoid vague language ("be careful", "use judgement"); the runtime
brain treats the test rules in `tests/test_skills_lint.py` as a style
mirror — same vague-language penalties apply by convention.

```
### <slug> — <YYYY-MM-DD added>
Trigger: <concrete condition>
Action: <concrete adjustment to size_mult, decision, or veto>
Rationale: <one or two sentences>
```
