"""Phase 8 — TDD step 1: ClaudeOversightStrategy parameters must be wrapped in
Freqtrade's IntParameter / DecimalParameter so the hyperopt search space is
discoverable.

The strategy currently uses bare numeric literals (EMA20, EMA50, ADX>25,
2*ATR, &-prediction>0.65). Phase 8 wraps each into a hyperoptable parameter
attribute on the class so ``freqtrade hyperopt`` (or our custom runner) can
sweep their values. This test asserts the wrapping has happened.

Expected ranges (from plan + ADR-003):
  * buy_ema_fast       — IntParameter(low=10,  high=25)
  * buy_ema_slow       — IntParameter(low=40,  high=80)
  * buy_adx_threshold  — IntParameter(low=20,  high=35)
  * sell_atr_mult      — DecimalParameter(low=1.5, high=3.0)
  * buy_pred_threshold — DecimalParameter(low=0.55, high=0.75)

Naming convention follows Freqtrade docs: ``buy_*`` for entry-side params
(``space='buy'``), ``sell_*`` for exit-side (``space='sell'``).
"""
from __future__ import annotations

from freqtrade.strategy import DecimalParameter, IntParameter


def test_buy_ema_fast_is_intparameter_with_correct_range() -> None:
    from strategies.ClaudeOversightStrategy import ClaudeOversightStrategy

    p = ClaudeOversightStrategy.buy_ema_fast
    assert isinstance(p, IntParameter), (
        f"buy_ema_fast must be an IntParameter, got {type(p).__name__}"
    )
    assert p.low == 10, f"buy_ema_fast.low expected 10, got {p.low}"
    assert p.high == 25, f"buy_ema_fast.high expected 25, got {p.high}"
    assert p.space == "buy"
    assert p.optimize is True


def test_buy_ema_slow_is_intparameter_with_correct_range() -> None:
    from strategies.ClaudeOversightStrategy import ClaudeOversightStrategy

    p = ClaudeOversightStrategy.buy_ema_slow
    assert isinstance(p, IntParameter)
    assert p.low == 40
    assert p.high == 80
    assert p.space == "buy"
    assert p.optimize is True


def test_buy_adx_threshold_is_intparameter_with_correct_range() -> None:
    from strategies.ClaudeOversightStrategy import ClaudeOversightStrategy

    p = ClaudeOversightStrategy.buy_adx_threshold
    assert isinstance(p, IntParameter)
    assert p.low == 20
    assert p.high == 35
    assert p.space == "buy"
    assert p.optimize is True


def test_sell_atr_mult_is_decimalparameter_with_correct_range() -> None:
    from strategies.ClaudeOversightStrategy import ClaudeOversightStrategy

    p = ClaudeOversightStrategy.sell_atr_mult
    assert isinstance(p, DecimalParameter)
    # DecimalParameter low/high values are stored as float
    assert float(p.low) == 1.5
    assert float(p.high) == 3.0
    assert p.space == "sell"
    assert p.optimize is True


def test_buy_pred_threshold_is_decimalparameter_with_correct_range() -> None:
    from strategies.ClaudeOversightStrategy import ClaudeOversightStrategy

    p = ClaudeOversightStrategy.buy_pred_threshold
    assert isinstance(p, DecimalParameter)
    assert float(p.low) == 0.55
    assert float(p.high) == 0.75
    assert p.space == "buy"
    assert p.optimize is True


def test_ema_slow_strictly_greater_than_ema_fast_at_default() -> None:
    """Sanity: defaults must satisfy ema_fast < ema_slow (else strategy is
    always-flat). This protects against operator typo when pinning a chosen
    set in config.json."""
    from strategies.ClaudeOversightStrategy import ClaudeOversightStrategy

    fast = ClaudeOversightStrategy.buy_ema_fast.value
    slow = ClaudeOversightStrategy.buy_ema_slow.value
    assert fast < slow, (
        f"buy_ema_fast default ({fast}) must be < buy_ema_slow default ({slow})"
    )
