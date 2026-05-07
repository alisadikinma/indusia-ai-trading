"""ClaudeOversightHyperopt — Phase 8 hyperopt definition.

This module is consumed in two ways:

1. **Freqtrade CLI path (VPS-only):**

   ::

       freqtrade hyperopt \\
           --hyperopt-loss SharpeHyperOptLoss \\
           --strategy ClaudeOversightStrategy \\
           --config crypto-bot/freqtrade-config/config.json \\
           --hyperopt-path crypto-bot/freqtrade-config/hyperopts \\
           --epochs 5000 \\
           --timerange 20180101-20240101 \\
           --spaces buy sell stoploss roi

   Freqtrade discovers ``ClaudeOversightHyperopt`` (subclass of
   :class:`freqtrade.optimize.hyperopt.IHyperOpt`) and uses it to (a) declare
   the search space (via the ``buy_*`` / ``sell_*`` :class:`IntParameter` /
   :class:`DecimalParameter` attributes already pinned on the strategy) and
   (b) drive the loss function. We delegate buy/sell space resolution to
   the strategy (Freqtrade's default behavior since strategy parameters
   are auto-discovered when ``optimize=True``); this class therefore just
   has to exist and reference :class:`SharpeHyperOptLoss` so the CLI's
   ``--hyperopt-loss SharpeHyperOptLoss`` flag has a class to wire up.

2. **Custom runner path (Windows dev box, see infra/scripts/run_hyperopt.py):**

   The Freqtrade CLI calls ``ccxt.binance().load_markets()`` during init,
   which is geofenced from this Windows dev box. Our custom runner sidesteps
   the CLI by calling :class:`SharpeHyperOptLoss.hyperopt_loss_function`
   directly against simulated trade results derived from the strategy's
   rule-set on Postgres-backed OHLCV. The runner imports
   :class:`ClaudeOversightHyperopt` only for the class-level metadata
   (loss function reference + strategy version label).

   See ADR-003 (``docs/decisions/2026-05-07-003-strategy-v1-hyperopt-params.md``)
   for the full runner-vs-CLI rationale and the smoke-vs-full-sweep decision.
"""
from __future__ import annotations

from freqtrade.optimize.hyperopt.hyperopt_interface import IHyperOpt
from freqtrade.optimize.hyperopt_loss.hyperopt_loss_sharpe import SharpeHyperOptLoss


# Strategy version tag persisted to brain.hyperopt_results.strategy_version.
# Bump alongside any signature change in ClaudeOversightStrategy.
STRATEGY_VERSION = "ClaudeOversightStrategy-v1"


class ClaudeOversightHyperopt(IHyperOpt):
    """Phase 8 hyperopt class for ClaudeOversightStrategy.

    The buy/sell search dimensions live on the strategy itself (auto-detected
    by Freqtrade because the parameters are declared with ``optimize=True``).
    We therefore inherit IHyperOpt's defaults for everything except the loss
    function reference: ``SharpeHyperOptLoss`` is the chosen objective per
    Phase 8 plan (Sharpe maximization → loss = -Sharpe).
    """

    # Tagged for runner-side discovery.
    loss_class = SharpeHyperOptLoss
    strategy_version = STRATEGY_VERSION
