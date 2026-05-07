"""Phase 7 — FreqAI integration tests.

Validates the ``ClaudeOversightModel`` (XGBoost classifier) wiring:

  * Imports + extends Freqtrade's ``BaseClassifierModel``.
  * ``predict()`` returns Freqtrade's expected (DataFrame, do_predict) tuple
    with predictions in the unit interval.
  * Strategy ``populate_entry_trend`` gates on ``&-prediction > 0.65`` when
    the column exists, falls back to Phase 3 behavior when absent.
  * Feature engineering hooks expose the right column names.
  * Target generator marks the +2% / 16-bar-ahead horizon correctly.

Integration tests (require real Postgres + ``brain.freqai_history``):
  * ``fit()`` writes a row with non-zero AUC + non-empty feature_importance.

Iron Law 3 caveat documented in ``ClaudeOversightModel.fit``:
the post-train INSERT logs+continues on Postgres failure rather than
re-raising. Telemetry is not the bot's primary mission; crashing the
training pipeline because Postgres flickered would leave the bot in an
unknown retrain state. This is a deliberate, scoped exception to
"fail loud" — applies ONLY to the freqai_history hook, not to env validation
or training itself.
"""
from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime
from typing import Any

import numpy as np
import pandas as pd
import pytest


# ---------------------------------------------------------------------------
# Test 1 — module import (TDD red gate)
# ---------------------------------------------------------------------------
def test_claude_oversight_model_imports() -> None:
    """RED gate: importing the model must succeed once Phase 7 ships."""
    from freqaimodels.ClaudeOversightModel import ClaudeOversightModel  # noqa: F401


# ---------------------------------------------------------------------------
# Test 2 — class hierarchy
# ---------------------------------------------------------------------------
def test_model_extends_base_classifier() -> None:
    from freqtrade.freqai.base_models.BaseClassifierModel import BaseClassifierModel

    from freqaimodels.ClaudeOversightModel import ClaudeOversightModel

    assert issubclass(ClaudeOversightModel, BaseClassifierModel)
    # The two methods we override must exist directly on the subclass.
    assert "fit" in ClaudeOversightModel.__dict__
    assert "predict" in ClaudeOversightModel.__dict__


# ---------------------------------------------------------------------------
# Test 5 — set_freqai_targets correctness
# ---------------------------------------------------------------------------
def test_set_freqai_targets_marks_2pct_4h_horizon_correctly() -> None:
    """Synthetic dataframe: rows 10..15 have a +2.5% close 16 bars ahead.

    Assert ``&-prediction`` target column has 1s exactly at rows 10..15
    and 0s on rows where the future return is below 2%.
    """
    from strategies.ClaudeOversightStrategy import ClaudeOversightStrategy

    n = 60
    close = np.full(n, 100.0)
    # Spike +2.5% at indexes 26..31 (= rows 10..15 + horizon 16).
    close[26:32] = 102.5
    df = pd.DataFrame(
        {
            "date": pd.date_range("2024-01-01", periods=n, freq="15min", tz="UTC"),
            "open": close - 0.05,
            "high": close + 0.1,
            "low": close - 0.1,
            "close": close,
            "volume": 1000.0,
        }
    )

    # set_freqai_targets is bound to instance; instantiate without going
    # through Freqtrade's full IStrategy init (which needs config dict).
    strat = ClaudeOversightStrategy.__new__(ClaudeOversightStrategy)
    out = strat.set_freqai_targets(df.copy(), metadata={"pair": "BTC/USDT"})

    assert "&-prediction" in out.columns
    assert (out["&-prediction"].iloc[10:16] == 1).all(), (
        "rows 10..15 should mark 1 (close 16 bars ahead is +2.5%)"
    )
    # Rows where the future close is the same as current → 0.
    assert (out["&-prediction"].iloc[0:10] == 0).all()
    # The last 16 rows have NaN futures → forced to 0 by the > comparison.
    assert (out["&-prediction"].iloc[-16:] == 0).all()


# ---------------------------------------------------------------------------
# Test 6 — feature_engineering_expand_all column naming
# ---------------------------------------------------------------------------
def test_feature_engineering_expand_all_creates_period_columns() -> None:
    from strategies.ClaudeOversightStrategy import ClaudeOversightStrategy

    n = 80
    rng = np.random.RandomState(7)
    close = 100 + np.cumsum(rng.normal(0, 0.5, n))
    df = pd.DataFrame(
        {
            "date": pd.date_range("2024-01-01", periods=n, freq="15min", tz="UTC"),
            "open": close - 0.05,
            "high": close + 0.2,
            "low": close - 0.2,
            "close": close,
            "volume": 1000.0,
        }
    )

    strat = ClaudeOversightStrategy.__new__(ClaudeOversightStrategy)
    out = strat.feature_engineering_expand_all(df.copy(), period=14, metadata={})

    assert "%-rsi-period_14" in out.columns
    assert "%-adx-period_14" in out.columns
    assert "%-ema_dist-period_14" in out.columns


# ---------------------------------------------------------------------------
# Test 7 — entry gated when prediction below 0.65
# ---------------------------------------------------------------------------
def test_strategy_entry_gated_on_prediction_above_0_65() -> None:
    """Rule conditions satisfied but &-prediction < 0.65 → no entries."""
    from strategies.ClaudeOversightStrategy import ClaudeOversightStrategy

    n = 50
    close = np.linspace(100, 130, n)
    df = pd.DataFrame(
        {
            "date": pd.date_range("2024-01-01", periods=n, freq="15min", tz="UTC"),
            "open": close - 0.05,
            "high": close + 0.2,
            "low": close - 0.2,
            "close": close,
            "volume": 1000.0,
            # All rule conditions satisfied:
            "ema_fast": close - 0.5,  # > ema_slow
            "ema_slow": close - 1.0,
            "adx14": 30.0,  # > 25
            # FreqAI gate: predictions below threshold → must veto.
            "&-prediction": 0.30,
        }
    )

    strat = ClaudeOversightStrategy.__new__(ClaudeOversightStrategy)
    out = strat.populate_entry_trend(df.copy(), metadata={"pair": "BTC/USDT"})

    # No entries despite rule conditions firing.
    if "enter_long" in out.columns:
        assert (out["enter_long"].fillna(0) == 0).all(), (
            "FreqAI gate should block all entries when prediction < 0.65"
        )


# ---------------------------------------------------------------------------
# Test 8 — backward compat: no &-prediction column → Phase 3 behavior
# ---------------------------------------------------------------------------
def test_strategy_entry_unchanged_when_freqai_column_absent() -> None:
    """Without &-prediction column, gate defaults to 1.0 → rules behave as Phase 3."""
    from strategies.ClaudeOversightStrategy import ClaudeOversightStrategy

    n = 50
    close = np.linspace(100, 130, n)
    df = pd.DataFrame(
        {
            "date": pd.date_range("2024-01-01", periods=n, freq="15min", tz="UTC"),
            "open": close - 0.05,
            "high": close + 0.2,
            "low": close - 0.2,
            "close": close,
            "volume": 1000.0,
            "ema_fast": close - 0.5,
            "ema_slow": close - 1.0,
            "adx14": 30.0,
            # No &-prediction column.
        }
    )

    strat = ClaudeOversightStrategy.__new__(ClaudeOversightStrategy)
    out = strat.populate_entry_trend(df.copy(), metadata={"pair": "BTC/USDT"})

    assert "enter_long" in out.columns
    # Rule conditions fully satisfied → entries should fire (default gate = 1.0).
    assert (out["enter_long"].fillna(0).sum()) > 0, (
        "Rule conditions met and no FreqAI column → entries must fire (Phase 3 fallback)"
    )


# ---------------------------------------------------------------------------
# Test 3 + 4 — predict signature + unit-interval values
# These tests bypass the heavy Freqtrade train pipeline by manually
# constructing a mocked datakitchen + a trained XGBoost model object,
# then calling our model's predict via the BaseClassifierModel pathway.
# ---------------------------------------------------------------------------
class _FakeDataKitchen:
    """Minimal stand-in for FreqaiDataKitchen used by predict()."""

    def __init__(self, label_list: list[str], features: pd.DataFrame) -> None:
        self.label_list = label_list
        self.training_features_list = list(features.columns)
        self.data_dictionary: dict[str, Any] = {}
        self.data: dict[str, Any] = {"labels_std": {0: 0, 1: 0}}
        self.do_predict = np.ones(len(features), dtype=int)
        self.DI_values = np.zeros(len(features))
        self._features = features
        self.feature_pipeline = _FakeFeaturePipeline()

    def find_features(self, df: pd.DataFrame) -> None:
        # No-op: training_features_list already set.
        pass

    def filter_features(
        self,
        df: pd.DataFrame,
        feature_list: list[str],
        training_filter: bool = False,
    ) -> tuple[pd.DataFrame, pd.DataFrame | None]:
        return self._features, None


class _FakeFeaturePipeline:
    def __init__(self) -> None:
        self._items: dict[str, Any] = {"di": None}

    def transform(
        self, X: pd.DataFrame, outlier_check: bool = False
    ) -> tuple[pd.DataFrame, np.ndarray, Any]:
        outliers = np.ones(len(X), dtype=int)
        return X, outliers, None

    def fit_transform(self, X: pd.DataFrame, y: Any, w: Any) -> tuple[Any, Any, Any]:
        return X, y, w

    def __getitem__(self, key: str) -> Any:
        return self._items.get(key)


def _make_trained_xgb(seed: int = 42):
    """Build a tiny trained XGBClassifier on synthetic 2-class data."""
    from xgboost import XGBClassifier

    rng = np.random.RandomState(seed)
    X = rng.normal(0, 1, size=(200, 5))
    # Binary label correlated with X[:,0]
    y = (X[:, 0] + rng.normal(0, 0.2, 200) > 0).astype(int)
    model = XGBClassifier(n_estimators=20, max_depth=3, eval_metric="auc", verbosity=0)
    model.fit(X, y)
    return model


def test_predict_returns_freqai_tuple_shape() -> None:
    """predict() must return (DataFrame, ndarray-like). DataFrame has &-prediction."""
    from freqaimodels.ClaudeOversightModel import ClaudeOversightModel

    feats = pd.DataFrame(
        np.random.RandomState(1).normal(0, 1, size=(50, 5)),
        columns=[f"feat_{i}" for i in range(5)],
    )
    dk = _FakeDataKitchen(label_list=["&-prediction"], features=feats)

    instance = ClaudeOversightModel.__new__(ClaudeOversightModel)
    instance.model = _make_trained_xgb()
    instance.CONV_WIDTH = 1

    pred_df, do_predict = instance.predict(unfiltered_df=feats.copy(), dk=dk)
    assert isinstance(pred_df, pd.DataFrame)
    assert "&-prediction" in pred_df.columns
    assert len(pred_df) == len(feats)
    assert len(do_predict) == len(feats)


def test_predict_values_in_unit_interval() -> None:
    """The probability column emitted by predict() must lie in [0, 1]."""
    from freqaimodels.ClaudeOversightModel import ClaudeOversightModel

    feats = pd.DataFrame(
        np.random.RandomState(2).normal(0, 1, size=(80, 5)),
        columns=[f"feat_{i}" for i in range(5)],
    )
    dk = _FakeDataKitchen(label_list=["&-prediction"], features=feats)

    instance = ClaudeOversightModel.__new__(ClaudeOversightModel)
    instance.model = _make_trained_xgb()
    instance.CONV_WIDTH = 1

    pred_df, _ = instance.predict(unfiltered_df=feats.copy(), dk=dk)
    # predict_proba lands in unit interval; the &-prediction column is the
    # positive-class probability we expose.
    assert pred_df["&-prediction"].between(0.0, 1.0).all()


# ---------------------------------------------------------------------------
# Test 9 — integration: fit() writes a row to brain.freqai_history
# ---------------------------------------------------------------------------
@pytest.mark.integration
def test_fit_inserts_freqai_history_row() -> None:
    """End-to-end: synthetic features → fit() → row in brain.freqai_history.

    Uses real psycopg connection. If POSTGRES_* env missing the test fails
    loud (no silent skip). The integration marker keeps it off the default
    suite for dev boxes without a live DB.
    """
    import psycopg

    from freqaimodels.ClaudeOversightModel import ClaudeOversightModel

    pair = f"TEST/USDT-{uuid.uuid4().hex[:8]}"

    rng = np.random.RandomState(13)
    n = 1000
    feature_names = [
        "%-return_1h",
        "%-return_4h",
        "%-volatility_1h",
        "%-volume_z_24h",
        "%-rsi-period_14",
    ]
    X = rng.normal(0, 1, size=(n, len(feature_names)))
    # Binary label with real signal in the first feature.
    y = (X[:, 0] + rng.normal(0, 0.3, n) > 0).astype(int)
    train_n = int(n * 0.75)

    train_features = pd.DataFrame(X[:train_n], columns=feature_names)
    train_labels = pd.DataFrame(y[:train_n], columns=["&-prediction"])
    test_features = pd.DataFrame(X[train_n:], columns=feature_names)
    test_labels = pd.DataFrame(y[train_n:], columns=["&-prediction"])

    data_dictionary = {
        "train_features": train_features,
        "train_labels": train_labels,
        "train_weights": np.ones(train_n),
        "test_features": test_features,
        "test_labels": test_labels,
        "test_weights": np.ones(n - train_n),
    }

    # Minimal fake dk that fit() can interact with for pair + model_path metadata.
    class _DK:
        pass

    dk = _DK()
    dk.pair = pair
    dk.full_path = "test_run"
    dk.data_path = "test_run"
    dk.model_filename = "test_model"

    instance = ClaudeOversightModel.__new__(ClaudeOversightModel)
    # Mimic enough of IFreqaiModel state for the fit hook telemetry insert.
    instance.freqai_info = {
        "feature_parameters": {"label_period_candles": 16},
        "data_split_parameters": {"test_size": 0.25},
        "train_period_days": 180,
    }
    instance.model_training_parameters = {
        "n_estimators": 50,
        "max_depth": 3,
        "learning_rate": 0.1,
        "verbosity": 0,
        "n_jobs": 1,
    }
    instance.CONV_WIDTH = 1

    def _no_init_model(*_args, **_kwargs):
        return None

    instance.get_init_model = _no_init_model  # type: ignore[method-assign]

    model = instance.fit(data_dictionary, dk)
    assert model is not None

    # Verify the row landed.
    dsn = (
        f"postgresql://{os.environ['POSTGRES_USER']}:"
        f"{os.environ['POSTGRES_PASSWORD']}@"
        f"{os.environ['POSTGRES_HOST']}:"
        f"{os.environ['POSTGRES_PORT']}/"
        f"{os.environ['POSTGRES_DB']}"
    )
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT auc, feature_importance, train_rows, model_path "
            "FROM brain.freqai_history WHERE pair = %s ORDER BY retrained_at DESC LIMIT 1",
            (pair,),
        )
        row = cur.fetchone()

    assert row is not None, "fit() should have inserted a row to brain.freqai_history"
    auc, feature_importance, train_rows, model_path = row
    assert 0.0 <= float(auc) <= 1.0
    # Synthetic data has real signal — AUC should beat random (0.5).
    assert float(auc) > 0.55, f"AUC {auc} unexpectedly low for separable synthetic data"
    assert isinstance(feature_importance, dict)
    assert len(feature_importance) > 0, "feature_importance must be populated"
    assert int(train_rows) == train_n
    assert model_path  # non-empty

    # Cleanup: this is a test fixture row, not a real retrain. Leaving it
    # in place would pollute the 7-day window that `retrain_health_check`
    # tests sample, and skew dashboard FreqAI calibration response.
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM brain.freqai_history WHERE pair = %s", (pair,))
        conn.commit()
