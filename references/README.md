# references/ — RAG Knowledge Layer

The fifth knowledge surface of the Claude oversight brain, per
[`docs/decisions/2026-05-07-002-references-rag-layer.md`](../docs/decisions/2026-05-07-002-references-rag-layer.md).

## Five-tier brain knowledge anatomy

When the brain reasons about a signal during a 5-minute oversight cycle, it
consults five surfaces in this precedence order:

1. **Iron Laws** (`CLAUDE.md` §Iron Laws) — non-negotiable, architecturally
   enforced. Cannot be overridden.
2. **Skills** (`<bot>/claude-routines/skills/*.md`) — operator-curated rules
   for THIS portfolio.
3. **References** (this folder) — external grounded research, distilled from
   NotebookLM notebooks.
4. **Memory** (`<bot>/claude-routines/memory/*.md`) — accumulated learnings
   from live trading.
5. **Training data** (Claude's pretrained knowledge, cutoff Jan 2026) —
   fallback only.

This `references/` layer addresses the gap that training data has cutoffs and
operator-curated skills don't capture every microstructure quirk or regulatory
shift. The two NotebookLM notebooks behind this layer (84 crypto sources +
121 Polymarket sources) are the source of truth for distilled facts.

## Layout

```
references/
├── README.md                            (this file)
├── global-trading-config.md             (Iron Laws + JSON contract + precedence; cross-bot invariant)
├── crypto/                              (crypto-bot specific)
│   ├── exchange-microstructure.md
│   ├── freqtrade-walkforward.md
│   ├── known-failure-modes.md
│   ├── regime-taxonomy.md
│   └── compiled/
│       └── refs-crypto-decision.md      (≤8K tokens, cron inject target)
├── polymarket/                          (polymarket-bot specific)
│   ├── clob-microstructure.md
│   ├── uma-oracle-risk.md
│   ├── edge-sources.md
│   ├── regulatory-cftc.md
│   ├── known-failure-modes.md
│   └── compiled/
│       └── refs-polymarket-decision.md  (≤8K tokens)
└── shared/                              (cross-bot)
    ├── walk-forward-methodology.md
    ├── kelly-criterion.md
    └── claude-oversight-pattern.md
```

## How references reach the brain at runtime

Each routine cron invocation appends the compiled per-bot decision file to
the system prompt:

```
claude --append-system-prompt-file references/<bot>/compiled/refs-<bot>-decision.md \
       --skill <routine-skill-name> ...
```

The compiled file is built by `infra/scripts/compile_refs.py` (Phase J),
which selects only `## Quick Decision Heuristics` sections + first paragraph
per `## ` topic from each source reference. Hard caps at 8K tokens. The full
detail-level files are still readable by any skill that needs deep dive.

## Update workflow

1. Operator runs research in NotebookLM (`nlm research start ...`).
2. Operator queries specific topics (`nlm notebook query <id> "..."`).
3. Operator hand-distills the response into the relevant
   `references/<bot>/<topic>.md` — appending or rewriting sections.
4. Operator runs `python infra/scripts/compile_refs.py --bot <bot>` to
   rebuild the compiled file (hard-fails if token budget exceeded).
5. Operator commits both the source ref edits and the compiled output.

This is intentionally **human-in-the-loop**. Distillation is not a cron job
because the cost of a bad reference (hallucinated rule shipped into runtime)
exceeds the manual update cost. Iron Law 4 ("Claude must not modify its own
discipline files") extends to `references/`.

## Citation discipline

Every fact in a reference file should carry a `[Source: NotebookLM source #N
— title]` tag where N maps to the underlying NotebookLM source. This makes
journal entries traceable: when the brain logs "vetoed signal because
references/crypto/known-failure-modes.md §flash-crash matched current order
book", a reader can follow the citation back to the original research.

Reference files are operator-curated. Anti-placeholder enforcement applies:
no `[TODO]`, `Lorem`, or stub content — if the reference is thin, re-query
NotebookLM and distill harder.
