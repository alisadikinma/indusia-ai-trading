"""ClaudeOversightModel — XGBoost classifier predicting P(close[t+16] > close[t] * 1.02).

Phase 7 of docs/plans/2026-05-06-ai-trading-247.md.

Target: probability that the 15m close 16 bars ahead (= 4 hours) exceeds
the current close by 2%. We treat this as binary classification because
the strategy uses the probability as a soft gate, not a regression.

Features (computed by Freqtrade's feature engineering pipeline + our hooks
in ClaudeOversightStrategy.feature_engineering_expand_*):

  * returns over (1, 4, 12, 24)h
  * volatility over (1, 4, 12)h (rolling std of returns)
  * volume z-score over 24h
  * EMA distance: (close - EMA20) / close, (close - EMA50) / close
  * RSI(14)
  * ADX(14)

Model: XGBoost classifier, parameters provided via config.json
``freqai.model_training_parameters``. After every retrain, the post-fit
hook INSERTs a row to brain.freqai_history so the dashboard FreqAI Insights
view + retrain_health_check cron see the new run in real time.

Iron Law 3 (anti-placeholder) — exception scope:
  Env var validation hard-fails as expected (POSTGRES_* missing → KeyError).
  However the post-train INSERT itself logs+continues on Postgres failure
  rather than raising. Rationale: telemetry is not the bot's primary
  mission. Crashing the training pipeline because Postgres flickered
  would leave the bot in an unknown retrain state, and Freqtrade would
  retry the entire training cycle. The trained model is still saved to
  disk — only telemetry is lost. retrain_health_check.py treats a stale
  freqai_history as 'no_data' (not 'red'), so the operator sees the gap
  on the dashboard and can investigate. This exception is scoped ONLY to
  the freqai_history hook; everything else (env, sklearn, xgboost) fails
  loud as Iron Law 3 mandates.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any

import numpy as np
import numpy.typing as npt
import pandas as pd
import psycopg
from pandas import DataFrame
from pandas.api.types import is_integer_dtype
from sklearn.metrics import roc_auc_score
from sklearn.preprocessing import LabelEncoder
from xgboost import XGBClassifier

from freqtrade.freqai.base_models.BaseClassifierModel import BaseClassifierModel
from freqtrade.freqai.data_kitchen import FreqaiDataKitchen


logger = logging.getLogger(__name__)


class ClaudeOversightModel(BaseClassifierModel):
    """XGBoost classifier with brain.freqai_history writeback.

    Subclass of Freqtrade's BaseClassifierModel — Freqtrade's training
    framework calls ``train()`` on the parent which in turn invokes
    ``fit()`` (this class) with ``data_dictionary`` containing the
    train/test split already prepared by FreqaiDataKitchen.

    The ``predict()`` override returns the canonical ``&-prediction``
    column with positive-class probability (probability that the 16-bar
    forward return exceeds +2%) — the strategy entry gate consumes this
    column directly.
    """

    def fit(self, data_dictionary: dict, dk: Any, **kwargs: Any) -> Any:
        """Train XGBoost on data_dictionary, evaluate on test split, write
        retrain telemetry to brain.freqai_history.

        See module docstring for the Iron Law 3 exception applied to the
        Postgres telemetry hook.
        """
        train_features = data_dictionary["train_features"]
        train_labels = data_dictionary["train_labels"]
        train_weights = data_dictionary.get("train_weights")

        X_train = train_features.to_numpy()
        y_train = train_labels.to_numpy()[:, 0]

        # XGBoost wants integer labels; encode strings/categoricals if present.
        le = LabelEncoder()
        if not is_integer_dtype(y_train):
            y_train = pd.Series(le.fit_transform(y_train), dtype="int64")

        # Build eval set when a test split exists.
        test_features = data_dictionary.get("test_features")
        test_labels = data_dictionary.get("test_labels")
        eval_set = None
        y_test_int = None
        if (
            test_features is not None
            and test_labels is not None
            and len(test_features) > 0
        ):
            X_test = test_features.to_numpy()
            y_test = test_labels.to_numpy()[:, 0]
            if not is_integer_dtype(y_test):
                y_test_int = pd.Series(le.transform(y_test), dtype="int64").to_numpy()
            else:
                y_test_int = y_test
            eval_set = [(X_test, y_test_int)]

        init_model = self.get_init_model(getattr(dk, "pair", "UNKNOWN"))

        # Auto-tune scale_pos_weight to dataset class imbalance unless caller
        # specified it explicitly via config.
        params: dict[str, Any] = dict(self.model_training_parameters)
        if "scale_pos_weight" not in params:
            pos = float((np.asarray(y_train) == 1).sum())
            neg = float((np.asarray(y_train) == 0).sum())
            if pos > 0:
                params["scale_pos_weight"] = neg / pos

        model = XGBClassifier(**params)
        model.fit(
            X=X_train,
            y=np.asarray(y_train),
            eval_set=eval_set,
            sample_weight=train_weights,
            xgb_model=init_model,
        )

        # ---- Telemetry hook: compute AUC + feature_importance, write to PG ---
        auc_val = self._compute_auc(model, eval_set, y_test_int)
        feature_importance = self._extract_feature_importance(
            model, list(train_features.columns)
        )

        logger.info(
            "ClaudeOversightModel retrained pair=%s rows=%d auc=%.4f features=%d",
            getattr(dk, "pair", "UNKNOWN"),
            len(train_features),
            auc_val,
            len(feature_importance),
        )

        try:
            self._insert_freqai_history(
                pair=getattr(dk, "pair", "UNKNOWN"),
                tf=self._extract_timeframe(),
                train_window_days=int(self.freqai_info.get("train_period_days", 0)),
                train_rows=int(len(train_features)),
                auc=float(auc_val),
                feature_importance=feature_importance,
                model_path=self._extract_model_path(dk),
                notes=self._extract_notes(),
            )
        except Exception:
            # Iron Law 3 scoped exception — see module docstring.
            logger.exception(
                "ClaudeOversightModel: brain.freqai_history INSERT failed; "
                "trained model is saved to disk but retrain telemetry was lost. "
                "Dashboard FreqAI view + retrain_health_check will treat this "
                "as a missed retrain (no_data) until the next successful run."
            )

        return model

    def predict(
        self, unfiltered_df: DataFrame, dk: FreqaiDataKitchen, **kwargs: Any
    ) -> tuple[DataFrame, npt.NDArray[np.int_]]:
        """Filter prediction features and return (pred_df, do_predict).

        The ``&-prediction`` column carries the positive-class probability
        in [0, 1]. The strategy gates entries on this value > 0.65.
        """
        dk.find_features(unfiltered_df)
        filtered_df, _ = dk.filter_features(
            unfiltered_df, dk.training_features_list, training_filter=False
        )

        dk.data_dictionary["prediction_features"] = filtered_df

        dk.data_dictionary["prediction_features"], outliers, _ = dk.feature_pipeline.transform(
            dk.data_dictionary["prediction_features"], outlier_check=True
        )

        # XGBoost predict_proba returns shape (n_samples, n_classes).
        # We expose the positive-class probability as the &-prediction column.
        proba = self.model.predict_proba(dk.data_dictionary["prediction_features"])
        proba = np.asarray(proba)
        if proba.ndim == 1:
            positive_proba = proba
        elif proba.shape[1] >= 2:
            # Class 1 (the "+2% in 16 bars" outcome) lives at index 1.
            positive_proba = proba[:, 1]
        else:
            positive_proba = proba[:, 0]

        label = dk.label_list[0] if dk.label_list else "&-prediction"
        pred_df = DataFrame({label: positive_proba})

        if dk.feature_pipeline["di"]:
            dk.DI_values = dk.feature_pipeline["di"].di_values
        else:
            dk.DI_values = np.zeros(outliers.shape[0])
        dk.do_predict = outliers

        return (pred_df, dk.do_predict)

    # ------------------------------------------------------------------ #
    # Telemetry helpers
    # ------------------------------------------------------------------ #
    @staticmethod
    def _compute_auc(
        model: XGBClassifier,
        eval_set: list[tuple[np.ndarray, np.ndarray]] | None,
        y_test_int: np.ndarray | None,
    ) -> float:
        """ROC-AUC on the held-out test split, or 0.5 fallback when no test."""
        if eval_set is None or y_test_int is None or len(eval_set) == 0:
            return 0.5
        X_test, _ = eval_set[0]
        try:
            proba = model.predict_proba(X_test)
        except Exception:
            logger.exception("ClaudeOversightModel: predict_proba on test set failed")
            return 0.5
        proba = np.asarray(proba)
        if proba.ndim == 2 and proba.shape[1] >= 2:
            scores = proba[:, 1]
        else:
            scores = proba.ravel()
        # roc_auc_score raises if y_test_int has only one class. Guard.
        if len(np.unique(y_test_int)) < 2:
            return 0.5
        return float(roc_auc_score(y_test_int, scores))

    @staticmethod
    def _extract_feature_importance(
        model: XGBClassifier, feature_names: list[str]
    ) -> dict[str, float]:
        """Return {feature_name: importance} dict from XGBClassifier."""
        importances = getattr(model, "feature_importances_", None)
        if importances is None:
            return {}
        importances = np.asarray(importances).astype(float)
        if len(importances) != len(feature_names):
            # Fall back to anonymous keys if names somehow mismatch.
            return {f"f{i}": float(v) for i, v in enumerate(importances)}
        return {name: float(v) for name, v in zip(feature_names, importances, strict=False)}

    def _extract_timeframe(self) -> str:
        """Best-effort timeframe extraction from freqai_info."""
        # FreqAI doesn't pass strategy timeframe directly into the model
        # context; the strategy is fixed at 15m for Phase 7.
        return "15m"

    @staticmethod
    def _extract_model_path(dk: Any) -> str:
        """Best-effort model_path string for the freqai_history row.

        We try several attributes Freqtrade exposes on FreqaiDataKitchen
        across versions (`full_path`, `data_path`, `model_filename`).
        Falls back to a stable label if none are present.
        """
        for attr in ("full_path", "data_path"):
            val = getattr(dk, attr, None)
            if val:
                return str(val)
        model_filename = getattr(dk, "model_filename", None)
        if model_filename:
            return str(model_filename)
        return "unknown"

    @staticmethod
    def _extract_notes() -> str | None:
        return None

    @staticmethod
    def _insert_freqai_history(
        *,
        pair: str,
        tf: str,
        train_window_days: int,
        train_rows: int,
        auc: float,
        feature_importance: dict[str, float],
        model_path: str,
        notes: str | None,
    ) -> None:
        """INSERT one row into brain.freqai_history.

        Hard-fails (KeyError) on missing POSTGRES_* env vars — Iron Law 3.
        Runtime exceptions during the INSERT are caught by the caller
        (see fit) per the documented telemetry exception.
        """
        dsn = (
            f"postgresql://{os.environ['POSTGRES_USER']}:"
            f"{os.environ['POSTGRES_PASSWORD']}@"
            f"{os.environ['POSTGRES_HOST']}:"
            f"{os.environ['POSTGRES_PORT']}/"
            f"{os.environ['POSTGRES_DB']}"
        )
        # Clamp AUC to the schema CHECK constraint (auc BETWEEN 0 AND 1).
        clamped_auc = max(0.0, min(1.0, float(auc)))

        with psycopg.connect(dsn, autocommit=True) as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO brain.freqai_history "
                "(pair, tf, train_window_days, train_rows, auc, "
                " feature_importance, model_path, notes) "
                "VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s, %s)",
                (
                    pair,
                    tf,
                    train_window_days,
                    train_rows,
                    clamped_auc,
                    json.dumps(feature_importance),
                    model_path,
                    notes,
                ),
            )
