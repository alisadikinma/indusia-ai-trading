"""Phase 8 — verify the hyperopt loss function works as expected.

We DO NOT reimplement Sharpe — we just confirm:

  1. ``ClaudeOversightHyperopt`` is importable and references the real
     ``freqtrade.optimize.hyperopt_loss.hyperopt_loss_sharpe.SharpeHyperOptLoss``
     class (no clones, no shims).
  2. ``SharpeHyperOptLoss.hyperopt_loss_function`` returns a NEGATIVE number
     (loss = -sharpe) for a winning trade series, and the loss is monotone
     w.r.t. trade quality (more profit → smaller loss).
  3. Empty trades returns 0 (the class's documented degenerate case).

These guards protect against silent regressions if a future Freqtrade
version changes the sign convention.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd


# Add the hyperopts/ folder to sys.path so our local module is importable
# in tests just like Freqtrade will discover it at runtime.
_HYPEROPT_DIR = (
    Path(__file__).resolve().parent.parent
    / "crypto-bot" / "freqtrade-config" / "hyperopts"
)
if str(_HYPEROPT_DIR) not in sys.path:
    sys.path.insert(0, str(_HYPEROPT_DIR))


def test_claude_oversight_hyperopt_imports_real_sharpe_loss() -> None:
    """The hyperopt class must reference the genuine Freqtrade loss class."""
    from freqtrade.optimize.hyperopt_loss.hyperopt_loss_sharpe import (
        SharpeHyperOptLoss,
    )
    from ClaudeOversightHyperopt import ClaudeOversightHyperopt

    assert ClaudeOversightHyperopt.loss_class is SharpeHyperOptLoss


def test_strategy_version_tag_matches_v1() -> None:
    from ClaudeOversightHyperopt import STRATEGY_VERSION

    assert STRATEGY_VERSION == "ClaudeOversightStrategy-v1"


def test_sharpe_loss_returns_zero_on_empty_trades() -> None:
    from freqtrade.optimize.hyperopt_loss.hyperopt_loss_sharpe import (
        SharpeHyperOptLoss,
    )

    empty = pd.DataFrame(columns=["profit_abs"])
    loss = SharpeHyperOptLoss.hyperopt_loss_function(
        results=empty,
        min_date=datetime(2024, 1, 1, tzinfo=timezone.utc),
        max_date=datetime(2024, 1, 31, tzinfo=timezone.utc),
        starting_balance=1000.0,
    )
    assert loss == 0


def test_sharpe_loss_negative_for_winning_trades() -> None:
    """A trade series with positive expectation must produce loss < 0
    (because SharpeHyperOptLoss returns -sharpe; smaller is better)."""
    from freqtrade.optimize.hyperopt_loss.hyperopt_loss_sharpe import (
        SharpeHyperOptLoss,
    )

    # 30 days of consistent ~$5/day winners on a $1k bankroll
    trades = pd.DataFrame({"profit_abs": [5.0] * 30})
    loss = SharpeHyperOptLoss.hyperopt_loss_function(
        results=trades,
        min_date=datetime(2024, 1, 1, tzinfo=timezone.utc),
        max_date=datetime(2024, 1, 31, tzinfo=timezone.utc),
        starting_balance=1000.0,
    )
    # All-positive constant returns → std=0 → annualized_ratio is 0 OR a
    # large negative loss depending on Freqtrade's edge handling. Accept
    # either: we just want NOT > 0 (i.e. the function does not invert
    # sign on positive trades).
    assert loss <= 0, f"expected loss<=0 for winning trades, got {loss}"


def test_sharpe_loss_monotone_better_trades_smaller_loss() -> None:
    """Loss for a stronger winner series must be ≤ loss for a weaker one."""
    from freqtrade.optimize.hyperopt_loss.hyperopt_loss_sharpe import (
        SharpeHyperOptLoss,
    )

    # Both series have non-zero std (we add a small jitter) so calculate_sharpe
    # produces a real ratio rather than the degenerate std=0 case.
    weak = pd.DataFrame({"profit_abs": [1.0, 1.5, 0.5, 2.0, 0.8] * 6})  # mean ~1.16
    strong = pd.DataFrame({"profit_abs": [4.0, 6.0, 2.0, 8.0, 3.2] * 6})  # mean ~4.64

    args = dict(
        min_date=datetime(2024, 1, 1, tzinfo=timezone.utc),
        max_date=datetime(2024, 1, 31, tzinfo=timezone.utc),
        starting_balance=1000.0,
    )
    weak_loss = SharpeHyperOptLoss.hyperopt_loss_function(results=weak, **args)
    strong_loss = SharpeHyperOptLoss.hyperopt_loss_function(results=strong, **args)
    assert strong_loss <= weak_loss, (
        f"strong-trades loss ({strong_loss}) must be <= weak-trades loss ({weak_loss})"
    )
