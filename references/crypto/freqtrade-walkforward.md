# Freqtrade Walk-Forward Methodology

> Distilled from NotebookLM notebook `14c3a70f-c265-456e-a937-9281af14cae1`
> (`ai-trading-research`, 84 sources). Last refreshed: 2026-05-07.
> Per ADR-002 references RAG layer.
>
> **Source-coverage note:** the notebook explicitly flagged that it has thin
> Freqtrade-specific coverage (Freqtrade appears only as a brief plugin
> mention). Walk-forward concepts ARE well-covered via adjacent
> frameworks (vectorbt-backtesting-skills, maverick-mcp, claude-trading-
> skills/backtest-expert). Freqtrade-specific content (StoplossGuard,
> MaxDrawdown, CooldownPeriod, FreqAI XGBoost feature engineering, ATR
> trailing stop calibration) treated as hint-only and re-validate against
> Freqtrade upstream docs.

## Topic 1 — Hyperparameter overfitting pitfalls

Over-optimizing strategy parameters is described as a "massive trap" in
algorithmic trading: traders tweak until paper-trade equity curves look
flawless, then strategies fail instantly live
[Source: NotebookLM source #3 — overfitting trap pattern].

When AI agents generate strategies via evolutionary systems, a specific
failure mode emerges: **the AI evolves toward the METRIC rather than the
MARKET** — maximizing Sharpe in-sample without building a real edge
[Source: NotebookLM source #4 — evolutionary AI metric-vs-market trap].

Mitigation: the `strategy-pivot-designer` skill uses an "overfitting proxy"
to detect when tuning has reached a curve-fitted local optimum
[Source: NotebookLM source #5 — overfitting proxy detector].

**Actionable rule for the brain:** Reject backtest gate-pass if the
in-sample-vs-OOS Sharpe ratio degrades > 50% across folds. A strategy
that's "Sharpe 2.5 in-sample, 0.8 OOS" is overfit, not real edge.

## Topic 2 — Walk-forward validation methodology

Walk-forward optimization is a critical validation step. The
`vectorbt-backtesting-skills` repo uses rolling train/test optimization
and calculates a **Walk-Forward Efficiency (WFE) ratio** to score
robustness [Source: NotebookLM source #6 — vectorbt WFE ratio]
[Source: NotebookLM source #7 — vectorbt rolling train/test pattern].

`maverick-mcp` and `claude-trading-skills` mandate walk-forward
optimization for out-of-sample testing — strategies must survive
simulated OOS data before live deploy [Source: NotebookLM source #8 —
maverick-mcp walk-forward gate] [Source: NotebookLM source #9 —
backtest-expert OOS requirement].

**Project-specific gates** (per Iron Law 2 in CLAUDE.md): all 5 OOS folds
must pass: Sharpe > 1.5, MaxDD < 25%, profit factor > 1.4, ≥ 100 trades
per fold. Failure → Phase 9.5 iteration loop, max 3 cycles, then
architectural rethink ADR.

**Actionable rule for the brain:** Reject any signal whose underlying
strategy hasn't passed walk-forward in ≥ 5 OOS folds AT THE GATE
THRESHOLDS (Sharpe > 1.5, MaxDD < 25%, PF > 1.4). If the journal shows
the strategy is in iteration loop cycle ≥ 2, halve the size_mult.

## Topic 3 — Freqtrade-specific protections (HINT, validate)

**External (not in notebook, validate against Freqtrade docs at deploy):**

- **StoplossGuard:** halts trading on the pair if N consecutive trades
  hit stoploss within a lookback period. Tune `lookback_period` and
  `trade_limit` per pair volatility profile.
- **MaxDrawdown:** halts globally when drawdown exceeds threshold over
  lookback window. Distinct from the Iron Law 1 −20% from-peak kill
  switch (which is OS-level, not Freqtrade-level).
- **CooldownPeriod:** prevents re-entry on same pair for N seconds after
  exit. Mitigates oscillation in choppy regimes.
- **FreqAI XGBoost feature engineering:** standard practice = engineered
  features beat raw OHLCV (returns, RSI, momentum-z, vol-z, regime
  encoding). Re-trains per `train_period_days` interval. Drift detection
  required.
- **ATR trailing stop:** Iron Law 1 mandates 2× ATR(14) trailing per-trade.
  Tune `atr_multiplier` only with operator approval; lower mult
  (e.g. 1.5×) increases stop-out frequency.

**Actionable rule for the brain:** If a signal arrives during a
StoplossGuard-active window or CooldownPeriod-active window, treat as
no_action — the body will reject the entry anyway. Don't waste cycle
budget on signals the body will block.

## Topic 4 — In-sample vs out-of-sample protocol

The vectorbt skill files explicitly require: optimize parameters on a
training window, validate on a holdout window, repeat with rolling
window, score consistency [Source: NotebookLM source #6 — rolling
train/test optimization].

If parameters chosen on fold N's training set degrade > 30% on fold N's
test set across the 5 folds, the strategy has not learned a stable edge.

**Actionable rule for the brain:** Cross-check the strategy version that
generated a signal against `brain.backtest_runs` — if the most recent
backtest run for that strategy had > 30% IS-vs-OOS Sharpe degradation,
downgrade the signal's confidence cap to 5/10 maximum.

## Quick Decision Heuristics

- Backtest IS-vs-OOS Sharpe degradation > 50% → reject strategy entirely.
- Backtest IS-vs-OOS Sharpe degradation 30–50% → accept signals at
  confidence ≤ 5 only.
- Strategy currently in iteration loop cycle ≥ 2 → halve size_mult.
- Walk-forward fold count < 5 OR any single fold failed gate → veto all
  new entries until re-validation.
- StoplossGuard or CooldownPeriod active for the pair → no_action; do
  not even spend cycle budget on signal evaluation.
- Strategy lacks documented overfitting-proxy check in its config →
  request operator validation before approving any signals.
- WFE ratio (Walk-Forward Efficiency) < 0.5 = strategy not robust to
  shifting markets; reject.
