"""infra.backtest — Phase 9 walk-forward orchestrator package.

The orchestrator (``infra.backtest.walk_forward``) drives the Iron Law 2
gate: a strategy version cannot graduate to paper trade until all 5 OOS
folds clear Sharpe>1.5, MaxDD<25%, profit factor>1.4, trades>=100.

Fold computation is delegated to ``infra.scripts.walkforward_folds`` (the
Phase 0.5 regime-aware fold-spec generator) so there is one canonical
fold contract across the project.
"""
