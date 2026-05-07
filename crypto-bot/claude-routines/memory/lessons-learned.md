# Lessons Learned

> Initialised 2026-05-07 as part of Phase 6 (Memory + Journal helpers +
> Continuous Learning Ops).

## Purpose

This file holds Claude's cumulative wisdom from past trade outcomes for the
crypto bot only (Polymarket has its own under `polymarket-bot/`). It is the
output side of the **post-mortem learning loop**:

- The Phase 6 weekly cron (`infra/scripts/post_mortem_cron.py`) runs every
  Sunday 00:00 UTC. After grouping recent losing trades by failure signature,
  it invokes Claude with `pattern-detector.md` + `post-mortem-protocol.md`
  injected via `--append-system-prompt-file`, then appends ONE entry per
  detected group here, regardless of whether the pattern was structural.
- The runtime brain (5-min oversight loop) **READS** this file every cycle
  via the memory layer of ADR-002 precedence (Iron Laws > Skills >
  References > Memory > Training). It MUST NOT write here — Iron Law 4
  reserves auto-edits to the cron only.

The file is **append-only by convention**. Past entries are immutable
context; new lessons stack at the bottom. Operator may prune via ADR.

## How to read

Each entry is timestamped (UTC date), tagged with the regime + cause, and
cites the `brain_journal.id` range of the trades that produced the lesson.
Example shape:

```
### YYYY-MM-DD — <regime> — <cause>
Trades: brain_journal ids [N, M, ...]
Signature: regime=X, funding_bucket=Y, vol_bucket=Z, signal_type=W
Sample count: <n> (avg pnl <m>%, spread <d>d)
Lesson: <Claude's structured 2-3 sentence takeaway>
```

When `signal-evaluation.md` checklist items 4 and 7 ask "is this trade
similar to past losses", they search this file's `Signature:` lines for
matches. Lessons that point at the same signature as a pending signal lower
that signal's confidence floor by 1, raising the threshold for approval.

## Entries

(Empty initially. The Phase 6 post-mortem cron grows this section. First
entries appear once enough losing trades have accumulated to satisfy the
3-within-7-days threshold the cron uses for grouping.)
