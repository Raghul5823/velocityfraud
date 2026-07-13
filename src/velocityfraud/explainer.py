"""SHAP-based explainer for the fraud-detection champion model.

Wraps shap.TreeExplainer to give per-prediction feature attributions.
Output: list of (feature_name, feature_value, shap_value) tuples, sorted by
|shap_value| descending. Positive shap_value pushes toward fraud; negative
pushes toward legit.

Usage:
    from velocityfraud.explainer import get_explainer, explain_event

    explainer = get_explainer()
    contributions = explain_event(explainer, X_row, top_n=5)
    for fc in contributions:
        print(fc.feature_name, fc.feature_value, fc.shap_value)

Smoke test:
    uv run python -m velocityfraud.explainer
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

import numpy as np
import pandas as pd
import shap
from loguru import logger

from velocityfraud.predict import get_champion_model


# ---------------------------------------------------------------------------
# Data class for one feature's contribution to a prediction
# ---------------------------------------------------------------------------
@dataclass
class FeatureContribution:
    feature_name: str
    feature_value: float
    shap_value: float

    def as_dict(self) -> dict:
        return {
            "feature_name":  self.feature_name,
            "feature_value": float(self.feature_value),
            "shap_value":    float(self.shap_value),
        }


# ---------------------------------------------------------------------------
# Explainer cache
# ---------------------------------------------------------------------------
@lru_cache(maxsize=1)
def get_explainer() -> shap.TreeExplainer:
    """Build a TreeExplainer for the champion model (cached)."""
    model = get_champion_model()
    logger.info("Building SHAP TreeExplainer for {}", model.__class__.__name__)
    explainer = shap.TreeExplainer(model)
    return explainer


# ---------------------------------------------------------------------------
# Per-event explanation
# ---------------------------------------------------------------------------
def explain_event(
    explainer: shap.TreeExplainer,
    X: pd.DataFrame,
    top_n: int = 5,
) -> list[FeatureContribution]:
    """Compute SHAP values for one row, return top-N contributors by |shap|.

    Args:
        explainer: pre-built TreeExplainer for the champion model.
        X: single-row DataFrame (shape (1, 43)) matching training feature order.
        top_n: how many features to return (sorted by |shap_value| desc).

    Returns:
        list[FeatureContribution] — at most `top_n` entries.
    """
    if len(X) != 1:
        raise ValueError(f"explain_event expects a single row, got {len(X)}")

    shap_values = explainer.shap_values(X)

    # XGBoost binary classifier -> shape (1, n_features); some versions return
    # a list of two arrays (one per class). Normalize to the positive class.
    if isinstance(shap_values, list):
        # multi-output (older API): pick class-1 (fraud)
        shap_values = shap_values[1]
    arr = np.asarray(shap_values).reshape(-1)  # flatten to (n_features,)

    feature_names = X.columns.tolist()
    feature_values = X.iloc[0].values

    pairs = [
        FeatureContribution(
            feature_name=feature_names[i],
            feature_value=float(feature_values[i]),
            shap_value=float(arr[i]),
        )
        for i in range(len(feature_names))
    ]
    # Sort by |shap_value| descending; pick top_n
    pairs.sort(key=lambda fc: abs(fc.shap_value), reverse=True)
    return pairs[:top_n]


# ---------------------------------------------------------------------------
# Smoke test — explain a few synthetic + real events
# ---------------------------------------------------------------------------
def _demo() -> int:
    from velocityfraud.live_features import featurize_event

    sample_event = {
        "event_id":               "demo-001",
        "event_timestamp_ms":     1782731301417,
        "customer_id":            "13926",
        "card_token":             "10c1bf7c3c76e313",
        "amount":                 2454.00,       # high amount (fraud-ish)
        "currency":               "USD",
        "amount_fx_normalised":   2454.00,
        "merchant_id_hash":       "5f59d374246893e0",
        "merchant_name":          "S-MERCHANT-anonymous.com",  # anonymous email (fraud-ish)
        "mcc":                    "5999",
        "merchant_country":       "00",          # unknown country (fraud-ish)
        "ip_address_hash":        "98e58ca964c583e2",
        "device_fingerprint_hash":"a245d9cb16edd5da",
        "geo_distance_km":        0.0,
        "source_label":           "explainer-demo",
        "schema_version":         "v1",
    }

    logger.info("=" * 70)
    logger.info("SHAP EXPLAINER DEMO")
    logger.info("=" * 70)
    logger.info("Synthetic 'suspicious' event: $2454 at S-anonymous.com MCC=5999")

    X, completeness = featurize_event(sample_event)
    logger.info("Feature completeness: {:.2%}", completeness)

    explainer = get_explainer()
    from velocityfraud.predict import predict_proba, get_champion_model
    model = get_champion_model()
    score = float(predict_proba(model, X)[0])
    logger.info("Predicted P(fraud): {:.4f}", score)

    contribs = explain_event(explainer, X, top_n=5)
    logger.info("-" * 70)
    logger.info("Top 5 SHAP contributors (positive = pushes toward FRAUD):")
    logger.info("{:<25s} {:>15s} {:>15s}", "feature", "value", "shap")
    logger.info("-" * 70)
    for fc in contribs:
        arrow = "->FRAUD" if fc.shap_value > 0 else "->LEGIT"
        logger.info("{:<25s} {:>15.4f} {:>+15.4f}  {}",
                    fc.feature_name, fc.feature_value, fc.shap_value, arrow)
    logger.info("=" * 70)
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(_demo())
