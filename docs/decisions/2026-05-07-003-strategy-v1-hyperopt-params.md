# ADR-003 — Strategy v1 Hyperopt Parameters

## Status

Accepted (provisional — pending VPS full-sweep validation in Phase 9
walk-forward) — 2026-05-07. Authored by Ali Sadikin during Phase 8.

## Context

Phase 8 of the AI-Trading 24/7 plan
(`docs/plans/2026-05-06-ai-trading-247.md` lines 776–797) calls for
hyperoptimization of `ClaudeOversightStrategy`'s rule-set parameters using
Freqtrade's `freqtrade hyperopt` CLI with `SharpeHyperOptLoss` over the
2018–2023 timerange (5000 epochs), then validation on the 2024–2025
out-of-sample window. The output of that phase is a chosen parameter set
that survives an OOS-Sharpe-gate (top-3 must all show OOS Sharpe > 1.0).

The strategy entered Phase 8 with five magic numbers hard-coded in its
rule body:

- EMA fast period (`20`) — the trend-fast leg.
- EMA slow period (`50`) — the trend-slow leg.
- ADX threshold (`25`) — the trendiness filter.
- ATR stop multiplier (`2.0`) — the per-trade stop distance.
- FreqAI prediction threshold (`0.65`) — the ML gate's go/no-go cutoff.

The plan also called for the file path
`freqtrade-fork/user_data/hyperopts/ClaudeOversightHyperopt.py`, but
[ADR-001](2026-05-07-001-mono-repo-multi-bot.md) restructured the repo so
all strategy-side artefacts live under `crypto-bot/freqtrade-config/`.
The hyperopt module therefore lives at
`crypto-bot/freqtrade-config/hyperopts/ClaudeOversightHyperopt.py`. The
plan path predates ADR-001 and is corrected here.

Finally, Phase 7's post-mortem
(`infra/scripts/freqai_train_smoke.py`) established a precedent for
sidestepping the Freqtrade CLI on this Windows dev box because
`ccxt.binance().load_markets()` is geofenced. Phase 8 inherits the same
constraint: the full `freqtrade hyperopt` CLI cannot run locally.

## Decision

### 1. Parameter wrapping

Wrap each of the five tunables in Freqtrade's
`IntParameter` / `DecimalParameter`, declared as class attributes on
`ClaudeOversightStrategy`. Ranges and defaults follow the plan:

| Attribute              | Type                      | Range          | Default | Space   | Justification |
|------------------------|---------------------------|----------------|---------|---------|---------------|
| `buy_ema_fast`         | `IntParameter`            | 10–25          | 20      | `buy`   | Plan §Phase 8 step 1; default = legacy v1 value. |
| `buy_ema_slow`         | `IntParameter`            | 40–80          | 50      | `buy`   | Plan §Phase 8 step 1; default = legacy v1 value. |
| `buy_adx_threshold`    | `IntParameter`            | 20–35          | 25      | `buy`   | Plan §Phase 8 step 1; default = legacy v1 value. ADX < 20 is "no trend"; ADX > 35 is rare and would over-filter. |
| `buy_pred_threshold`   | `DecimalParameter` (2 dp) | 0.55–0.75      | 0.65    | `buy`   | Plan §Phase 8 step 1; default = legacy v1 value. Below 0.55 the ML gate is uninformative; above 0.75 it would abstain too aggressively given XGBoost's typical OOS calibration. |
| `sell_atr_mult`        | `DecimalParameter` (2 dp) | 1.5–3.0        | 2.0     | `sell`  | Plan §Phase 8 step 1; default = legacy v1 value. < 1.5 stops out on noise; > 3.0 risks Iron Law 1 stop-loss-too-far. |

A regression test (`tests/test_hyperopt_param_wrapping.py`) asserts the
type, range, and `space` of every parameter so a future refactor cannot
silently break the search space.

The constraint `buy_ema_fast < buy_ema_slow` is enforced both by a
default-defaults sanity test and by the runner's sampler (`_sample_params`
in `infra/scripts/run_hyperopt.py` rejects samples where `slow ≤ fast`).

### 2. HyperOpt class shell

`crypto-bot/freqtrade-config/hyperopts/ClaudeOversightHyperopt.py`
declares `ClaudeOversightHyperopt(IHyperOpt)` as the metadata holder for
the sweep:

- References the real `freqtrade.optimize.hyperopt_loss.hyperopt_loss_sharpe.SharpeHyperOptLoss`.
- Tags every persisted run with `STRATEGY_VERSION = "ClaudeOversightStrategy-v1"`.
- Inherits IHyperOpt defaults — buy/sell space resolution is delegated to
  the strategy's `optimize=True` parameter attributes (Freqtrade's
  documented auto-detection path).

### 3. Loss function

`SharpeHyperOptLoss` (sign convention: `loss = -sharpe`, so lower-is-better
matches `IHyperOptLoss`). Justification:

- The plan explicitly names this class.
- Sharpe is the gate metric in Phase 9 (`> 1.5` per fold), so optimizing
  Sharpe directly avoids alignment drift between the search objective and
  the validation gate.
- We accept the well-known weakness that Sharpe penalizes upside
  volatility symmetrically. Sortino was considered (penalizes only
  downside volatility) and rejected because the plan locks Sharpe;
  switching the loss function mid-plan would invalidate the Phase 9 gate
  comparison. If Phase 9.5 iteration is triggered and the failure mode is
  "Sharpe-driven overfit", swap to SortinoHyperOptLoss in iteration cycle
  2 with a follow-up ADR.

### 4. Runner choice — custom Windows-friendly sweep, NOT the CLI

Implemented `infra/scripts/run_hyperopt.py` rather than relying on
`freqtrade hyperopt`. Rationale:

- **Geofence:** Freqtrade CLI calls `ccxt.binance().load_markets()` during
  `Backtesting.__init__`, which fails on this Windows dev box with
  `binance {"code":-2014,"msg":"API-key format invalid."}` (no key, the
  load_markets call itself is region-blocked). Phase 7 hit the same wall
  and adopted the "drive Freqtrade internals directly with Postgres data"
  pattern (`infra/scripts/freqai_train_smoke.py`); Phase 8 follows that
  precedent.
- **Cost discipline:** A 5000-epoch full sweep is appropriate on the VPS
  (Hetzner CX22, no geofence) but disproportionate for a smoke validation
  on the dev box. The runner supports any epoch count; we use a 50-epoch
  smoke locally and document the 5000-epoch full sweep as a Phase 9 VPS
  task.
- **Real-data fidelity:** The runner uses real `brain.ohlcv` data (no
  mocks), real `SharpeHyperOptLoss` (no reimplementation), and the same
  rule logic as the strategy's `populate_entry_trend` /
  `populate_exit_trend` / `custom_stoploss` (rule-based — no FreqAI gate
  in the smoke; the FreqAI gate's threshold is sampled and persisted but
  treated as transparent in the simulation, since FreqAI retrain is not
  part of the search-space evaluation cost model).
- **Persistence:** Every epoch lands in `brain.hyperopt_results` (per the
  new migration `005_hyperopt_results.sql`). Track A's Strategy Lab UI
  consumes the table to render top-3 selectors and per-epoch
  equity-curve overlays without coupling to the runner.

### 5. Smoke sweep results (in-sample 2024-H1 + OOS 2024-H2)

Run ID `smoke-001` (50 epochs, BTC/USDT 15m, 2024-01-01 → 2024-07-01,
seed=42, $1k starting balance) — top-3:

| Rank | Sharpe | Trades | Profit Factor | Max DD | EMA fast | EMA slow | ADX | Pred | ATR mult |
|------|--------|--------|---------------|--------|----------|----------|-----|------|----------|
| #1   | +3.50  | 430    | 1.28          | -7.4%  | 13       | 74       | 22  | 0.67 | 1.55     |
| #2   | +3.35  | 222    | 1.54          | -9.0%  | 11       | 54       | 22  | 0.73 | 2.79     |
| #3   | +3.30  | 223    | 1.53          | -7.8%  | 13       | 64       | 22  | 0.66 | 2.74     |

Out-of-sample REPLAY on 2024-07-01 → 2025-01-01 (window the smoke did
NOT see during sweep). The IS-top-3 parameter sets above were re-run
verbatim — no resampling — over the OOS window via the runner's
``--replay-params`` mode (added 2026-05-07 as the spec-review fix to
this ADR; see "Reproducibility" note below). Rows persisted under
``run_id='oos-replay-001'`` (epochs 1, 2, 3 = ranks #1, #2, #3 above):

| Rank | Sharpe (OOS) | Trades | Profit Factor (OOS) | Max DD (OOS) | Win rate |
|------|--------------|--------|---------------------|---------------|----------|
| #1   | +2.64        | 432    | 1.20                | -10.7%        | 36.3%    |
| #2   | +2.04        | 230    | 1.29                |  -8.2%        | 38.7%    |
| #3   | +1.77        | 228    | 1.24                | -10.9%        | 41.2%    |

**Reproducibility (added 2026-05-07 spec-review fix):** prior to this
revision, the OOS table presented narrative numbers that were not
derivable from any row in ``brain.hyperopt_results`` — the sibling run
``oos-001`` is an *independent* random sweep over the OOS window (30
epochs with different params), not a fixed-params replay. The runner now
supports a ``--replay-params <json> --replay-run-id <id>`` mode (see
``infra/scripts/run_hyperopt.py``); the IS-top-3 sets were exported to
``infra/scripts/replay_inputs/oos_replay_001_smoke_top3.json`` and
re-run via:

```bash
python infra/scripts/run_hyperopt.py \
    --pair BTC/USDT \
    --timerange-start 2024-07-01 --timerange-end 2025-01-01 \
    --replay-params infra/scripts/replay_inputs/oos_replay_001_smoke_top3.json \
    --replay-run-id oos-replay-001
```

The 3 rows in ``brain.hyperopt_results`` for ``run_id='oos-replay-001'``
are now the canonical source for the OOS table above; query via
``SELECT epoch, sharpe, total_trades, profit_factor, max_dd, win_rate,
parameters FROM brain.hyperopt_results WHERE run_id='oos-replay-001'
ORDER BY epoch ASC;``.

**Verification gate satisfied:** All 3 IS-top sets show OOS Sharpe > 1.0
(plan §Phase 8 verification line 793). #1 is the most robust (OOS Sharpe
2.64, fewest sign-changes between IS and OOS). The independent random
sweep ``oos-001`` (top-3 OOS Sharpe 2.53 / 1.34 / 1.22) provides a
secondary cross-check on the same window with different params; both
runs satisfy the gate.

### 6. Chosen set (provisional)

```
buy_ema_fast       = 13
buy_ema_slow       = 74
buy_adx_threshold  = 22
buy_pred_threshold = 0.67
sell_atr_mult      = 1.55
```

**Reasoning:**

- Highest combined Sharpe (IS 3.50 + OOS 2.64) with the smallest IS→OOS
  drop (24%) of the three candidates.
- 430 IS trades and 432 OOS trades exceed the Phase 9 gate's `≥ 100
  trades per fold` floor by a wide margin → statistical confidence.
- ADX threshold = 22 means the strategy enters trends earlier than the
  legacy v1 (`25`); paired with a fast EMA = 13 (vs legacy 20) the entry
  is more responsive. The longer slow EMA (74 vs 50) keeps the trend
  filter durable against shorter-duration false signals.
- Tighter ATR stop (1.55 vs legacy 2.0) is the failure-mode trade-off.
  Slightly higher stop-out frequency, but profit factor stays > 1.20 OOS
  → the wins still outsize the losses in aggregate.

**Pinning policy:** the chosen set is **NOT** written to
`crypto-bot/freqtrade-config/config.json` in this ADR. Two reasons:

1. The full 5000-epoch sweep on 2018-2023 IS data (the plan's prescribed
   timerange) has not yet run — that requires the VPS. Pinning a
   smoke-derived set into `config.json` would make every paper-trade run
   inherit smoke-only optimization, defeating Phase 9's gate.
2. Phase 9 walk-forward (5 OOS folds) is the architectural validation
   step. Pinning before walk-forward would couple two phases; keeping
   the parameters as Freqtrade params-file-loadable defaults (via the
   legacy values on the strategy class) preserves the option to either
   load the chosen set explicitly via `--strategy-path … --params-file …`
   or to override with the walk-forward-winning set after Phase 9.

When Phase 9 completes, the ADR-update path is:

- If walk-forward agrees with the smoke choice → pin in `config.json`
  via a small follow-up ADR (ADR-00X-strategy-v1-chosen-params-pinned).
- If walk-forward selects a different set → supersede this ADR with
  ADR-00X-strategy-v1-chosen-params-walkforward.

### 7. Full sweep handoff (VPS-only)

What still needs to happen on the VPS:

1. `cd /srv/ai-trading && set -a; source .env; set +a`
2. Run the full Freqtrade CLI sweep (CLI works there because Hetzner
   Frankfurt is not Binance-blocked):

   ```bash
   freqtrade hyperopt \
       --hyperopt-loss SharpeHyperOptLoss \
       --strategy ClaudeOversightStrategy \
       --config crypto-bot/freqtrade-config/config.json \
       --strategy-path crypto-bot/freqtrade-config/strategies \
       --hyperopt-path crypto-bot/freqtrade-config/hyperopts \
       --epochs 5000 \
       --timerange 20180101-20240101 \
       --spaces buy sell stoploss
   ```
3. Persist the top-3 epochs back to `brain.hyperopt_results` (operator
   responsibility; alternatively re-run our `run_hyperopt.py` on the VPS
   with `--epochs 5000 --timerange-start 2018-01-01 --timerange-end
   2024-01-01 --run-id full-001` for an apples-to-apples comparison
   against the smoke).
4. Run the OOS replay on 2024-2025 with the top-3 sets; confirm OOS
   Sharpe > 1.0 for all.
5. Update this ADR (or supersede) with the chosen set and pin in
   `config.json`.

The runner is intentionally also VPS-runnable (no Windows-specific code
besides the encoding-safe `print` calls). The same `infra/scripts/run_hyperopt.py`
that produced the smoke sweep can produce the full sweep on the VPS — with
or without the FreqAI gate, depending on whether the operator wants the
search to be rule-only (faster, what we did locally) or rule + FreqAI
(slower, but matches live behavior 1:1).

## Consequences

**Positive:**

- Strategy is hyperopt-ready: 5 wrapped parameters, regression-tested,
  default-preserving.
- Custom runner unblocks parameter exploration on the Windows dev box at
  zero CLI dependency.
- `brain.hyperopt_results` table is queryable by Track A immediately;
  Strategy Lab UI can render the smoke sweep results without waiting for
  the VPS full sweep.
- Smoke-validated chosen set is documented with both IS and OOS Sharpe;
  the OOS Sharpe gate (> 1.0) is satisfied for all top-3.

**Negative:**

- Smoke sweep is rule-only (no FreqAI gate). The chosen set's
  `buy_pred_threshold` is therefore loosely optimized; the VPS full
  sweep with the FreqAI gate enabled may pick a different value.
  Mitigation: the parameter is in the search space; the VPS run will
  resolve it.
- 50 epochs of random search is light coverage of a 5-dim space (~21k
  feasible integer-cell combinations + 26 × 16 = 416 decimal cells per
  integer cell). Acceptable for smoke validation; not acceptable as the
  final answer. The plan's 5000-epoch budget (now Phase 9 follow-up)
  addresses this.
- `config.json` not yet pinned — operator must remember to either (a)
  pass the chosen set explicitly when paper-trading, or (b) accept the
  legacy v1 defaults. Mitigation: this ADR's "Pinning policy" section is
  explicit.

## Alternatives Considered

**1. Pin the smoke-best set to `config.json` immediately (rejected).**
Would conflate Phase 8 smoke optimization with Phase 9 walk-forward
validation. If Phase 9 disagrees we'd have to back the pin out, which is
a config rollback; cleaner to keep the legacy defaults as the floor and
let walk-forward make the binding call.

**2. Run `freqtrade hyperopt` CLI via VPN to bypass the geofence
(rejected).** Operationally fragile, no guarantee the VPN egress IP
isn't also blocked, and adds a dependency that doesn't exist on the VPS
(where the CLI will work natively). Phase 7's pattern of "drive
internals directly with Postgres data" is the established precedent.

**3. SortinoHyperOptLoss instead of SharpeHyperOptLoss (rejected).**
Sortino's downside-only volatility penalty is theoretically better for
asymmetric strategies but the plan locks Sharpe. Switching the loss
function mid-Phase 8 would invalidate the Phase 9 gate's comparability.
Reserve Sortino as a Phase 9.5 iteration option if Sharpe-driven overfit
is the diagnosed failure mode.

**4. TPE sampler via Optuna instead of random search (rejected for the
smoke).** TPE would converge faster but requires more Optuna scaffolding
and is overkill at 50 epochs. The full VPS sweep at 5000 epochs benefits
from Optuna's NSGAIIISampler (Freqtrade's CLI default) — that's where
TPE-class samplers earn their keep, not on smoke runs. Documented for
the VPS handoff.

## References

- Plan: `docs/plans/2026-05-06-ai-trading-247.md` Phase 8 (lines 776–797)
- ADR-001 (mono-repo restructure that moved hyperopt path):
  `docs/decisions/2026-05-07-001-mono-repo-multi-bot.md`
- ADR-002 (references RAG layer; no direct Phase 8 impact but sets the
  Iron Law 4 read-only floor on operator-curated content):
  `docs/decisions/2026-05-07-002-references-rag-layer.md`
- Phase 7 precedent for Postgres-backed Windows-friendly harness:
  `infra/scripts/freqai_train_smoke.py`
- Migration: `infra/migrations/005_hyperopt_results.sql`
- Strategy: `crypto-bot/freqtrade-config/strategies/ClaudeOversightStrategy.py`
- HyperOpt class: `crypto-bot/freqtrade-config/hyperopts/ClaudeOversightHyperopt.py`
- Runner: `infra/scripts/run_hyperopt.py`
- Tests: `tests/test_hyperopt_param_wrapping.py`,
  `tests/test_hyperopt_loss_function.py`,
  `tests/test_hyperopt_replay_mode.py` (added 2026-05-07 spec-review fix)
- Replay input (IS-top-3 from smoke-001):
  `infra/scripts/replay_inputs/oos_replay_001_smoke_top3.json`
- Smoke run_id (`smoke-001`) results: queryable via
  `SELECT * FROM brain.hyperopt_results WHERE run_id='smoke-001' ORDER BY loss ASC;`
- OOS independent-sweep run_id (`oos-001`) results: queryable via
  `SELECT * FROM brain.hyperopt_results WHERE run_id='oos-001' ORDER BY loss ASC;`
- OOS fixed-params replay run_id (`oos-replay-001`, the canonical source for §5
  OOS table): `SELECT * FROM brain.hyperopt_results WHERE run_id='oos-replay-001' ORDER BY epoch ASC;`
