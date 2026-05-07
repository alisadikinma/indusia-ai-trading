---
name: backtest-diagnostics
description: Read a Phase 9.5 diagnostic JSON and propose 1-3 hypotheses for fixing a failed walk-forward backtest, classified by failure mode and matched to the iteration playbook.
---

# Backtest diagnostics — Phase 9.5 analyst playbook

This skill is invoked **conditionally** during the Phase 9.5 iteration loop —
specifically Phase 9.5.A step 5 — after `infra/scripts/diagnose_backtest_failure.py`
has produced a `iteration-{run_id}-diagnostic.json` report. Never invoked
by the runtime oversight loop.

Model tier per `CLAUDE.md` Model Routing: **HEAVY (Opus)** — capital-at-stake
strategy redesign reasoning.

## Inputs you'll receive

- `diagnostic_report.json` written to `docs/research/iterations/iteration-{run_id}-diagnostic.json`
  by `infra/scripts/diagnose_backtest_failure.py`. Contains:
  - `failure_mode` ∈ {overfit, underfit, strategy_logic, regime_specific, hyperopt_unstable}
  - `sub_checks.overfit` — train/test Sharpe gap %
  - `sub_checks.strategy_vs_ml` — ML vs rule-based comparison (or status=needs_separate_backtest)
  - `sub_checks.per_regime` — per-regime PnL breakdown (or status=unavailable_no_signals)
  - `sub_checks.hyperopt_stability` — top-N OOS Sharpe variance (or status=insufficient_data)
- The original `brain.backtest_runs` row metrics (embedded under `metrics`).
- Plan reference: `docs/plans/2026-05-06-ai-trading-247.md` Phase 9.5.C
  (the fix-option table — failure_mode → effort/days mapping).

## How to analyze

1. **Read `failure_mode`** — this is the diagnostic's classification. Trust
   it as the starting point but cross-check against the four sub-check
   payloads (a sub-check with `status=skipped` does NOT contribute to the
   classification — flag if the operator should re-run with more data).

2. **Pull the matching candidate fixes from the Phase 9.5.C table:**

   | failure_mode       | candidate fix(es) from plan                                                       | effort |
   |--------------------|-----------------------------------------------------------------------------------|--------|
   | overfit            | XGBoost depth 6→4, add L2 reg, longer training window 180→365d                    | 2 days |
   | underfit           | add features (volume profile, order-flow imbalance, funding trend); try ensemble  | 3 days |
   | regime_specific    | regime filter — only trade in trending; veto in ranging                           | 1 day  |
   | hyperopt_unstable  | switch to SharpeHyperOptLossDaily; reduce epochs to 1000; require top-10 OOS pass | 1 day + re-hyperopt |
   | strategy_logic     | replace strategy entirely (mean-rev → momentum, etc.)                             | 7 days |

3. **For each candidate, evaluate fit:**
   - **Iteration budget** — `cycle_n` from `brain.iteration_runs`. Max 3
     before architectural-rethink ADR. If `cycle_n=3` and a fix is being
     proposed, the previous 2 cycles' fixes must be MATERIALLY different
     (not parameter tweaks of each other).
   - **Data sufficiency** — e.g., adding volume-profile features needs
     order-book data we may not have ingested. Flag explicitly if the data
     pipeline must be extended first.
   - **Iron Law 4 compliance** — DO NOT propose changes to:
     - `crypto-bot/freqtrade-config/config.json` (operator-only risk rails)
     - `crypto-bot/claude-routines/skills/trading-discipline.md` (operator-only)
     - any ADR or `references/` content
   - **Iron Law 1 compliance** — DO NOT propose disabling/extending any risk
     rail (max 25% per trade, 3 concurrent, −5% daily loss, −20% MaxDD).

4. **Output 1–3 hypotheses, each with all five required fields below.**
   Pick ONE primary if confidence is high; up to three when the operator
   should A/B compare alternatives.

## What you must NOT do

- **DO NOT** auto-edit `crypto-bot/freqtrade-config/config.json` (Iron Law 4).
- **DO NOT** auto-edit `crypto-bot/claude-routines/skills/trading-discipline.md` (Iron Law 4).
- **DO NOT** auto-edit `references/`, `CLAUDE.md`, or any `docs/decisions/*.md`.
- **DO NOT** silently re-trigger walk-forward. The orchestrator (operator) decides.
- **DO NOT** propose architectural rethink unless `cycle_n >= 3` AND the
  previous cycles' fixes were materially different. Architectural rethink is
  a separate ADR captured via `gaspol-adr`.
- **DO NOT** invent a `failure_mode` not in the canonical list.
- **DO NOT** write to `brain.brain_journal` (Iron Law 5 — append-only by
  trigger; this skill is a READ-ONLY analyst).

## Output format

Single JSON block, no prose outside the JSON:

```json
{
  "failure_mode": "<exact value from diagnostic_report.failure_mode>",
  "diagnostic_run_id": 42,
  "hypotheses": [
    {
      "title": "Reduce XGBoost depth 6→4 and lengthen training window to 365d",
      "rationale": "diagnostic shows train_sharpe=2.5 vs test_sharpe=0.8 (gap 68%). Classic overfit signature. Lower model capacity + more training data is the textbook fix.",
      "expected_improvement": {"metric": "test_sharpe", "from": 0.8, "to": 1.5},
      "effort_days": 2,
      "risk_if_wrong": "model may underfit instead — symptom would be train and test sharpe both <1.5",
      "scope": [
        "crypto-bot/freqtrade-config/strategies/claude_oversight.py (FreqAI hyperparams block)",
        "infra/migrations/008_extend_training_window.sql (if window stored in DB)"
      ]
    }
  ],
  "next_action": "Operator reviews; if accepted, capture via gaspol-adr → insert iteration_runs row → implement → re-run walk_forward.sh"
}
```

Field rules:

- `failure_mode`: must equal `diagnostic_report.failure_mode` verbatim.
- `diagnostic_run_id`: integer matching the `run_id` in the report.
- `hypotheses`: 1–3 entries. Empty array is INVALID — if no hypothesis is
  defensible (e.g., diagnostic flagged `failure_mode=underfit` but every
  sub-check has `status=skipped`), return a SINGLE hypothesis with title
  `"insufficient diagnostic data"` and `effort_days=0`, requesting a re-run.
- `expected_improvement.metric` must match a key in `diagnostic_report.metrics`.
- `effort_days` must match the plan's Phase 9.5.C effort column (or document
  the deviation in `rationale`).
- `scope` lists concrete file paths (not vague "the strategy code").
- `risk_if_wrong`: 1–2 sentences naming the contrary symptom to watch for.

Cross-references:
- `crypto-bot/claude-routines/skills/trading-discipline.md` — operator-only
  Iron Rules. Read before proposing any change that touches risk rails.
- `crypto-bot/claude-routines/skills/known-traps.md` — known regime traps.
  Cross-check any `regime_specific` failure mode against this file.
- `docs/plans/2026-05-06-ai-trading-247.md` Phase 9.5.C — the canonical fix
  table.
- `infra/scripts/diagnose_backtest_failure.py` — the script that produces
  the input JSON.
