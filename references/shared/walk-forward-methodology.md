# Walk-Forward Methodology

> Source attribution: distilled from NotebookLM notebook `ai-trading-research`
> (id `14c3a70f-c265-456e-a937-9281af14cae1`, 84 sources) plus standard
> Pardo (2008) walk-forward methodology where the notebook flagged gaps.
> Last refreshed: 2026-05-07. Per ADR-002 references RAG layer.

Walk-forward analysis is the **primary backtest validation gate** for both
the crypto and Polymarket bots. It is how the project moves from "the
strategy fit historical data" (low value) to "the strategy generalizes to
periods it has never seen" (the only assertion that matters for live
capital). Per the project's Iron Law 2, no live trade is approved until
all four gate criteria (Sharpe > 1.5, MaxDD < 25%, profit factor > 1.4,
≥ 100 trades) pass in **all 5 OOS folds**.

## Topic 1 — Rolling vs anchored windows + WFE ratio

Modern open-source trading frameworks default to **rolling train/test
windows** rather than anchored (expanding) windows. The `vectorbt-backtesting-skills`
repository ships a dedicated `walk-forward.md` rule file that calculates a
**Walk-Forward Efficiency (WFE) ratio** — the ratio of out-of-sample
performance to in-sample performance — as its primary overfitting detector
[Source: NotebookLM ai-trading-research, citation 1, source
`39ec99b1-67d2-48d4-8b7c-6ca8cba70387` `walk-forward.md` rule file]. The
`maverick-mcp` server's VectorBT-powered backtesting engine and the
`FinClaw` AI-native engine likewise integrate walk-forward optimization
natively rather than as a post-hoc check
[Source: NotebookLM ai-trading-research, citations 3–5].

**Anchored vs rolling tradeoff** (Pardo methodology, supplemental — the
notebook flagged this gap explicitly):

- **Anchored (expanding) window:** train data accumulates from time 0; each
  fold's training set is strictly larger than the previous. Better for
  strategies whose edge depends on long-memory regimes (e.g., 5-year
  trend-following). Risk: late folds are dominated by stale early data,
  blunting recent regime sensitivity.
- **Rolling (sliding) window:** training set has fixed length, slides
  forward. Better for regime-sensitive strategies and shorter-horizon
  signals. Risk: discards potentially informative older data.

This project's plan §6 specifies **expanding-window folds (train 2018→T,
test (T, T+1y))** [Source: docs/plans/2026-05-06-ai-trading-247.md §Phase 9]
— anchored. The choice reflects the trend-follower v1 strategy whose edge
is partly long-memory regime structure.

**Actionable rule for the brain:** WFE ratio < 0.5 is a hard veto, regardless
of whether IS metrics looked good. A strategy that delivers half its
in-sample performance out-of-sample is curve-fit, not robust.

## Topic 2 — Hyperparameter overfitting detection + statistical robustness

The `claude-trading-skills` repository encodes overfitting detection as
deterministic skills, not as ad-hoc reviewer checks
[Source: NotebookLM ai-trading-research, citations 6–7, source
`a74e4525-cadb-45b3-b69e-722d50bbd7f3`]:

- **`strategy-pivot-designer`** — detects backtest iteration stagnation via
  four deterministic triggers: improvement plateau, **overfitting proxy**,
  cost defeat, and tail risk. When parameter tuning reaches a local optimum
  and the overfitting proxy fires, the skill forces the agent to propose a
  structurally different strategy rather than continuing to tune.
- **`edge-strategy-reviewer`** — deterministic 0–100 quality gate scoring
  drafts on 8 criteria including **overfitting risk, sample adequacy, and
  regime dependency**. PASS / REVISE / REJECT verdicts gate exports;
  curve-fitted threshold conditions are explicitly penalized.

For statistical robustness — the closest the source-set gets to "statistical
significance gates" — the reviewed frameworks employ a battery of
**Monte Carlo + perturbation tests** before live deployment
[Source: NotebookLM ai-trading-research, citation 8, `vectorbt-backtesting-skills`]:

- Monte Carlo trade shuffling
- Noise injection on the OHLCV feed
- Parameter sensitivity sweeps (single-axis perturbation)
- Entry/exit delay tests (does a 1-bar lag destroy the edge?)
- Cross-symbol validation (does the same strategy survive on a correlated
  pair it was not optimized on?)

The `backtest-expert` skill enforces realistic OOS validation by modelling
slippage, transaction costs, and survivorship-bias elimination
[Source: NotebookLM ai-trading-research, citation 9, source
`a74e4525-cadb-45b3-b69e-722d50bbd7f3` `backtest-expert`].

**Actionable rule for the brain:** if a strategy passes raw OOS Sharpe but
fails the entry/exit delay test (1-bar lag drops Sharpe by > 50%), it is
likely exploiting bar-close fill mispricing. Default to veto and log to
journal as `decision='halt'` with reason "edge sensitive to fill-timing
assumption".

## Topic 3 — OOS fold sizing + Pardo methodology

The provided source corpus does **not** explicitly cover Pardo's fold-sizing
rules of thumb; the notebook flagged this gap and recommended independent
verification [Source: NotebookLM ai-trading-research, "what is not in the
sources" footnote in walk-forward query response]. Standard Pardo (2008,
*The Evaluation and Optimization of Trading Strategies*) heuristics:

- **OOS fold = 20–30% of IS window length.** If IS = 4 years, OOS ≈ 1 year.
  This project's plan uses 1-year OOS folds against expanding IS, consistent
  with the upper end of Pardo
  [Source: docs/plans/2026-05-06-ai-trading-247.md §Phase 9].
- **Minimum 5 folds.** Fewer folds give insufficient evidence that the
  strategy generalizes; more folds shrink each OOS test below the 100-trade
  significance threshold. The project's "5 OOS folds" gate aligns.
- **≥ 100 trades per fold.** Below this, the per-fold metrics are dominated
  by noise from individual trades. The project's gate enforces this
  explicitly [Source: docs/plans/2026-05-06-ai-trading-247.md §Phase 9 gate
  criteria].
- **Re-optimize hyperparameters at each fold boundary.** The point of
  walk-forward is to test the *re-optimization process* itself, not a
  single static parameter set. FreqAI auto-retrains per fold in this
  project's setup [Source: docs/plans/2026-05-06-ai-trading-247.md §Phase
  7 freqai block, `live_retrain_hours: 24`].

**Actionable rule for the brain:** if a backtest report shows < 100 trades
in any single OOS fold, treat the per-fold metrics as informational only —
never use them to clear an Iron Law 2 gate. Demand a longer test window or
a higher-frequency strategy.

## Topic 4 — Lopez de Prado techniques (CPCV, Triple-Barrier, Meta-Labeling, DSR)

Marcos Lopez de Prado's *Advances in Financial Machine Learning* is the
definitive guide for crypto quant ML — the techniques explicitly address
the failure modes that simple walk-forward + Sharpe miss
[Source: Lopez de Prado cheat sheet via NotebookLM backtest-data-sources,
citation 5 — r/quant cheat sheet repository].

**Combinatorial Purged Cross-Validation (CPCV):** Standard K-fold CV
fails in finance because neighbouring data points are highly correlated
(autocorrelated returns, overlapping label horizons). CPCV "purges"
training-set rows that overlap with the test set (label leakage) AND
"embargoes" a buffer period after the test set (information leakage).
For a project with 5 OOS folds, CPCV produces a more conservative — and
correct — generalization estimate than naive walk-forward.

**Triple-Barrier labeling:** Classifies each event by which of three
barriers hits first: an upper take-profit barrier, a lower stop-loss
barrier, or a vertical time-limit barrier. Beats fixed-horizon labeling
because it captures the intraday path, not just terminal return — a
trade that hits TP in 2 hours is different from one that drifts to TP
over 5 days, even if PnL is identical.

**Meta-Labeling:** Train a *secondary* model whose only job is to
decide "should we take this trade, and if so, how big?" given the
primary model's signal. Boosts F1 by filtering whipsaw signals and
calibrating bet size — particularly powerful for crypto where the
primary signal often fires correctly but at unhelpful sizes.

**Deflated Sharpe Ratio (DSR):** Corrects raw Sharpe for selection
bias — if you tested 100 strategies, the best one will look great by
chance alone. DSR requires tracking the number of trials AND the
variance of Sharpe ratios across them; it tells you the true
probability that the surviving strategy's edge is real, not luck.
For this project's Iron Law 2 gate (Sharpe > 1.5), the gate should be
read as **DSR > 1.5**, not raw Sharpe > 1.5 — otherwise hyperopt
search will mechanically generate a "passing" strategy by chance.

[Source: NotebookLM backtest-data-sources, citation 5 — Lopez de Prado
methodology cheat sheet] [Source: NotebookLM backtest-data-sources,
citation 51 — academic stop-out rules + serial correlation analysis]

**Actionable rule for the brain:** When the operator reports a
backtest passes the Iron Law 2 gate (Sharpe > 1.5, MaxDD < 25%, PF
> 1.4 across 5 OOS folds), the brain MUST ask whether the gate was
evaluated using DSR (Deflated Sharpe) or raw Sharpe. If raw Sharpe AND
the operator did > 20 hyperparameter iterations to reach the
passing version, the result is plausibly selection-bias artefact;
demand DSR recomputation before clearing.

## Quick Decision Heuristics

- If WFE ratio < 0.5, veto promotion to paper-trade — strategy is curve-fit.
- If any single OOS fold has < 100 trades, the gate criteria are
  statistically meaningless for that fold; re-run with longer window.
- If hyperparameter tuning reached a local optimum and the overfitting proxy
  fires, do not re-tune — propose a structurally different strategy instead.
- If a 1-bar entry/exit delay drops OOS Sharpe by > 50%, the edge depends
  on bar-close fill assumptions; default to veto in live.
- If IS Sharpe > 2.0 but OOS Sharpe < 1.0 in any fold, treat as overfit
  signal regardless of average across folds.
- If a strategy passes 5 OOS folds but cross-symbol validation fails on a
  correlated pair, the edge is symbol-specific overfitting — do not treat
  the multi-fold pass as generalization evidence.
- If Monte Carlo trade-shuffle 5th percentile equity curve goes negative,
  the realized historical sequence may have been favourable luck — demand
  a longer IS window or alternative entry rule.
- If raw Sharpe is the gate metric AND > 20 hyperopt iterations were run
  to reach passing, demand DSR (Deflated Sharpe) recomputation —
  selection-bias artefact is the default assumption, not the exception.
- If ML strategy uses fixed-horizon labels (e.g. "1h forward return"),
  reject in favor of Triple-Barrier labeling — fixed-horizon ignores
  intraday path and misclassifies trades that hit SL before TP.
- If standard K-fold CV is used instead of CPCV (purge + embargo) on
  autocorrelated returns, OOS scores are inflated by label leakage —
  demand CPCV re-run before gate.
